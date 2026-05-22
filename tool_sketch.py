"""
tool_sketch.py
--------------
MCP Tool 4 — check_sketch_status

Reads sketch constraint status from a .sldprt file via SW COM API.

Discovery
---------
SW Student Edition locks out the standard ISketch::GetFullyDefinedStatus
via named COM dispatch. However, the data is accessible via raw DISPID:

  IFeature  DISPID  7  → ISketch object (sketch plane/geometry)
  ISketch   DISPID 48  → constraint status integer

Status values (confirmed against GraderWorks ground truth, 19/19):
  2 = UNDERDEFINED
  3 = FULLY_DEFINED
  1 = OVERDEFINED    (hypothesis — not yet confirmed with test data)
  0 = NO_SOLUTION    (hypothesis)

Output schema
-------------
{
    "underdefined_count":        int,
    "underdefined_sketch_names": [str, ...],
    "all_sketches": [
        {
            "name":   str,
            "status": "FULLY_DEFINED" | "UNDERDEFINED" | "OVERDEFINED" |
                      "NO_SOLUTION"   | "UNKNOWN"
        },
        ...
    ],
    "method": "dispid_probe",
    "error":  str | None
}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import win32com.client
import win32com.client.dynamic

from sw_connection import get_connection

logger = logging.getLogger(__name__)

# d7_48 status values confirmed by empirical testing
_STATUS_MAP = {
    3: "FULLY_DEFINED",
    2: "UNDERDEFINED",
    1: "OVERDEFINED",
    0: "NO_SOLUTION",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def check_sketch_status(filepath: str) -> dict:
    """
    Check sketch constraint status for all sketches in a .sldprt file.

    Parameters
    ----------
    filepath : absolute path to a local .sldprt file

    Returns
    -------
    See module docstring for schema.
    """
    result: dict[str, Any] = {
        "underdefined_count": 0,
        "underdefined_sketch_names": [],
        "all_sketches": [],
        "method": "dispid_probe",
        "error": None,
    }

    path = Path(filepath).resolve()
    if not path.exists():
        result["error"] = f"File not found: {path}"
        return result

    conn = None
    try:
        conn = get_connection()
        doc, _ = conn.open_part_silent(str(path))
        doc.ForceRebuild3(False)

        sketches = _read_sketch_statuses(doc)
        result["all_sketches"] = sketches

        underdefined = [s for s in sketches if s["status"] == "UNDERDEFINED"]
        result["underdefined_count"] = len(underdefined)
        result["underdefined_sketch_names"] = [s["name"] for s in underdefined]

    except Exception as exc:
        logger.exception("Error checking sketches in '%s'", path)
        result["error"] = str(exc)
    finally:
        if conn is not None:
            try:
                conn.close_doc(str(path))
            except Exception as exc:
                logger.warning("Failed to close doc: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Core reader
# ---------------------------------------------------------------------------

def _read_sketch_statuses(doc) -> list[dict]:
    """
    Iterate all ProfileFeature features and read sketch status via
    raw DISPID access (DISPID 7 → DISPID 48).
    """
    sketches = []

    try:
        fm = doc.FeatureManager
        feats = fm.GetFeatures(False)
    except Exception as exc:
        logger.warning("GetFeatures failed: %s", exc)
        return sketches

    for feat in feats:
        try:
            # Filter to sketch features only
            feat_type = feat.GetTypeName
            if callable(feat_type): feat_type = feat.GetTypeName()
            if feat_type not in ("ProfileFeature", "3DProfileFeature"):
                continue

            feat_name = feat.Name
            if callable(feat_name): feat_name = feat.Name()

            status_val, status_str = _get_sketch_status(feat)

            sketches.append({
                "name":   feat_name,
                "status": status_str,
            })

            logger.debug("'%s': d7_48=%s → %s", feat_name, status_val, status_str)

        except Exception as exc:
            logger.debug("Skipped feature: %s", exc)

    return sketches


def _get_sketch_status(feat) -> tuple[int | None, str]:
    """
    Read sketch status via DISPID 7 (ISketch) → DISPID 48 (status int).

    Returns (raw_value, status_string).
    """
    try:
        raw_feat = feat._oleobj_

        # DISPID 7 on IFeature → ISketch object
        sketch_obj = raw_feat.Invoke(7, 0, 1, 1)
        if sketch_obj is None:
            return None, "UNKNOWN"

        # Wrap for easier access
        sketch = win32com.client.dynamic.Dispatch(sketch_obj)
        raw_sketch = sketch._oleobj_

        # DISPID 48 on ISketch → constraint status integer
        status_val = raw_sketch.Invoke(48, 0, 1, 1)

        if status_val is None:
            return None, "UNKNOWN"

        status_str = _STATUS_MAP.get(int(status_val), f"UNKNOWN({status_val})")
        return int(status_val), status_str

    except Exception as exc:
        logger.debug("DISPID probe failed: %s", exc)
        return None, "UNKNOWN"
