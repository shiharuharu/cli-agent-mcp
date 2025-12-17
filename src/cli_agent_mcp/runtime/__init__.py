"""Runtime module for subprocess management and event streaming.

This module provides isolated process execution with proper signal handling
and reliable termination for CLI subprocess management.
"""

from __future__ import annotations

from .process_runner import ProcessRunner, ProcessSpec

__all__ = [
    "ProcessRunner",
    "ProcessSpec",
]
