"""Public API for directory-size-counter-py.

This module re-exports the small surface of the library so callers can do
``from directory_size_counter_py import summarize`` without knowing the
internal module layout.
"""

from .core import DirectorySummary, summarize

__all__ = ["DirectorySummary", "summarize"]
