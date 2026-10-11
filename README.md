# jwt-for-node

`jwt-for-node` lazily walks a filesystem tree from a root directory and yields one `Entry` per filesystem node, annotated with its `os.stat_result` and its depth relative to the root. Traversal can be bounded by entry type, maximum depth, and device boundary.

## Usage

```python
import os
import tempfile

from jwt_for_node import iter_entries, Entry

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "sub"))
with open(os.path.join(tmp, "sub", "data.txt"), "w") as f:
    f.write("")

for entry in iter_entries(tmp, types={"file"}, max_depth=3, same_device=True):
    assert isinstance(entry, Entry)
    print(entry.depth, entry.path, entry.st.st_size)
```

`iter_entries(root, *, types=None, max_depth=None, same_device=False)` returns a generator of `Entry(path: str, st: os.stat_result, depth: int)`.

## Why

Every backup, sync, and audit tool eventually needs "walk this tree, but stop where I say." The standard library's `os.walk` is eager, yields tuples rather than records, and gives no first-class hook for "do not cross mount points." This library exists to fill that gap with a single, dependency-free generator.

Depth counts edges, not directories: the root is depth 0, its immediate children are depth 1. `max_depth=0` therefore means "just the root." The convention is documented once here and applied uniformly; callers who wanted directory-counting semantics can add `depth + 1` themselves.

## Edge cases you will hit

- **Symlinks are never followed.** `iter_entries` uses `lstat`, so a symlink to a directory is yielded as a `link` entry and not descended into. This is deliberate: following links makes depth accounting meaningless and risks cycles.
- **Inaccessible directories yield silently.** A `PermissionError` or other `OSError` mid-walk stops recursion at that directory; the directory entry itself has already been produced. Callers who need to distinguish "empty" from "unreadable" should `os.scandir` the path themselves.
- **`same_device` yields the mount-point directory but does not step inside it.** When a subdirectory lives on a different `st_dev` than the root, the entry is still produced (so a backup tool can record the boundary) but its contents are not traversed.
- **`types` is a set membership test against the strings `dir`, `file`, `link`, `other`.** Passing a list or a tuple will work but is not officially supported; use a `set`.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```
