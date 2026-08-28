import win32com.client
import pythoncom
import logging
import os
import sys
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------
# Logging setup — writes to a log file next to this script
# ---------------------------------------------------------------
log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solidworks_mcp.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
log = logging.getLogger("solidworks-mcp")
log.info("=== SOLIDWORKS MCP Server starting ===")
log.info(f"Log file: {log_path}")

# Create the MCP server
mcp = FastMCP("solidworks-mcp")

# ---------------------------------------------------------------
# Start popup dismisser at server startup
# Handles "educational use only" dialog and other SW modal popups
# ---------------------------------------------------------------
try:
    from popup_dismisser import ensure_dismisser_running
    ensure_dismisser_running()
    log.info("Popup dismisser started.")
except Exception as _e:
    log.warning(f"Popup dismisser failed to start: {_e}")


# ---------------------------------------------------------------
# Helper: connect to a running SOLIDWORKS instance
# ---------------------------------------------------------------
def get_sw():
    """Connect to a running SOLIDWORKS instance via COM."""
    pythoncom.CoInitialize()
    log.debug("Attempting GetActiveObject('SldWorks.Application')...")
    try:
        sw = win32com.client.dynamic.Dispatch("SldWorks.Application")
        _ = sw.RevisionNumber  # verify connection
        log.debug("Connected to existing SOLIDWORKS instance.")
        return sw
    except Exception as e:
        log.warning(f"GetActiveObject failed: {e}")

    log.debug("Falling back to Dispatch('SldWorks.Application')...")
    try:
        sw = win32com.client.dynamic.Dispatch("SldWorks.Application")
        log.debug("Dispatched new SOLIDWORKS instance.")
        return sw
    except Exception as e:
        log.error(f"Dispatch also failed: {e}")
        raise RuntimeError(
            f"Could not connect to SOLIDWORKS. Is it running? Error: {e}"
        )


# ---------------------------------------------------------------
# Mass properties: tool_mass._read_mass_properties is the ONE
# implementation used everywhere (SPEC_v0.2 §14.5). The function that
# used to live here (get_mass_props) used a different API
# (CreateMassProperty / GetMassProperties2) and returned volume/area in
# m³/m² instead of tool_mass's mm³/mm² — two implementations of the same
# reading, silently disagreeing on units. Deleted; callers below use
# tool_mass and its units (mm³, mm², kg) instead.
# ---------------------------------------------------------------
from tool_mass import _read_mass_properties as _read_mass_properties_for_server


# ---------------------------------------------------------------
# TOOL 1: Open a file
# ---------------------------------------------------------------
@mcp.tool()
def open_file(file_path: str) -> str:
    """Open a SOLIDWORKS part, assembly, or drawing file."""
    log.info(f"open_file called: {file_path}")
    try:
        sw = get_sw()
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = sw.OpenDoc6(file_path, 1, 1, "", errors, warnings)
        if doc is None:
            msg = f"Failed to open file. Error code: {errors.value}"
            log.error(msg)
            return msg
        log.info(f"Successfully opened: {file_path}")
        return f"Successfully opened: {file_path}"
    except Exception as e:
        log.error(f"open_file exception: {e}")
        return f"Error opening file: {str(e)}"


# ---------------------------------------------------------------
# TOOL 2: Save the active document
# ---------------------------------------------------------------
@mcp.tool()
def save_file() -> str:
    """Save the currently active SOLIDWORKS document."""
    log.info("save_file called")
    try:
        sw = get_sw()
        doc = sw.ActiveDoc
        if doc is None:
            return "No active document to save."
        doc.Save3(1, 0, 0)
        path = doc.GetPathName
        log.info(f"Saved: {path}")
        return f"Saved: {path}"
    except Exception as e:
        log.error(f"save_file exception: {e}")
        return f"Error saving file: {str(e)}"


# ---------------------------------------------------------------
# TOOL 3: Close the active document
# ---------------------------------------------------------------
@mcp.tool()
def close_file() -> str:
    """Close the currently active SOLIDWORKS document."""
    log.info("close_file called")
    try:
        sw = get_sw()
        doc = sw.ActiveDoc
        if doc is None:
            return "No active document is open."
        name = doc.GetPathName
        sw.CloseDoc(name)
        log.info(f"Closed: {name}")
        return f"Closed: {name}"
    except Exception as e:
        log.error(f"close_file exception: {e}")
        return f"Error closing file: {str(e)}"


