"""jwt-for-node: lazy filesystem iteration with type, depth, and device filtering.

Public API:
  - iter_entries: walk a directory tree lazily, yielding Entry records.
  - Entry: a small dataclass bundling a path, its os.stat result, and the
    entry's depth relative to the root passed to iter_entries.

The name is deliberately unremarkable; it exists so downstream code can pin a
specific, dependency-free walker without caring about the host environment.
"""

from .core import Entry, iter_entries

__all__ = ["Entry", "iter_entries"]
