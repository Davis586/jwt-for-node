"""Core implementation for jwt-for-node.

The walker is a plain generator so callers can stop early without paying for
a full traversal. Keeping everything in the standard library means the test
suite runs in a hermetic container with no network access and nothing to pip
install.

A note on depth semantics: depth counts edges, not directories. The root
itself is depth 0, its immediate children are depth 1, and so on. This is the
only definition that makes max_depth easy to reason about -- max_depth=0 means
\"just the root\", max_depth=1 means \"the root and its direct children\".
Choosing to count directories instead would force callers to do off-by-one
arithmetic constantly, and we prefer one clear rule over two compatible ones.
"""

from __future__ import annotations

import os
import stat as _stat
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class Entry:
    """A single filesystem entry produced by iter_entries.

    Fields:
      path: absolute or root-relative filesystem path, exactly as constructed
        during traversal -- we never call os.path.realpath on it, so links are
        preserved textually.
      st: the os.stat_result for path, obtained via os.lstat so symlink targets
        are never followed (crossing into a symlinked tree would make depth
        accounting meaningless and risks cycles). Callers who want to follow
        links can os.stat(path) themselves.
      depth: number of edges from the original root to this entry; see the
        module docstring for the precise convention.
    """

    path: str
    st: os.stat_result
    depth: int


def _type_name(st: os.stat_result) -> str:
    """Classify an lstat result into one of dir/file/link/other.

    We branch on stat.S_ISDIR etc. rather than os.path.isdir because we already
    hold the stat buffer -- re-stating every entry would double the syscall
    count for no benefit.
    """

    mode = st.st_mode
    if _stat.S_ISDIR(mode):
        return "dir"
    if _stat.S_ISREG(mode):
        return "file"
    if _stat.S_ISLNK(mode):
        return "link"
    return "other"


def iter_entries(
    root: str,
    *,
    types: Optional[set[str]] = None,
    max_depth: Optional[int] = None,
    same_device: bool = False,
) -> Iterator[Entry]:
    """Lazily yield Entry records for everything under root.

    Args:
      root: directory to start from. Must be an existing directory; anything
        else raises ValueError. We refuse to walk a path that is not a
        directory because the traversal model does not cover it and returning
        an empty iterator silently would mask caller mistakes.
      types: if set, only yield entries whose classification (dir/file/link/
        other) is in the set. The root is always subject to this filter.
      max_depth: if not None, stop descending past this depth. The root is
        depth 0. None means \"unlimited\".
      same_device: if True, never cross into a different filesystem device.
        We capture the root's st_dev once and, when entering a subdirectory,
        compare its st_dev; a mismatch stops recursion at that directory but
        still yields the directory itself (its name and stat are visible).

    The traversal is pre-order and deterministic: at each directory we read
    entries via os.scandir, sort them by name, and recurse. Sorting keeps
    tests stable regardless of inode allocation order, which otherwise makes
    assertions on output order flaky.
    """

    if not isinstance(root, str):
        raise TypeError("root must be a string path")
    if not os.path.isdir(root):
        raise ValueError("root does not exist or is not a directory: %r" % root)

    root = os.path.abspath(root)
    root_st = os.lstat(root)
    root_device = root_st.st_dev

    # os.path.join is used rather than string concatenation so that absolute
    # children are respected and trailing-slash edge cases on the root are
    # handled uniformly across platforms.
    def _walk(path: str, st: os.stat_result, depth: int) -> Iterator[Entry]:
        if max_depth is not None and depth > max_depth:
            return

        entry = Entry(path=path, st=st, depth=depth)
        if types is None or _type_name(st) in types:
            yield entry

        if not _stat.S_ISDIR(st.st_mode):
            return

        # Guard against symlinked directories sneaking across device or cycle
        # boundaries; we deliberately use lstat above so symlinks never expand
        # into the walk. A directory can only be descended into if it is a
        # real directory on disk.
        try:
            children = sorted(os.scandir(path), key=lambda c: c.name)
        except (PermissionError, OSError):
            # Inaccessible directories yield nothing more; the entry itself
            # has already been produced so the caller knows the path exists.
            return

        for child in children:
            child_path = os.path.join(path, child.name)
            child_st = os.lstat(child_path)

            if same_device and _stat.S_ISDIR(child_st.st_mode):
                if child_st.st_dev != root_device:
                    # Yield the mount point itself so a backup tool can record
                    # it as a boundary, but do not step inside.
                    boundary = Entry(path=child_path, st=child_st, depth=depth + 1)
                    if types is None or _type_name(child_st) in types:
                        yield boundary
                    continue

            yield from _walk(child_path, child_st, depth + 1)

    yield from _walk(root, root_st, 0)