# ---------------------------------------------------------------
# TOOL 4: Get model properties
# ---------------------------------------------------------------
@mcp.tool()
def get_properties() -> str:
    """Read mass, volume, material, and custom properties from the active model."""
    log.info("get_properties called")
    try:
        sw = get_sw()
        try:
            sw_version = sw.RevisionNumber
            log.debug(f"  SOLIDWORKS version: {sw_version}")
        except Exception as e:
            log.warning(f"  Could not read SW version: {e}")

        doc = sw.ActiveDoc
        if doc is None:
            return "No active document. Please open a part file in SOLIDWORKS first."

        props = {
            "mass": None, "volume": None, "surface_area": None,
            "center_of_mass": None, "density": None,
            "material_assigned": False, "material_name": None, "error": None,
        }
        _read_mass_properties_for_server(doc, props)

        try:
            material = doc.MaterialIdName
            if not material:
                material = "Not assigned"
        except Exception as e:
            material = f"Error reading material: {e}"

        custom = {}
        try:
            prop_mgr = doc.Extension.CustomPropertyManager("")
            names = prop_mgr.GetNames()
            if names:
                for name in names:
                    try:
                        custom[name] = prop_mgr.Get(name)
                    except Exception as e:
                        custom[name] = f"<error: {e}>"
        except Exception as e:
            custom = {"error": str(e)}

        result = (
            f"File: {doc.GetPathName}\n"
            f"Material: {material}\n"
            f"Mass: {props['mass']} kg\n"
            f"Volume: {props['volume']} mm³\n"
            f"Surface area: {props['surface_area']} mm²\n"
            f"Custom properties: {custom if custom else 'None'}"
        )
        log.info(f"get_properties result:\n{result}")
        return result

    except Exception as e:
        log.error(f"get_properties exception: {e}", exc_info=True)
        return f"Error reading properties: {str(e)}\nCheck log for details: {log_path}"


# ---------------------------------------------------------------
# TOOL 5: Export file
# ---------------------------------------------------------------
@mcp.tool()
def export_file(output_path: str) -> str:
    """
    Export the active model to another format.
    The format is determined by the file extension in output_path.
    Supported: .stl, .step, .stp, .dxf, .pdf
    Example: C:\\exports\\mypart.stl
    """
    log.info(f"export_file called: {output_path}")
    try:
        sw = get_sw()
        doc = sw.ActiveDoc
        if doc is None:
            return "No active document to export."
        data = sw.GetExportFileData(1)
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        result = doc.Extension.SaveAs(output_path, 0, 1, data, errors, warnings)
        if result:
            log.info(f"Exported to: {output_path}")
            return f"Exported to: {output_path}"
        msg = f"Export failed. Error: {errors.value}, Warning: {warnings.value}"
        log.error(msg)
        return msg
    except Exception as e:
        log.error(f"export_file exception: {e}")
        return f"Error exporting: {str(e)}"


# ---------------------------------------------------------------
# TOOL 6: Compare two models
# ---------------------------------------------------------------
@mcp.tool()
def compare_models(file_path_a: str, file_path_b: str) -> str:
    """
    Compare mass properties and custom properties between two SOLIDWORKS part files.
    Provide full file paths to both files.
    """
    log.info(f"compare_models called: {file_path_a} vs {file_path_b}")
    try:
        sw = get_sw()
        errors = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

        def load_props(path):
            log.debug(f"Loading props for: {path}")
            # Note: this opens read-write (bare OpenDoc6 with option=1, no
            # ReadOnly flag) — compare_models is a generic ad-hoc MCP tool
            # for the instructor's own files, not the grading path, so the
            # SPEC_v0.2 §15.3 read-only requirement (which is about student
            # submissions) does not apply here.
            doc = sw.OpenDoc6(path, 1, 1, "", errors, warnings)
            if doc is None:
                return None, f"Could not open {path}"
            try:
                mp = {
                    "mass": None, "volume": None, "surface_area": None,
                    "center_of_mass": None, "density": None,
                    "material_assigned": False, "material_name": None, "error": None,
                }
                _read_mass_properties_for_server(doc, mp)
                pm = doc.Extension.CustomPropertyManager("")
                names = pm.GetNames() or []
                custom = {}
                for n in names:
                    try:
                        custom[n] = pm.Get(n)
                    except Exception as e:
                        custom[n] = f"<error: {e}>"
                props = {
                    "file": path,
                    "material": doc.MaterialIdName or "Not assigned",
                    "mass_kg": mp["mass"],
                    "volume_mm3": mp["volume"],
                    "surface_area_mm2": mp["surface_area"],
                    "custom": custom,
                }
            finally:
                sw.CloseDoc(path)
            return props, None

        props_a, err_a = load_props(file_path_a)
        if err_a:
            return err_a
        props_b, err_b = load_props(file_path_b)
        if err_b:
            return err_b

        lines = ["=== Model Comparison ===\n"]
        fields = ["material", "mass_kg", "volume_mm3", "surface_area_mm2"]
        labels = ["Material", "Mass (kg)", "Volume (mm³)", "Surface area (mm²)"]

        for field, label in zip(fields, labels):
            a_val = props_a[field]
            b_val = props_b[field]
            diff = ""
            if isinstance(a_val, float) and isinstance(b_val, float):
                delta = round(b_val - a_val, 6)
                pct = round((delta / a_val * 100), 2) if a_val != 0 else "N/A"
                diff = f"  →  Δ {delta:+} ({pct}%)"
            changed = " *** CHANGED ***" if a_val != b_val else ""
            lines.append(f"{label}:{changed}")
            lines.append(f"  A: {a_val}")
            lines.append(f"  B: {b_val}{diff}\n")

        all_keys = set(props_a["custom"]) | set(props_b["custom"])
        if all_keys:
            lines.append("Custom properties:")
            for k in sorted(all_keys):
                a_val = props_a["custom"].get(k, "(not present)")
                b_val = props_b["custom"].get(k, "(not present)")
                changed = " *** CHANGED ***" if a_val != b_val else ""
                lines.append(f"  {k}:{changed}  A={a_val}  B={b_val}")

        return "\n".join(lines)
    except Exception as e:
        log.error(f"compare_models exception: {e}", exc_info=True)
        return f"Error comparing models: {str(e)}"


