# directory-size-counter-py

Walk a directory tree once and get back a nested summary of byte counts and file counts for every subdirectory.

```python
from directory_size_counter_py import summarize

summary = summarize(".")
print(summary.total_bytes)
print(summary.file_count)
for name, child in summary.subdirectories.items():
    print(name, child.total_bytes, child.file_count)
```

## Why this exists

The standard library gives you `os.walk` and `os.scandir`, but neither aggregates totals for you. If you want to know "how big is `src/` and how many files are under it?" you end up either re-walking the tree for every subdirectory or writing the same accumulator by hand. This library does the walk once and returns a tree of `DirectorySummary` objects where every node already carries its subtree totals, so you can ask that question at any level without touching the filesystem again.

The trade-off is that the whole tree is held in memory at once. For a repository or a home directory that is fine; for a filesystem with tens of millions of files you would want a streaming interface instead. This library deliberately picks the simple, inspectable result over a callback-based one.

## The awkward edge

Symlinks are counted as leaves but never followed. A symlink contributes its own `lstat` size to its parent directory and increments the file count, but the walk does not descend into a symlinked directory even if it points somewhere real. This avoids infinite loops on cycles and avoids double-counting files that are reachable from more than one path. It also means a symlink to a directory shows up as a file, not as a subdirectory, in the summary.

Directories that cannot be read (for example because of permissions) are still present in the result, with zero bytes and zero files. The tree shape stays stable regardless of the caller's privileges.

## API

### `summarize(root: str) -> DirectorySummary`

Walk `root` and return its summary. Raises `FileNotFoundError` if `root` does not exist and `NotADirectoryError` if it exists but is not a directory. An unreadable `root` returns an empty summary rather than raising.

### `DirectorySummary`

A dataclass with these fields:

- `path: str` — the directory path as supplied or as joined during the walk, not normalised.
- `total_bytes: int` — sum of `st_size` for every regular file and symlink in the subtree. Directory inode sizes are excluded because they are filesystem-specific.
- `file_count: int` — number of regular files and symlinks in the subtree.
- `subdirectories: dict[str, DirectorySummary]` — child summaries keyed by base name.

It also has a `to_dict()` method that returns the same structure as nested plain dictionaries, which is convenient for JSON serialisation or for comparing trees in tests.
