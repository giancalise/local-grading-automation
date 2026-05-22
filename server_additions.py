# ---------------------------------------------------------------
# GRADING TOOLS — add these to server.py before the run block
# ---------------------------------------------------------------
# Drop this entire block into server.py just before:
#   if __name__ == "__main__":
# ---------------------------------------------------------------

from tool_metadata import get_file_metadata as _get_file_metadata
from tool_mass     import get_mass_properties as _get_mass_properties
from tool_export   import export_file as _export_file
from tool_compare  import compare_shapes as _compare_shapes
from tool_sketch   import check_sketch_status as _check_sketch_status
from sw_connection import solidworks_health_check as _sw_health_check
from popup_dismisser import ensure_dismisser_running as _ensure_dismisser

# Start popup dismisser once at server startup
_ensure_dismisser()


# ---------------------------------------------------------------
# GRADING TOOL 0: Health check
# ---------------------------------------------------------------
@mcp.tool()
def solidworks_running() -> dict:
    """
    Check whether SolidWorks is running and accessible via COM.
    Returns version, application type, and any connection errors.
    """
    log.info("solidworks_running called")
    return _sw_health_check()


# ---------------------------------------------------------------
# GRADING TOOL 1: File metadata
# ---------------------------------------------------------------
@mcp.tool()
def grading_get_file_metadata(filepath: str) -> dict:
    """
    Extract authorship and metadata from a local .sldprt file.

    Returns author (SW login name), last saved date, custom properties,
    and identity-keyword properties (username, student ID, email, etc.).

    Parameters
    ----------
    filepath : absolute path to a local .sldprt file
    """
    log.info(f"grading_get_file_metadata called: {filepath}")
    result = _get_file_metadata(filepath)
    log.info(f"grading_get_file_metadata result: {result}")
    return result


# ---------------------------------------------------------------
# GRADING TOOL 2: Mass properties
# ---------------------------------------------------------------
@mcp.tool()
def grading_get_mass_properties(filepath: str) -> dict:
    """
    Read mass, volume, surface area, center of mass, density, and
    material assignment from a local .sldprt file.

    Units: mass=kg, volume=mm³, surface_area=mm², center_of_mass=mm,
           density=kg/mm³

    Parameters
    ----------
    filepath : absolute path to a local .sldprt file
    """
    log.info(f"grading_get_mass_properties called: {filepath}")
    result = _get_mass_properties(filepath)
    log.info(f"grading_get_mass_properties result: {result}")
    return result


# ---------------------------------------------------------------
# GRADING TOOL 3: Shape comparison
# ---------------------------------------------------------------
@mcp.tool()
def grading_compare_shapes(
    student_filepath: str,
    solution_filepath: str,
    form_only: bool = True,
) -> dict:
    """
    Compare the geometry of two .sldprt files and return a similarity score.

    Uses STL export + PCA-normalized voxel IoU. With form_only=True (default),
    scale and orientation differences are normalized out so only shape matters.

    Score interpretation:
      1.0 = identical geometry
      0.8+ = very similar
      0.5-0.8 = partial match
      <0.5 = significantly different

    Parameters
    ----------
    student_filepath  : absolute path to student .sldprt
    solution_filepath : absolute path to solution .sldprt
    form_only         : if True, normalize scale and orientation (default True)
    """
    log.info(f"grading_compare_shapes called: {student_filepath} vs {solution_filepath}")
    result = _compare_shapes(student_filepath, solution_filepath, form_only)
    log.info(f"grading_compare_shapes result: {result}")
    return result


# ---------------------------------------------------------------
# GRADING TOOL 4: Sketch status
# ---------------------------------------------------------------
@mcp.tool()
def grading_check_sketch_status(filepath: str) -> dict:
    """
    Check sketch constraint status for all sketches in a .sldprt file.

    Reports which sketches are underdefined, overdefined, or fully defined.
    Underdefined sketches appear blue in SolidWorks and indicate missing
    dimensions or relations.

    Parameters
    ----------
    filepath : absolute path to a local .sldprt file
    """
    log.info(f"grading_check_sketch_status called: {filepath}")
    result = _check_sketch_status(filepath)
    log.info(f"grading_check_sketch_status result: {result}")
    return result


