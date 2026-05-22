"""
tool_export.py
--------------
MCP Tool 0 — export_file (helper used by compare_shapes)

Exports a .sldprt file to STL, STEP, or IGES using SaveAs.
Confirmed working on SW 2026 Student Edition via doc.SaveAs(path).

STL Quality Settings
--------------------
SolidWorks STL resolution is controlled by two tolerance values set via
GetUserPreferenceDoubleValue before export:

  swUserPreferenceDoubleValue_e.swSTLDeviation     (swSTLDeviation = 41)
    - Chord deviation in model units (mm)
    - Lower = finer mesh = larger file
    - Default: ~0.5 mm   Fine: 0.05 mm   Very fine: 0.01 mm

  swUserPreferenceDoubleValue_e.swSTLAngleTolerance (swSTLAngleTolerance = 42)
    - Angular deviation in radians between adjacent facet normals
    - Lower = finer mesh on curved surfaces
    - Default: ~0.5 rad  Fine: 0.1 rad   Very fine: 0.05 rad

Quality presets (STL_QUALITY constant):
  "draft"     — fast, coarse  (deviation=0.5,  angle=0.5)
  "standard"  — SW default    (deviation=0.1,  angle=0.2)
  "fine"      — good quality  (deviation=0.05, angle=0.1)   ← recommended
  "very_fine" — maximum       (deviation=0.01, angle=0.05)  ← slow, large files

Output schema
-------------
{
    "success":     bool,
    "output_path": str | None,
    "error":       str | None
}
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from sw_connection import get_connection

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {"STL", "STEP", "IGES"}

_FORMAT_EXT = {
    "STL":  ".stl",
    "STEP": ".step",
    "IGES": ".igs",
}

# ---------------------------------------------------------------------------
# STL quality presets
# swUserPreferenceDoubleValue_e constants confirmed on SW 2026 Student Edition
# ---------------------------------------------------------------------------
_STL_DEVIATION_PREF     = 41   # swSTLDeviation
_STL_ANGLE_TOL_PREF     = 42   # swSTLAngleTolerance

_STL_QUALITY_PRESETS = {
    "draft":     {"deviation": 0.5,   "angle": 0.5},
    "standard":  {"deviation": 0.1,   "angle": 0.2},
    "fine":      {"deviation": 0.05,  "angle": 0.1},
    "very_fine": {"deviation": 0.01,  "angle": 0.05},
}

# Default quality for all grading exports
STL_QUALITY = "fine"


def _set_stl_quality(app, quality: str = STL_QUALITY) -> tuple[float, float]:
    """
    Set SolidWorks STL export resolution preferences.
    Returns the previous (deviation, angle) values so they can be restored.
    """
    preset = _STL_QUALITY_PRESETS.get(quality, _STL_QUALITY_PRESETS["fine"])

    prev_deviation = None
    prev_angle     = None

    try:
        prev_deviation = app.GetUserPreferenceDoubleValue(_STL_DEVIATION_PREF)
        prev_angle     = app.GetUserPreferenceDoubleValue(_STL_ANGLE_TOL_PREF)
    except Exception as e:
        logger.debug("Could not read STL preferences: %s", e)

    try:
        app.SetUserPreferenceDoubleValue(_STL_DEVIATION_PREF, preset["deviation"])
        app.SetUserPreferenceDoubleValue(_STL_ANGLE_TOL_PREF, preset["angle"])
        logger.debug(
            "STL quality set to '%s': deviation=%.4f mm, angle=%.4f rad",
            quality, preset["deviation"], preset["angle"]
        )
    except Exception as e:
        logger.warning("Could not set STL quality preferences: %s", e)

    return prev_deviation, prev_angle


def _restore_stl_quality(app, prev_deviation, prev_angle) -> None:
    """Restore STL preferences to their previous values."""
    try:
        if prev_deviation is not None:
            app.SetUserPreferenceDoubleValue(_STL_DEVIATION_PREF, prev_deviation)
        if prev_angle is not None:
            app.SetUserPreferenceDoubleValue(_STL_ANGLE_TOL_PREF, prev_angle)
    except Exception as e:
        logger.debug("Could not restore STL preferences: %s", e)


def export_file(
    filepath: str,
    format: str,
    output_path: str,
    quality: str = STL_QUALITY,
) -> dict:
    """
    Export a .sldprt file to STL, STEP, or IGES.

    Parameters
    ----------
    filepath    : absolute path to source .sldprt
    format      : "STL" | "STEP" | "IGES"
    output_path : destination path for exported file
    quality     : STL quality preset — "draft" | "standard" | "fine" | "very_fine"
                  Only applies to STL exports. Default: "fine"

    Returns
    -------
    {"success": bool, "output_path": str | None, "error": str | None}
    """
    result: dict[str, Any] = {
        "success": False,
        "output_path": None,
        "error": None,
    }

    fmt = format.upper().strip()
    if fmt not in SUPPORTED_FORMATS:
        result["error"] = f"Unsupported format '{format}'. Use: {SUPPORTED_FORMATS}"
        return result

    src = Path(filepath).resolve()
    if not src.exists():
        result["error"] = f"Source file not found: {src}"
        return result

    dst = Path(output_path).resolve()

    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        result["error"] = f"Cannot create output directory: {exc}"
        return result

    expected_ext = _FORMAT_EXT[fmt]
    if dst.suffix.lower() != expected_ext:
        dst = dst.with_suffix(expected_ext)

    conn = None
    prev_deviation = None
    prev_angle     = None

    try:
        conn = get_connection()
        doc, _ = conn.open_part_silent(str(src))
        app = conn.application

        # Set STL quality before export (STL only)
        if fmt == "STL":
            prev_deviation, prev_angle = _set_stl_quality(app, quality)

        ok = doc.SaveAs(str(dst))

        if ok and dst.exists() and dst.stat().st_size > 0:
            result["success"]     = True
            result["output_path"] = str(dst)
            logger.info(
                "Exported '%s' → '%s' (%d bytes, quality=%s)",
                src.name, dst, dst.stat().st_size,
                quality if fmt == "STL" else "n/a"
            )
        else:
            result["error"] = f"SaveAs returned {ok} but output file missing or empty."

    except Exception as exc:
        logger.exception("Export failed for '%s'", src)
        result["error"] = str(exc)
    finally:
        # Always restore STL preferences
        if fmt == "STL" and conn is not None:
            try:
                _restore_stl_quality(conn.application, prev_deviation, prev_angle)
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close_doc(str(src))
            except Exception as exc:
                logger.warning("Failed to close doc after export: %s", exc)

    return result
