"""
tool_metadata.py
----------------
MCP Tool 1 — get_file_metadata

Reads identity/authorship metadata from a local .sldprt file using the
SolidWorks COM API (IModelDoc2).

SummaryInfo index map (confirmed on SW 2026 Student Edition):
  [5]  = Author (login name of file creator)
  [6]  = Created date (short format)
  [7]  = Last saved date (short format)
  [8]  = Created date (long format)
  [9]  = Last saved date (long format)

GetPathName is a property (not a method) on this SW version.
CustomPropertyManager.GetNames() returns None on Student Edition —
we use GetCustomInfoNames() fallback instead.

Output schema
-------------
{
    "last_saved_by":           str | None,
    "author":                  str | None,
    "last_saved_date":         str | None,   # ISO-8601
    "custom_properties":       dict,
    "raw_identity_properties": dict,
    "error":                   str | None
}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pythoncom
import win32com.client

from sw_connection import get_connection

logger = logging.getLogger(__name__)

IDENTITY_KEYWORDS = {
    "author", "user", "username", "student", "id", "owner",
    "email", "name", "created by", "createdby",
}

# Confirmed SummaryInfo indices for SW 2026 Student Edition
_SI_AUTHOR       = 5   # login name of creator  e.g. "gkermani"
_SI_CREATED_SHORT = 6  # "5/27/2022 12:58:12 PM"
_SI_SAVED_SHORT   = 7  # "12/11/2024 1:12:49 PM"
_SI_CREATED_LONG  = 8  # "Friday, May 27, 2022 12:58:12 PM"
_SI_SAVED_LONG    = 9  # "Wednesday, December 11, 2024 1:12:49 PM"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_file_metadata(filepath: str) -> dict:
    result: dict[str, Any] = {
        "last_saved_by": None,
        "author": None,
        "last_saved_date": None,
        "custom_properties": {},
        "raw_identity_properties": {},
        "error": None,
    }

    path = Path(filepath).resolve()
    if not path.exists():
        result["error"] = f"File not found: {path}"
        return result

    doc = None
    conn = None

    try:
        conn = get_connection()
        doc, _ = conn.open_part_silent(str(path))
        _read_summary_properties(doc, result)
        _read_custom_properties(doc, result)
    except Exception as exc:
        logger.exception("Error reading metadata from '%s'", path)
        result["error"] = str(exc)
    finally:
        if conn is not None:
            try:
                conn.close_doc(str(path))
            except Exception as exc:
                logger.warning("Failed to close doc: %s", exc)

    # Build identity subset
    result["raw_identity_properties"] = _filter_identity(result["custom_properties"])
    if result["author"]:
        result["raw_identity_properties"].setdefault("Author", result["author"])

    return result


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _read_summary_properties(doc, result: dict) -> None:
    """
    Read author and dates from SummaryInfo using confirmed index map.
    """
    # Author
    try:
        val = doc.SummaryInfo(_SI_AUTHOR)
        if val and str(val).strip():
            result["author"] = str(val).strip()
    except Exception:
        pass

    # Last saved date — prefer short format for easier parsing
    for idx in (_SI_SAVED_SHORT, _SI_SAVED_LONG):
        try:
            val = doc.SummaryInfo(idx)
            if val and str(val).strip():
                parsed = _parse_sw_date(str(val).strip())
                if parsed:
                    result["last_saved_date"] = parsed
                    break
        except Exception:
            pass

    # Fallback: filesystem mtime
    if result["last_saved_date"] is None:
        try:
            # GetPathName is a property on this SW version, not a method
            sw_path = doc.GetPathName
            if callable(sw_path):
                sw_path = sw_path()
            p = Path(str(sw_path))
            if p.exists():
                dt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                result["last_saved_date"] = dt.isoformat()
        except Exception:
            pass


def _read_custom_properties(doc, result: dict) -> None:
    """
    Read custom properties. Tries multiple API approaches since
    Student Edition has partial COM support.
    """
    # Approach A: Extension.CustomPropertyManager (SW 2014+)
    try:
        mgr = doc.Extension.CustomPropertyManager("")
        if mgr is not None:
            # GetNames may return None on Student Edition
            names_raw = mgr.GetNames()
            names = list(names_raw) if names_raw is not None else []

            if names:
                for name in names:
                    if not name:
                        continue
                    try:
                        # Get4: name, use_cached -> val, resolved_val, was_resolved
                        val, resolved, was_res = mgr.Get4(name, False)
                        value = str(resolved or val or "").strip()
                        if value:
                            result["custom_properties"][str(name)] = value
                    except Exception:
                        try:
                            val = mgr.Get(name)
                            if val and str(val).strip():
                                result["custom_properties"][str(name)] = str(val).strip()
                        except Exception:
                            pass
                return  # success — skip fallback approaches
    except Exception as e:
        logger.debug("CustomPropertyManager approach failed: %s", e)

    # Approach B: GetCustomInfoNames (older API)
    try:
        names_raw = doc.GetCustomInfoNames()
        # Returns a tuple on success, None if no props
        names = list(names_raw) if names_raw else []
        for name in names:
            if not name:
                continue
            try:
                # GetCustomInfo2(name, config) -> (value, type)
                val, _ = doc.GetCustomInfo2(name, "")
                if val and str(val).strip():
                    result["custom_properties"][str(name)] = str(val).strip()
            except Exception:
                try:
                    val = doc.GetCustomInfo(name)
                    if val and str(val).strip():
                        result["custom_properties"][str(name)] = str(val).strip()
                except Exception:
                    pass
        if names:
            return
    except Exception as e:
        logger.debug("GetCustomInfoNames approach failed: %s", e)

    # Approach C: IPartDoc cast — try part-specific property access
    try:
        part = doc.GetPartDoc() if hasattr(doc, "GetPartDoc") else None
        if part is None:
            part = doc
        names_raw = part.GetCustomInfoNames()
        names = list(names_raw) if names_raw else []
        for name in names:
            try:
                val = part.GetCustomInfo(name)
                if val and str(val).strip():
                    result["custom_properties"][str(name)] = str(val).strip()
            except Exception:
                pass
    except Exception as e:
        logger.debug("IPartDoc approach failed: %s", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sw_date(date_str: str) -> str | None:
    formats = [
        "%m/%d/%Y %I:%M:%S %p",   # "12/11/2024 1:12:49 PM"  ← confirmed SW format
        "%m/%d/%Y %H:%M:%S",
        "%A, %B %d, %Y %I:%M:%S %p",  # "Wednesday, December 11, 2024 1:12:49 PM"
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return date_str or None


def _is_identity_key(name: str) -> bool:
    name_lower = name.lower().strip()
    return any(kw in name_lower for kw in IDENTITY_KEYWORDS)


def _filter_identity(custom_props: dict) -> dict:
    return {k: v for k, v in custom_props.items() if _is_identity_key(k)}