# ===============================================================
# GRADING TOOLS
# ===============================================================

from tool_metadata import get_file_metadata as _get_file_metadata
from tool_mass     import get_mass_properties as _get_mass_properties
from tool_export   import export_file as _export_file_grading
from tool_compare  import compare_shapes as _compare_shapes
from tool_sketch   import check_sketch_status as _check_sketch_status
from sw_connection import solidworks_health_check as _sw_health_check


# ---------------------------------------------------------------
# GRADING TOOL 0: Health check
# ---------------------------------------------------------------
@mcp.tool()
def solidworks_running() -> dict:
    """
    Check whether SolidWorks is running and accessible via COM.
    Returns version, application type, and any connection errors.
    Use this to verify the server is working before grading.
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

    Returns the SW login name of the file creator (author), last saved date,
    all custom properties, and identity-keyword properties (username, student
    ID, email, etc.).

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

    Uses STL export + PCA-normalized voxel IoU comparison. With form_only=True
    (default), scale and orientation differences are normalized out so only
    shape matters — a correct part modeled off the wrong plane or in inches
    instead of mm will still score well.

    Score interpretation:
      1.0 = identical geometry
      0.8+ = very similar (minor differences)
      0.5-0.8 = partial match (notable errors)
      <0.5 = significantly different shape

    Parameters
    ----------
    student_filepath  : absolute path to student .sldprt
    solution_filepath : absolute path to solution .sldprt
    form_only         : normalize scale/orientation (default True)
    """
    log.info(f"grading_compare_shapes: {student_filepath} vs {solution_filepath}")
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
    dimensions or geometric relations — a common student error.

    Parameters
    ----------
    filepath : absolute path to a local .sldprt file
    """
    log.info(f"grading_check_sketch_status called: {filepath}")
    result = _check_sketch_status(filepath)
    log.info(f"grading_check_sketch_status result: {result}")
    return result


# ---------------------------------------------------------------
# GRADING TOOL 5: Batch grade one student file
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
    Run all grading checks against a single .sldprt file in one pass.

    Opens the file once, reads metadata + mass properties + sketch status
    sequentially, then closes it. Shape comparison (which requires STL
    export) runs as a separate step.

    SPEC_v0.2 §15.5: this used to spawn a thread per check, all calling
    methods on the same raw COM document pointer with no CoInitialize on
    those threads and the docstring's claim that this was "safe to
    parallelize" was wrong — SolidWorks' COM interface is a single-threaded
    apartment server; a dispatch pointer used from a foreign thread without
    marshalling raises RPC_E_WRONGTHREAD, and each thread's
    `join(timeout=30)` returning on a timeout meant the code went on to read
    a partially-populated (but truthy) result dict as if it were complete.
    This is now the sequential version — the one that was actually correct,
    previously living only in server_additions.py. All COM in this
    function runs on the calling thread; the only parallelism this module
    should ever have is downstream of STL export (pure Python, no COM).

    Parameters
    ----------
    filepath          : absolute path to student .sldprt
    solution_filepath : absolute path to solution .sldprt (required for shape)
    check_metadata    : include metadata (author, dates, custom properties)
    check_mass        : include mass, volume, material
    check_shape       : include shape comparison (requires solution_filepath)
    check_sketches    : include sketch fully-defined status check
    """
    import time
    from pathlib import Path
    from sw_connection import get_connection
    from tool_metadata import _read_summary_properties, _read_custom_properties, _filter_identity
    from tool_mass import _read_mass_properties, _read_material
    from tool_sketch import _read_sketch_statuses

    log.info(f"grading_batch called: {filepath}")
    t_start = time.monotonic()

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

        if check_metadata:
            try:
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

        if check_mass:
            try:
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

        if check_sketches:
            try:
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

    # --- Shape comparison runs after file is closed (needs its own STL export) ---
    if check_shape and solution_filepath and not result["error"]:
        try:
            result["shape_comparison"] = _compare_shapes(
                filepath, solution_filepath, form_only=True
            )
        except Exception as e:
            result["shape_comparison"] = {"error": str(e)}

    result["elapsed_seconds"] = round(time.monotonic() - t_start, 2)
    log.info(f"grading_batch completed in {result['elapsed_seconds']}s for {filepath}")
    return result


# ---------------------------------------------------------------
# Run the server
# ---------------------------------------------------------------
if __name__ == "__main__":
    log.info("Starting MCP server with stdio transport...")
    mcp.run(transport="stdio")
