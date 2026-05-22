"""
tool_mass.py
------------
MCP Tool 2 — get_mass_properties

Reads mass, volume, surface area, center of mass, density, and material
assignment from a local .sldprt file via the SolidWorks COM API.

GetMassProperties index map (confirmed SW 2026 Student Edition):
  [0] = center of mass X  (meters)
  [1] = center of mass Y  (meters)
  [2] = center of mass Z  (meters)
  [3] = volume            (m³)   ← non-standard order
  [4] = surface area      (m²)
  [5] = mass              (kg)
  [6-11] = moments of inertia (not used)

  NOTE: SW Student Edition returns (CoM x3, volume, surface_area, mass, inertia x6)
  NOT the standard (CoM x3, mass, volume, surface_area, inertia x6) order.
  Verified by cross-checking against brass density = 8500 kg/m³.

Unit conversions applied:
  volume:       m³  → mm³  (* 1e9)
  surface_area: m²  → mm²  (* 1e6)
  center_of_mass: m → mm   (* 1000)
  mass and density stay in kg / (kg/mm³)

Output schema
-------------
{
    "mass":             float | None,   # kg
    "volume":           float | None,   # mm³
    "surface_area":     float | None,   # mm²
    "center_of_mass":   {"x": float, "y": float, "z": float} | None,  # mm
    "density":          float | None,   # kg/mm³
    "material_assigned": bool,
    "material_name":    str | None,
    "error":            str | None
}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sw_connection import get_connection

logger = logging.getLogger(__name__)

# Unit conversion factors
_M3_TO_MM3  = 1e9
_M2_TO_MM2  = 1e6
_M_TO_MM    = 1e3


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_mass_properties(filepath: str) -> dict:
    """
    Extract mass properties from a .sldprt file via the SW COM API.

    Parameters
    ----------
    filepath : absolute path to a local .sldprt file

    Returns
    -------
    See module docstring for schema.
    """
    result: dict[str, Any] = {
        "mass": None,
        "volume": None,
        "surface_area": None,
        "center_of_mass": None,
        "density": None,
        "material_assigned": False,
        "material_name": None,
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

        # Rebuild before reading — ensures mass props are current
        try:
            doc.ForceRebuild3(False)
        except Exception:
            pass

        _read_mass_properties(doc, result)
        _read_material(doc, result)

    except Exception as exc:
        logger.exception("Error reading mass properties from '%s'", path)
        result["error"] = str(exc)
    finally:
        if conn is not None:
            try:
                conn.close_doc(str(path))
            except Exception as exc:
                logger.warning("Failed to close doc: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _read_mass_properties(doc, result: dict) -> None:
    """
    Read the 12-element GetMassProperties tuple and populate result.
    SW returns values in SI units (kg, m, m², m³).
    We convert volume/area/CoM to mm-based units for the grader.
    """
    try:
        props = doc.GetMassProperties
        # props is a property (not a method) on SW Student Edition
        if callable(props):
            props = props()

        if props is None or len(props) < 6:
            result["error"] = "GetMassProperties returned no data — material may not be assigned."
            return

        cx, cy, cz = props[0], props[1], props[2]
        volume     = props[3]   # m³  (SW Student Ed. index 3)
        surf_area  = props[4]   # m²  (SW Student Ed. index 4)
        mass       = props[5]   # kg  (SW Student Ed. index 5)

        result["mass"]         = float(mass)
        result["volume"]       = float(volume) * _M3_TO_MM3
        result["surface_area"] = float(surf_area) * _M2_TO_MM2
        result["center_of_mass"] = {
            "x": float(cx) * _M_TO_MM,
            "y": float(cy) * _M_TO_MM,
            "z": float(cz) * _M_TO_MM,
        }

        # Density = mass / volume (keep in kg/mm³)
        if volume and abs(volume) > 1e-30:
            result["density"] = float(mass) / (float(volume) * _M3_TO_MM3)

    except Exception as exc:
        logger.warning("GetMassProperties failed: %s", exc)
        result["error"] = f"GetMassProperties failed: {exc}"


def _read_material(doc, result: dict) -> None:
    """
    Read material assignment from MaterialIdName property.
    Format: "SOLIDWORKS Materials|MaterialName|ID"
    """
    try:
        mat_id = doc.MaterialIdName
        if callable(mat_id):
            mat_id = mat_id()

        if mat_id and str(mat_id).strip():
            mat_str = str(mat_id).strip()
            result["material_assigned"] = True

            # Parse "SOLIDWORKS Materials|Brass|27" → "Brass"
            parts = mat_str.split("|")
            if len(parts) >= 2:
                result["material_name"] = parts[1].strip()
            else:
                result["material_name"] = mat_str
        else:
            result["material_assigned"] = False

    except Exception as exc:
        logger.debug("MaterialIdName read failed: %s", exc)
        # Not a fatal error — material_assigned stays False


# ---------------------------------------------------------------------------
# Convenience extractors (used by grader adapter)
# ---------------------------------------------------------------------------

def get_mass(filepath: str) -> dict:
    """
    Convenience wrapper returning just mass in kg.
    Returns {"value": float | None, "unit": "kg", "error": str | None}
    """
    props = get_mass_properties(filepath)
    return {
        "value": props["mass"],
        "unit": "kg",
        "error": props["error"],
    }


def get_volume(filepath: str) -> dict:
    """
    Convenience wrapper returning just volume in mm³.
    Returns {"value": float | None, "unit": "mm³", "error": str | None}
    """
    props = get_mass_properties(filepath)
    return {
        "value": props["volume"],
        "unit": "mm³",
        "error": props["error"],
    }