# ---------------------------------------------------------------
# GRADING TOOL 5: Batch grade (open once, run all tools, close)
# ---------------------------------------------------------------
@mcp.tool()
def grading_batch(
    filepath: str,
    solution_filepath: str = "",
    check_metadata: bool = True,
    check_mass: bool = True,
    check_shape: bool = True,
    check_sketches: bool = True,
) -> dict:
    """
    Run all grading tools against a single .sldprt file in one pass.
    Opens the file once, reads all properties, closes it.
    Optionally compares shape against a solution file.

    This is ~4x faster than calling each tool individually because
    SolidWorks only opens and closes the file once.

    Parameters
    ----------
    filepath          : absolute path to student .sldprt
    solution_filepath : absolute path to solution .sldprt (for shape comparison)
    check_metadata    : include metadata (author, dates)
    check_mass        : include mass/volume/material
    check_shape       : include shape comparison (requires solution_filepath)
    check_sketches    : include sketch status check
    """
    import time
    log.info(f"grading_batch called: {filepath}")
    t_start = time.monotonic()

    from sw_connection import get_connection
    from pathlib import Path

    result = {
        "filepath": filepath,
        "metadata": None,
        "mass_properties": None,
        "shape_comparison": None,
        "sketch_status": None,
        "error": None,
        "elapsed_seconds": None,
    }

    path = Path(filepath).resolve()
    if not path.exists():
        result["error"] = f"File not found: {path}"
        return result

    conn = None
    doc = None

    try:
        conn = get_connection()
        doc, _ = conn.open_part_silent(str(path))
        doc.ForceRebuild3(False)

        # --- Metadata ---
        if check_metadata:
            try:
                from tool_metadata import (
                    _read_summary_properties, _read_custom_properties,
                    _filter_identity, IDENTITY_KEYWORDS
                )
                meta = {
                    "last_saved_by": None, "author": None,
                    "last_saved_date": None, "custom_properties": {},
                    "raw_identity_properties": {}, "error": None,
                }
                _read_summary_properties(doc, meta)
                _read_custom_properties(doc, meta)
                meta["raw_identity_properties"] = _filter_identity(meta["custom_properties"])
                if meta["author"]:
                    meta["raw_identity_properties"].setdefault("Author", meta["author"])
                result["metadata"] = meta
            except Exception as e:
                result["metadata"] = {"error": str(e)}

        # --- Mass properties ---
        if check_mass:
            try:
                from tool_mass import _read_mass_properties, _read_material
                mass = {
                    "mass": None, "volume": None, "surface_area": None,
                    "center_of_mass": None, "density": None,
                    "material_assigned": False, "material_name": None, "error": None,
                }
                doc.ForceRebuild3(False)
                _read_mass_properties(doc, mass)
                _read_material(doc, mass)
                result["mass_properties"] = mass
            except Exception as e:
                result["mass_properties"] = {"error": str(e)}

        # --- Sketch status ---
        if check_sketches:
            try:
                from tool_sketch import _read_sketch_statuses
                sketches = _read_sketch_statuses(doc)
                underdefined = [s for s in sketches if s["status"] == "UNDERDEFINED"]
                result["sketch_status"] = {
                    "underdefined_count": len(underdefined),
                    "underdefined_sketch_names": [s["name"] for s in underdefined],
                    "all_sketches": sketches,
                    "method": "dispid_probe",
                    "error": None,
                }
            except Exception as e:
                result["sketch_status"] = {"error": str(e)}

    except Exception as e:
        log.exception("grading_batch open/read failed for '%s'", filepath)
        result["error"] = str(e)
    finally:
        if conn is not None and doc is not None:
            try:
                conn.close_doc(str(path))
            except Exception as e:
                log.warning("grading_batch close failed: %s", e)

    # --- Shape comparison (needs separate open/close cycle) ---
    if check_shape and solution_filepath and not result["error"]:
        try:
            result["shape_comparison"] = _compare_shapes(
                filepath, solution_filepath, form_only=True
            )
        except Exception as e:
            result["shape_comparison"] = {"error": str(e)}

    result["elapsed_seconds"] = round(time.monotonic() - t_start, 2)
    log.info(f"grading_batch completed in {result['elapsed_seconds']}s")
    return result
