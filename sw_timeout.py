"""
sw_timeout.py
-------------
Timeout wrapper for SW COM calls that may stall.

SW Student Edition occasionally hangs on file open, especially
when the popup dismisser is slow or a file is corrupted.

Usage
-----
    from sw_timeout import with_timeout, SWTimeoutError

    try:
        doc = with_timeout(conn.open_part_silent, filepath, timeout=30)
    except SWTimeoutError:
        # SW stalled — attempt recovery
        recover_from_stall()
"""

from __future__ import annotations

import ctypes
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SWTimeoutError(Exception):
    """Raised when a SW COM call exceeds the timeout."""
    pass


def with_timeout(fn: Callable, *args, timeout: float = 30.0, **kwargs) -> Any:
    """
    Call fn(*args, **kwargs) with a timeout.
    Raises SWTimeoutError if the call doesn't complete in time.

    Note: Python threads can't be forcibly killed, so on timeout we
    raise the exception in the calling thread but the background thread
    may continue running. This is safe for COM calls since SW is an
    out-of-process server.
    """
    result: dict = {"value": None, "error": None, "done": False}

    def target():
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as exc:
            result["error"] = exc
        finally:
            result["done"] = True

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if not result["done"]:
        raise SWTimeoutError(
            f"{fn.__name__} timed out after {timeout}s — "
            "SW may be stalled. Call recover_from_stall() to attempt recovery."
        )

    if result["error"] is not None:
        raise result["error"]

    return result["value"]
