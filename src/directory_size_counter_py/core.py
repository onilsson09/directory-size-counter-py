"""Aggregate per-directory byte and file counts over a filesystem tree.

The main entry point is :func:`summarize`, which walks a directory once and
returns a nested :class:`DirectorySummary` tree. Each node reports the total
bytes and file count for the subtree rooted at that directory, so callers can
inspect any level without re-walking the filesystem.

Design decisions:

* Symlinks are never followed. Following them risks infinite loops on cycles
  and double-counting files that are reachable from multiple paths. A symlink
  is treated as a leaf entry: it contributes its own ``lstat`` size to the
  containing directory but is not descended into.
* The walk is depth-first and iterative rather than recursive. Filesystem
  trees can be deeper than Python's recursion limit, and an explicit stack
  avoids a hard-to-diagnose ``RecursionError`` on pathological inputs.
* A directory that cannot be read (for example due to permissions) is still
  represented in the result with zero bytes and zero files. Dropping it would
  make the tree shape depend on the caller's privileges, which is surprising.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

__all__ = ["DirectorySummary", "summarize"]


@dataclass
class DirectorySummary:
    """Aggregated byte and file counts for one directory and its subtree.

    Attributes:
        path: The directory path exactly as supplied to :func:`summarize` (or
            as joined during the walk). It is not normalised.
        total_bytes: Sum of ``st_size`` for every regular file and symlink in
            the subtree, including files in nested directories. Directory
            inode sizes are deliberately excluded because they are an
            implementation detail of the filesystem and vary wildly between
            platforms.
        file_count: Number of regular files and symlinks in the subtree.
        subdirectories: Mapping of child directory name to its summary. The
            keys are the base names, not full paths, which keeps the structure
            readable and avoids duplicating the parent path in every key.
    """

    path: str
    total_bytes: int = 0
    file_count: int = 0
    subdirectories: Dict[str, "DirectorySummary"] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a plain nested ``dict`` representation of this summary.

        This is useful for JSON serialisation and for tests that want to
        compare structure without depending on the dataclass type. The
        ``subdirectories`` mapping is converted recursively.
        """
        return {
            "path": self.path,
            "total_bytes": self.total_bytes,
            "file_count": self.file_count,
            "subdirectories": {
                name: child.to_dict()
                for name, child in self.subdirectories.items()
            },
        }


@dataclass
class _Frame:
    """One entry on the explicit walk stack.

    ``summary`` is the node being built. ``entries`` is the remaining list of
    directory entries to process for that node. ``child_frames`` records the
    child frames that must be folded into this node once they finish.
    """

    summary: DirectorySummary
    entries: List[os.DirEntry]
    child_frames: List["_Frame"] = field(default_factory=list)


def summarize(root: str) -> DirectorySummary:
    """Walk *root* and return a nested summary of bytes and file counts.

    The walk is performed once. Every directory in the tree gets its own
    :class:`DirectorySummary`, and each summary's ``total_bytes`` and
    ``file_count`` include all descendants.

    Args:
        root: Path to the directory to summarise. It may be relative or
            absolute; the value is stored verbatim in the returned tree.

    Returns:
        A :class:`DirectorySummary` for *root*.

    Raises:
        FileNotFoundError: If *root* does not exist.
        NotADirectoryError: If *root* exists but is not a directory.
    """
    # ``os.scandir`` is used instead of ``os.walk`` because it exposes cached
    # ``stat`` results on each entry, which avoids a second syscall per file.
    if not os.path.isdir(root):
        # Distinguish "missing" from "not a directory" so callers get the
        # standard exception they would expect from ``os.scandir`` itself.
        if os.path.exists(root):
            raise NotADirectoryError(root)
        raise FileNotFoundError(root)

    root_summary = DirectorySummary(path=root)
    try:
        root_entries = list(os.scandir(root))
    except OSError:
        # An unreadable root is still a valid, empty summary. Raising here
        # would make the function unusable for privileged-subtree scans.
        return root_summary

    stack: List[_Frame] = [_Frame(summary=root_summary, entries=root_entries)]

    while stack:
        frame = stack[-1]

        if not frame.entries:
            # All entries for this frame have been processed. Fold any child
            # frames that were pushed and then pop this frame.
            stack.pop()
            for child_frame in frame.child_frames:
                child = child_frame.summary
                frame.summary.total_bytes += child.total_bytes
                frame.summary.file_count += child.file_count
                frame.summary.subdirectories[os.path.basename(child.path)] = child
            continue

        entry = frame.entries.pop()
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            # A broken entry (for example a dangling symlink on some
            # filesystems) is treated as a leaf with no size contribution.
            continue

        if is_dir:
            child_path = os.path.join(frame.summary.path, entry.name)
            child_summary = DirectorySummary(path=child_path)
            try:
                child_entries = list(os.scandir(child_path))
            except OSError:
                # Unreadable child: record it with zero counts so the tree
                # shape still reflects the directory's existence.
                child_entries = []
            child_frame = _Frame(summary=child_summary, entries=child_entries)
            frame.child_frames.append(child_frame)
            stack.append(child_frame)
        else:
            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError:
                # If we cannot stat the entry, skip it rather than guessing.
                continue
            frame.summary.total_bytes += stat_result.st_size
            frame.summary.file_count += 1

    return root_summary
