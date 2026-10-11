"""Tests for jwt-for-node.core.

All tests build a fixture tree under a tempfile directory and assert on the
entries produced by iter_entries. Nothing touches the real filesystem outside
that temp dir, so the suite is hermetic and deterministic.
"""

import os
import stat
import tempfile
import unittest

from jwt_for_node.core import Entry, iter_entries


class _Fixture:
    """Tiny helper to build a throwaway tree without sprinkling os.makedirs
    and open() calls through every test body."""

    def __init__(self, spec):
        # spec maps relative path -> 'file'|'dir'|'link:target'. We create under
        # a fresh tempdir so cleanup is automatic and so st_dev values are the
        # container's own device, which our same_device tests rely on.
        self.root = tempfile.mkdtemp(prefix="jwt_for_node_")
        dirs = []
        for rel, kind in spec.items():
            full = os.path.join(self.root, rel)
            if kind == "dir":
                os.makedirs(full, exist_ok=True)
                dirs.append(full)
            elif kind == "file":
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as fh:
                    fh.write("")
            elif kind.startswith("link:"):
                target = os.path.join(self.root, kind.split(":", 1)[1])
                os.makedirs(os.path.dirname(full), exist_ok=True)
                os.symlink(target, full)
            else:
                raise ValueError("unknown spec kind: %r" % kind)

    def close(self):
        # best-effort teardown; failures here do not affect test outcome.
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=False):
            for name in dirnames + filenames:
                try:
                    os.remove(os.path.join(dirpath, name))
                except OSError:
                    pass
                try:
                    os.rmdir(os.path.join(dirpath, name))
                except OSError:
                    pass
        try:
            os.rmdir(self.root)
        except OSError:
            pass


class IterEntriesTests(unittest.TestCase):
    def setUp(self):
        self._fixtures = []

    def tearDown(self):
        for fx in self._fixtures:
            fx.close()

    def _fixture(self, spec):
        fx = _Fixture(spec)
        self._fixtures.append(fx)
        return fx

    def test_root_must_exist(self):
        with self.assertRaises(ValueError):
            list(iter_entries("/no/such/path/here"))

    def test_root_must_be_a_directory(self):
        fx = self._fixture({"plain.txt": "file"})
        with self.assertRaises(ValueError):
            list(iter_entries(os.path.join(fx.root, "plain.txt")))

    def test_root_only_when_max_depth_zero(self):
        fx = self._fixture(
            {
                "a": "dir",
                "a/b.txt": "file",
                "top.txt": "file",
            }
        )
        entries = list(iter_entries(fx.root, max_depth=0))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, os.path.abspath(fx.root))
        self.assertEqual(entries[0].depth, 0)

    def test_depth_counts_edges(self):
        fx = self._fixture(
            {
                "a": "dir",
                "a/b": "dir",
                "a/b/c.txt": "file",
            }
        )
        depths = {e.path: e.depth for e in iter_entries(fx.root)}
        self.assertEqual(depths[os.path.abspath(fx.root)], 0)
        self.assertEqual(depths[os.path.join(fx.root, "a")], 1)
        self.assertEqual(depths[os.path.join(fx.root, "a", "b")], 2)
        self.assertEqual(depths[os.path.join(fx.root, "a", "b", "c.txt")], 3)

    def test_type_filter_files_only(self):
        fx = self._fixture(
            {
                "d": "dir",
                "d/inner.txt": "file",
                "leaf.txt": "file",
            }
        )
        got = [e.path for e in iter_entries(fx.root, types={"file"})]
        self.assertIn(os.path.join(fx.root, "leaf.txt"), got)
        self.assertIn(os.path.join(fx.root, "d", "inner.txt"), got)
        self.assertFalse(any(stat.S_ISDIR(e.st.st_mode) for e in iter_entries(fx.root, types={"file"})))

    def test_type_filter_dirs_only(self):
        fx = self._fixture(
            {
                "d": "dir",
                "d/inner": "dir",
                "d/inner/leaf.txt": "file",
                "top.txt": "file",
            }
        )
        paths = [e.path for e in iter_entries(fx.root, types={"dir"})]
        self.assertIn(os.path.join(fx.root, "d"), paths)
        self.assertIn(os.path.join(fx.root, "d", "inner"), paths)
        self.assertNotIn(os.path.join(fx.root, "d", "inner", "leaf.txt"), paths)
        self.assertNotIn(os.path.join(fx.root, "top.txt"), paths)

    def test_pre_order_and_sorted(self):
        # Children are sorted by name at every level, so output is stable.
        fx = self._fixture(
            {
                "z.txt": "file",
                "a.txt": "file",
                "m.txt": "file",
            }
        )
        names = [os.path.basename(e.path) for e in iter_entries(fx.root)]
        # index 0 is the root dir itself; the rest should be a-sorted.
        self.assertEqual(names[1:], ["a.txt", "m.txt", "z.txt"])

    def test_symlink_is_not_followed(self):
        # A symlink whose target is a directory must NOT be descended into.
        # We point it at a real directory to make sure the walker still treats
        # it as a leaf link.
        fx = self._fixture(
            {
                "real_dir": "dir",
                "real_dir/inside.txt": "file",
                "link_to_dir": "link:real_dir",
            }
        )
        names = {os.path.basename(e.path) for e in iter_entries(fx.root)}
        self.assertIn("link_to_dir", names)
        self.assertIn("inside.txt", names)
        # the symlink must be classified as a link, not a dir
        link_entry = next(e for e in iter_entries(fx.root) if os.path.basename(e.path) == "link_to_dir")
        self.assertTrue(stat.S_ISLNK(link_entry.st.st_mode))

    def test_same_device_does_not_block_native_subdirs(self):
        fx = self._fixture(
            {
                "a": "dir",
                "a/b": "dir",
                "a/b/c.txt": "file",
            }
        )
        paths = [e.path for e in iter_entries(fx.root, same_device=True)]
        self.assertIn(os.path.join(fx.root, "a", "b", "c.txt"), paths)

    def test_entry_fields_present(self):
        fx = self._fixture({"x.txt": "file"})
        e = next(iter(iter_entries(fx.root)))
        self.assertIsInstance(e, Entry)
        self.assertIsInstance(e.path, str)
        self.assertIsInstance(e.st, os.stat_result)
        self.assertIsInstance(e.depth, int)

    def test_empty_root_yields_just_root(self):
        fx = self._fixture({})
        entries = list(iter_entries(fx.root))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, os.path.abspath(fx.root))

    def test_max_depth_one_includes_direct_children(self):
        fx = self._fixture(
            {
                "a": "dir",
                "a/b.txt": "file",
                "top.txt": "file",
            }
        )
        paths = [e.path for e in iter_entries(fx.root, max_depth=1)]
        self.assertIn(os.path.join(fx.root, "top.txt"), paths)
        self.assertIn(os.path.join(fx.root, "a"), paths)
        self.assertNotIn(os.path.join(fx.root, "a", "b.txt"), paths)

    def test_root_filter_obeys_types(self):
        # If types excludes 'dir' and the root is a dir, we yield nothing.
        fx = self._fixture({"x.txt": "file"})
        entries = list(iter_entries(fx.root, types={"file"}))
        self.assertEqual(len(entries), 1)
        self.assertEqual(os.path.basename(entries[0].path), "x.txt")


if __name__ == "__main__":
    unittest.main()
