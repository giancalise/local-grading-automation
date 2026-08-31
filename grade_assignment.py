"""
grade_assignment.py
-------------------
Batch grading script for single-problem SOLIDWORKS assignments.

Usage
-----
    python grade_assignment.py ^
        --students   "C:\\path\\to\\students\\folder" ^
        --solution   "C:\\path\\to\\solution.SLDPRT" ^
        --output     "C:\\path\\to\\output\\folder" ^
        --assignment "Quiz3"

Outputs
-------
    <output>/<assignment>_grades.json   — full structured data for web app
    <output>/<assignment>_grades.csv    — flat summary for Excel
    <output>/stl/<assignment>/          — STL files for 3D viewer
        solution.stl
        <username>.stl  (one per student)

JSON schema (results.json)
--------------------------
{
  "assignmentId":      str,
  "assignmentName":    str,
  "gradedAt":          str,   # ISO-8601
  "published":         false, # instructor controls visibility
  "solution": {
    "volume_mm3":  float,
    "material":    str,
    "stl_path":    str        # relative path within output folder
  },
  "rubric": { "shape": 0.65, "volume": 0.10, "material": 0.10, "sketches": 0.15 },
  "thresholds": { "volume_tolerance": 0.01, "shape_threshold": 0.95 },
  "students": [
    {
      "username":    str,
      "filename":    str,
      "sw_author":   str | null,
      "grade": {
        "total":           float,
        "shape_points":    float,
        "volume_points":   float,
        "material_points": float,
        "sketch_points":   float,
        "override":        null,   # set by instructor via web app
        "override_note":   null,
        "override_by":     null
      },
      "checks": {
        "shape_score":           float,
        "volume_ok":             bool,
        "material_ok":           bool,
        "sketches_ok":           bool,
        "underdefined_sketches": [str]
      },
      "geometry": {
        "student_stl_path":    str,          # relative path in output folder
        "solution_stl_path":   str,          # relative path in output folder
        "alignment_transform": [float x 16], # 4x4 row-major matrix for 3D viewer
        "best_flip":           [int, int, int]
      },
      "flags": {
        "plagiarism":      bool,
        "plagiarism_with": str | null,
        "needs_review":    bool
      },
      "error": str | null
    }
  ]
}

Rubric (edit below)
-------------------
"""

import argparse
import csv
import itertools
import json
import os
import re
import shutil
import stat
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Rubric weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_SHAPE     = 0.65
WEIGHT_VOLUME    = 0.10
WEIGHT_MATERIAL  = 0.10
WEIGHT_SKETCHES  = 0.15

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
VOLUME_TOLERANCE = 0.01   # ±1% of solution volume
SHAPE_THRESHOLD  = 0.95   # score >= this with correct volume = full shape credit
VOXEL_RES        = 64     # hard floor per SPEC_v0.2 §7.4 — not a speed lever

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import pythoncom
from popup_dismisser import ensure_dismisser_running
from sw_connection import get_connection, recover_from_stall
from check_result import CheckStatus
from tool_export import export_file
from tool_metadata import _read_summary_properties, _read_custom_properties, _filter_identity
from tool_mass import _read_mass_properties, _read_material, get_mass_properties
from tool_sketch import _read_sketch_statuses
from tool_compare import _normalize_mesh, _is_valid_mesh, compare_meshes_normalized, save_viewer_stls
import trimesh
import numpy as np

# SPEC_v0.2 §11.3 (sw_timeout.with_timeout) is deliberately NOT wired in
# here. Verified live during Milestone 1: its thread-based implementation
# is unsafe for SolidWorks' single-threaded-apartment COM calls — running
# open_part_silent/export_file on with_timeout's worker thread corrupted
# the connection (SolidWorks itself kept running; the Python-side
# connection was reported lost and had to fully reconnect), which is the
# same class of hazard §15.5 describes for server.py's old threaded
# grading_batch. See MILESTONE_1_REPORT.md. Needs a redesign (COM
# marshaling or a process-kill watchdog) before it's safe to use here.


# ---------------------------------------------------------------------------
# STL normalization helpers (for 3D viewer)
# ---------------------------------------------------------------------------

def save_viewer_solution_stl(
    raw_stl_path: str,
    output_path: Path,
) -> None:
    """
    Prepare solution STL for the 3D viewer.
    Just center at origin — browser handles PCA normalization and scale.
    """
    import copy
    mesh = trimesh.load(raw_stl_path, force="mesh")
    m = copy.deepcopy(mesh)
    m.vertices -= m.vertices.mean(axis=0)
    m.export(str(output_path))


def save_viewer_student_stl(
    raw_stl_path: str,
    sol_raw_stl_path: str,
    output_path: Path,
) -> None:
    """
    Prepare student STL for the 3D viewer.
    Just center at origin — the browser handles PCA alignment and flip search.
    """
    import copy
    mesh = trimesh.load(raw_stl_path, force="mesh")
    m = copy.deepcopy(mesh)
    m.vertices -= m.vertices.mean(axis=0)
    m.export(str(output_path))


# Keep these as aliases for backward compatibility
def save_normalized_stl(mesh, output_path):
    """Alias — not used for viewer STLs anymore."""
    mesh.export(str(output_path))

def save_normalized_aligned_student_stl(stu_norm, best_flip, alignment_transform, output_path):
    """Alias — not used for viewer STLs anymore."""
    stu_norm.export(str(output_path))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_username(filename: str) -> str:
    stem = Path(filename).stem
    return stem.split('-')[0].strip()


def compute_grade(shape_status, shape_score, volume_status, material_status, sketch_status) -> dict:
    """
    Three-state grading (SPEC_v0.2 §7.2, §15.1, §15.4).

    A NOT_EVALUATED check withholds its points — same numeric effect as a
    fail (zero points), but recorded as a distinct status the caller uses
    to force needs_review. It is never silently rounded into "passed" or
    "failed".

    Volume-aware shape coupling (unchanged from the existing rubric design;
    out of scope for this milestone — see SPEC_v0.2 §7.2 Q6): volume
    correct + shape >= threshold gets full shape credit. The boost
    requires volume_status to be PASS specifically — an unevaluated or
    failed volume check must not unlock full shape credit.
    """
    if shape_status == CheckStatus.NOT_EVALUATED or shape_score is None:
        shape_pts = 0.0
    else:
        shape_credit = (
            1.0 if (shape_score >= SHAPE_THRESHOLD and volume_status == CheckStatus.PASS)
            else shape_score
        )
        shape_pts = round(shape_credit * WEIGHT_SHAPE * 100, 1)

    volume_pts   = round(WEIGHT_VOLUME   * 100, 1) if volume_status   == CheckStatus.PASS else 0.0
    material_pts = round(WEIGHT_MATERIAL * 100, 1) if material_status == CheckStatus.PASS else 0.0
    sketch_pts   = round(WEIGHT_SKETCHES * 100, 1) if sketch_status   == CheckStatus.PASS else 0.0

    return {
        "total":           round(shape_pts + volume_pts + material_pts + sketch_pts, 1),
        "shape_points":    round(shape_pts, 1),
        "volume_points":   volume_pts,
        "material_points": material_pts,
        "sketch_points":   sketch_pts,
        "override":        None,
        "override_note":   None,
        "override_by":     None,
    }


# ---------------------------------------------------------------------------
# Main grading function
# ---------------------------------------------------------------------------

def grade_assignment(
    students_folder: str,
    solution_path: str,
    output_folder: str,
    assignment_name: str,
    solution_material: str | None = None,
    solution_volume: float | None = None,
    student_identity_map: dict | None = None,
    progress_callback=None,
    voxel_resolution: int | None = None,
):
    """
    voxel_resolution: optional override for the module-level VOXEL_RES.
    Additive and defaulted to None, so every existing caller is unaffected.
    SPEC_v0.2 §7.4 / D3 puts a HARD FLOOR of 64 on this — it is a criteria
    field, not a speed lever, and §7.5 marks the form check "valid only at
    resolution >= 64" (measured noise floor ~0.8% at 64 vs ~3% at 24).
    Anything below 64 is therefore raised to 64 rather than honoured; the
    value actually used is what gets stamped into
    thresholds.voxel_resolution in the result, so the output always records
    what was really run, not what was asked for.

    progress_callback: optional callable(dict) invoked after each student
    with {"current": int, "total": int, "filename": str, "elapsed_s":
    float, "file_seconds": float}. Additive, minimal hook for the desktop
    UI's live progress display (SPEC_v0.2 §10 step 6) — does not replace
    the existing print() output.

    student_identity_map: optional dict mapping filename → {uid, display_name}
    When provided, grades use Firebase UID and display name instead of
    values derived from the filename or SolidWorks file metadata.
    """
    # SPEC_v0.2 §7.4 hard floor. Clamp rather than reject: a caller asking
    # for less still gets a valid grade, and the value below is the one
    # stamped into the result, so the output never claims a resolution it
    # did not use.
    effective_voxel_res = VOXEL_RES if voxel_resolution is None else max(64, int(voxel_resolution))

    # Explicit COM init on the thread that will actually make COM calls
    # (SPEC_v0.2 §14.4) — this call must happen here, not at import time,
    # since import can happen on a different thread than the one that runs
    # this function (e.g. a web server's request-handling thread pool).
    # All COM in this function stays on the calling thread (§15.5).
    pythoncom.CoInitialize()

    identity = student_identity_map or {}
    ensure_dismisser_running()
    conn = get_connection()

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)

    # STL output folder — persisted for 3D viewer
    stl_folder = output_path / "stl" / assignment_name
    stl_folder.mkdir(parents=True, exist_ok=True)

    tmp_dir = tempfile.mkdtemp(prefix="grading_")
    t_start = time.monotonic()

    try:
        # -------------------------------------------------------
        # PHASE 0: Prepare solution
        # -------------------------------------------------------
        print(f"\n{'='*60}")
        print(f"PHASE 0: Preparing solution file")
        print(f"{'='*60}")

        # Export solution STL to temp first (raw export needed for normalization)
        solution_stl_tmp  = os.path.join(tmp_dir, "solution_raw.stl")
        solution_stl_dest = stl_folder / "solution.stl"   # final normalized path
        # NOTE on with_timeout (SPEC_v0.2 §11.3): NOT wrapped here. Verified
        # live during Milestone 1 that sw_timeout.py's existing thread-based
        # implementation is unsafe for this call — SolidWorks' COM object is
        # a single-threaded-apartment server, and running the wrapped call
        # on with_timeout's worker thread corrupts the connection exactly
        # the way §15.5 warns about for server.py's old threaded
        # grading_batch, just via a different code path (confirmed: the
        # live SolidWorks process kept running throughout, but the Python
        # side reported "SW connection lost" and had to fully reconnect).
        # See MILESTONE_1_REPORT.md for details. §11.3 is deliberately left
        # unaddressed pending a redesign (COM marshaling or a
        # process-kill-based watchdog) rather than shipping something that
        # passed a quick look but broke live COM.
        export_result = export_file(solution_path, "STL", solution_stl_tmp)
        if not export_result["success"]:
            raise RuntimeError(f"Failed to export solution STL: {export_result['error']}")

        # Get solution properties
        if solution_volume is None or solution_material is None:
            sol_props = get_mass_properties(solution_path)
            if solution_volume is None:
                solution_volume = sol_props.get("volume")
            if solution_material is None:
                solution_material = sol_props.get("material_name")

        # Pre-normalize solution mesh (reused for every student comparison)
        sol_mesh = trimesh.load(solution_stl_tmp, force="mesh")
        sol_norm = _normalize_mesh(sol_mesh)

        # Save viewer-ready solution STL — PCA-normalized, ready for direct overlay
        # (saved once here; student STLs saved after shape comparison below)
        save_viewer_stls(
            sol_norm, sol_norm, [1,1,1],
            str(solution_stl_dest), str(solution_stl_dest)
        )

        solution_stl_rel = f"stl/{assignment_name}/solution.stl"

        print(f"  Solution: {solution_path}")
        print(f"  Volume:   {solution_volume:.2f} mm³" if solution_volume else "  Volume: unknown")
        print(f"  Material: {solution_material}")
        print(f"  STL:      {solution_stl_dest}")

        # -------------------------------------------------------
        # PHASE 1: Grade each student
        # -------------------------------------------------------
        student_files = sorted(Path(students_folder).glob("*.SLDPRT")) + \
                        sorted(Path(students_folder).glob("*.sldprt"))
        seen = set()
        student_files = [f for f in student_files
                         if not (f.name.lower() in seen or seen.add(f.name.lower()))]

        print(f"\n{'='*60}")
        print(f"PHASE 1: Grading {len(student_files)} students")
        print(f"{'='*60}\n")

        all_results  = []
        author_map: dict[str, list[str]] = {}

        for i, student_path in enumerate(student_files):
            t_student = time.monotonic()
            filename  = student_path.name
            username  = extract_username(filename)

            # STL destination (persistent, for 3D viewer)
            student_stl_dest = stl_folder / f"{username}.stl"
            student_stl_tmp  = os.path.join(tmp_dir, f"student_{i}.stl")
            student_stl_rel  = f"stl/{assignment_name}/{username}.stl"

            print(f"[{i+1}/{len(student_files)}] {filename}")

            # Look up Firebase identity for this student
            id_info      = identity.get(filename, {})
            uid          = id_info.get("uid") or username
            display_name = id_info.get("display_name") or username

            record = {
                "uid":         uid,           # Firebase Auth UID
                "username":    display_name,  # Firebase Auth display name (shown in UI)
                "filename":    filename,
                "sw_author":   None,          # SolidWorks login — kept for plagiarism only
                "last_saved_date": None,
                "grade":       None,
                "checks":      {
                    "shape_score":           None,
                    "volume_ok":             None,
                    "material_ok":           None,
                    "sketches_ok":           None,
                    "underdefined_sketches": [],
                },
                "geometry": {
                    "student_stl_path":    student_stl_rel,
                    "solution_stl_path":   solution_stl_rel,
                    "alignment_transform": [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],
                    "best_flip":           [1, 1, 1],
                },
                "flags": {
                    "plagiarism":      False,
                    "plagiarism_with": None,
                    "needs_review":    False,
                },
                "error": None,
            }

            # --- SPEC_v0.2 §15.3: grade a scratch copy, never the original ---
            # Even with the read-only open strategy tried first, a student's
            # actual submission is never handed to SolidWorks directly.
            scratch_path = Path(tmp_dir) / f"scratch_{i}_{filename}"
            mass_error   = None
            sketch_error = None
            sketch_statuses: list[dict] = []
            try:
                shutil.copy2(str(student_path), str(scratch_path))
                os.chmod(str(scratch_path), stat.S_IREAD)

                # NOTE on with_timeout (SPEC_v0.2 §11.3): NOT used here —
                # see the note in PHASE 0 above. sw_timeout.py's thread-based
                # implementation is unsafe for STA COM calls as-is.
                doc, _ = conn.open_part_silent(str(scratch_path))
                doc.ForceRebuild3(False)

                # Metadata
                meta = {"last_saved_by": None, "author": None, "last_saved_date": None,
                        "custom_properties": {}, "raw_identity_properties": {}, "error": None}
                _read_summary_properties(doc, meta)
                record["sw_author"]       = meta.get("author")
                record["last_saved_date"] = meta.get("last_saved_date")

                # Mass
                mass = {"mass": None, "volume": None, "surface_area": None,
                        "center_of_mass": None, "density": None,
                        "material_assigned": False, "material_name": None, "error": None}
                _read_mass_properties(doc, mass)
                _read_material(doc, mass)
                record["checks"]["volume_mm3"] = mass.get("volume")
                record["checks"]["material"]   = mass.get("material_name")
                record["checks"]["mass_kg"]    = mass.get("mass")
                mass_error = mass.get("error")

                # Sketches
                sketch_statuses = _read_sketch_statuses(doc)
                record["checks"]["underdefined_sketches"] = [
                    s["name"] for s in sketch_statuses if s["status"] == "UNDERDEFINED"
                ]
                if not sketch_statuses:
                    sketch_error = "no sketch features found or feature read failed"

                # Export STL to temp first, then copy to persistent destination
                stl_result = export_file(str(scratch_path), "STL", student_stl_tmp)
                conn.close_doc(str(scratch_path))

                if stl_result["success"]:
                    shutil.copy2(student_stl_tmp, student_stl_dest)
                else:
                    record["error"] = f"STL export failed: {stl_result['error']}"
                    record["flags"]["needs_review"] = True

            except Exception as e:
                record["error"] = str(e)
                record["flags"]["needs_review"] = True
                try: conn.close_doc(str(scratch_path))
                except: pass
                if recover_from_stall(timeout_s=10.0):
                    print(f"  ⚠ Recovered from SW stall")
                else:
                    print(f"  ✗ SW crash — could not recover")
            finally:
                try:
                    if scratch_path.exists():
                        os.chmod(str(scratch_path), stat.S_IWRITE)
                        scratch_path.unlink()
                except Exception as e_cleanup:
                    print(f"  ⚠ Could not remove scratch copy: {e_cleanup}")

            # Shape comparison (pure Python, no SW)
            if student_stl_dest.exists() and record["error"] is None:
                try:
                    # Load the raw STL we just exported for comparison
                    student_mesh = trimesh.load(str(student_stl_dest), force="mesh")
                    if _is_valid_mesh(student_mesh):
                        stu_norm = _normalize_mesh(student_mesh)
                        iou, best_flip, alignment = compare_meshes_normalized(
                            stu_norm, sol_norm, effective_voxel_res
                        )
                        record["checks"]["shape_score"]           = iou
                        record["geometry"]["alignment_transform"] = alignment
                        record["geometry"]["best_flip"]           = best_flip

                        # Save PCA-normalized + best-flip-aligned student STL
                        # Both solution and student are now in the same PCA space
                        # so the viewer can overlay them with zero math
                        try:
                            _, tmp_stu = str(solution_stl_dest), str(student_stl_dest)
                            save_viewer_stls(
                                sol_norm, stu_norm, best_flip,
                                str(solution_stl_dest),  # re-save solution (same)
                                str(student_stl_dest),   # save aligned student
                            )
                        except Exception as e_stl:
                            print(f"  ⚠ Could not save viewer STLs: {e_stl}")

                except Exception as e:
                    record["flags"]["needs_review"] = True
                    print(f"  ⚠ Shape comparison failed: {e}")

            # -------------------------------------------------------
            # Grading checks — three states, never a silent pass/fail
            # for a check that didn't actually run (SPEC_v0.2 §7.2,
            # §15.1, §15.4).
            # -------------------------------------------------------
            vol = record["checks"].get("volume_mm3")
            mat = record["checks"].get("material")
            had_open_error = record["error"] is not None

            # Volume: a failed read (or nothing to compare against) is
            # not_evaluated, never a silent False the student didn't cause.
            if had_open_error or vol is None or mass_error or solution_volume is None:
                volume_status = CheckStatus.NOT_EVALUATED
            elif abs(vol - solution_volume) / solution_volume <= VOLUME_TOLERANCE:
                volume_status = CheckStatus.PASS
            else:
                volume_status = CheckStatus.FAIL
            record["checks"]["volume_status"] = volume_status.value
            record["checks"]["volume_ok"] = (
                None if volume_status == CheckStatus.NOT_EVALUATED
                else volume_status == CheckStatus.PASS
            )

            # Material
            if had_open_error or not mat or not solution_material:
                material_status = CheckStatus.NOT_EVALUATED
            elif mat.lower() == solution_material.lower():
                material_status = CheckStatus.PASS
            else:
                material_status = CheckStatus.FAIL
            record["checks"]["material_status"] = material_status.value
            record["checks"]["material_ok"] = (
                None if material_status == CheckStatus.NOT_EVALUATED
                else material_status == CheckStatus.PASS
            )

            # Sketches: an UNKNOWN status is never silently treated as
            # passing — it forces not_evaluated, same as a read failure.
            has_unknown_sketch = any(s["status"] == "UNKNOWN" for s in sketch_statuses)
            if had_open_error or sketch_error or has_unknown_sketch:
                sketches_status = CheckStatus.NOT_EVALUATED
            elif record["checks"]["underdefined_sketches"]:
                sketches_status = CheckStatus.FAIL
            else:
                sketches_status = CheckStatus.PASS
            record["checks"]["sketches_status"] = sketches_status.value
            record["checks"]["sketches_ok"] = (
                None if sketches_status == CheckStatus.NOT_EVALUATED
                else sketches_status == CheckStatus.PASS
            )

            # Shape: a None score means IoU could not be computed at all
            # (e.g. missing scipy) — never coerced to 0.0, which would look
            # like a genuinely bad match instead of a check that didn't run.
            raw_shape_score = record["checks"]["shape_score"]
            if had_open_error or raw_shape_score is None:
                shape_status = CheckStatus.NOT_EVALUATED
                shape_score  = None
            else:
                shape_score  = min(raw_shape_score, 1.0)
                shape_status = (CheckStatus.PASS if shape_score >= SHAPE_THRESHOLD
                                 else CheckStatus.FAIL)
            record["checks"]["shape_status"] = shape_status.value

            record["grade"] = compute_grade(
                shape_status, shape_score,
                volume_status, material_status, sketches_status,
            )

            # Flag for review if grade < 85, any check failed outright, or
            # any check could not be evaluated at all — not_evaluated always
            # forces review regardless of the numeric total.
            grade_total = record["grade"]["total"]
            any_not_evaluated = CheckStatus.NOT_EVALUATED in (
                shape_status, volume_status, material_status, sketches_status
            )
            if grade_total < 85 or volume_status == CheckStatus.FAIL \
                    or material_status == CheckStatus.FAIL \
                    or sketches_status == CheckStatus.FAIL \
                    or any_not_evaluated:
                record["flags"]["needs_review"] = True

            # Track authors for plagiarism
            author = record["sw_author"]
            if author:
                if author not in author_map:
                    author_map[author] = []
                author_map[author].append(username)

            def _mark(status: CheckStatus) -> str:
                return {"pass": "OK", "fail": "FAIL", "not_evaluated": "N/E"}[status.value]

            elapsed = round(time.monotonic() - t_student, 1)
            print(f"  author={record['sw_author']}  "
                  f"vol={_mark(volume_status)}  "
                  f"mat={_mark(material_status)}  "
                  f"shape={record['checks']['shape_score']} [{_mark(shape_status)}]  "
                  f"sketches={_mark(sketches_status)}  "
                  f"grade={grade_total}/100  ({elapsed}s)")

            all_results.append(record)

            if progress_callback is not None:
                try:
                    progress_callback({
                        "current": i + 1,
                        "total": len(student_files),
                        "filename": filename,
                        "elapsed_s": round(time.monotonic() - t_start, 1),
                        "file_seconds": elapsed,
                    })
                except Exception as e_cb:
                    print(f"  ⚠ progress_callback raised: {e_cb}")

            import gc; gc.collect()

        # -------------------------------------------------------
        # PHASE 2: Plagiarism flags
        # -------------------------------------------------------
        print(f"\n{'='*60}\nPHASE 2: Plagiarism analysis\n{'='*60}")
        for record in all_results:
            author = record["sw_author"]
            if author and author in author_map and len(author_map[author]) > 1:
                others = [u for u in author_map[author] if u != record["username"]]
                record["flags"]["plagiarism"]      = True
                record["flags"]["plagiarism_with"] = ", ".join(others)
                record["flags"]["needs_review"]    = True
                print(f"  ⚠ PLAGIARISM: {record['username']} ↔ {', '.join(others)} (author={author})")
        if not any(r["flags"]["plagiarism"] for r in all_results):
            print("  No plagiarism flags.")

        # -------------------------------------------------------
        # PHASE 3: Write outputs
        # -------------------------------------------------------
        print(f"\n{'='*60}\nPHASE 3: Writing output files\n{'='*60}")

        # --- JSON ---
        json_path = output_path / f"{assignment_name}_grades.json"
        output_data = {
            "assignmentId":   assignment_name,
            "assignmentName": assignment_name,
            "gradedAt":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "published":      False,
            "solution": {
                "file":        solution_path,
                "volume_mm3":  solution_volume,
                "material":    solution_material,
                "stl_path":    solution_stl_rel,
            },
            "rubric": {
                "shape":    WEIGHT_SHAPE,
                "volume":   WEIGHT_VOLUME,
                "material": WEIGHT_MATERIAL,
                "sketches": WEIGHT_SKETCHES,
            },
            "thresholds": {
                "volume_tolerance": VOLUME_TOLERANCE,
                "shape_threshold":  SHAPE_THRESHOLD,
                "voxel_resolution": effective_voxel_res,
            },
            "students": all_results,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"  JSON: {json_path}")

        # --- CSV ---
        csv_path = output_path / f"{assignment_name}_grades.csv"
        csv_fields = [
            "username", "filename", "sw_author",
            "grade_total", "shape_score", "volume_ok", "material_ok", "sketches_ok",
            "underdefined_sketches", "mass_kg", "volume_mm3", "material",
            "plagiarism", "plagiarism_with", "needs_review", "error",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_fields)
            writer.writeheader()
            for r in all_results:
                writer.writerow({
                    "username":              r["username"],
                    "filename":              r["filename"],
                    "sw_author":             r["sw_author"],
                    "grade_total":           r["grade"]["total"] if r["grade"] else "",
                    "shape_score":           r["checks"]["shape_score"],
                    "volume_ok":             r["checks"]["volume_ok"],
                    "material_ok":           r["checks"]["material_ok"],
                    "sketches_ok":           r["checks"]["sketches_ok"],
                    "underdefined_sketches": "; ".join(r["checks"]["underdefined_sketches"]),
                    "mass_kg":               r["checks"].get("mass_kg", ""),
                    "volume_mm3":            r["checks"].get("volume_mm3", ""),
                    "material":              r["checks"].get("material", ""),
                    "plagiarism":            r["flags"]["plagiarism"],
                    "plagiarism_with":       r["flags"]["plagiarism_with"] or "",
                    "needs_review":          r["flags"]["needs_review"],
                    "error":                 r["error"] or "",
                })
        print(f"  CSV:  {csv_path}")
        print(f"  STLs: {stl_folder}  ({len(list(stl_folder.glob('*.stl')))} files)")

        # Summary
        total_time = round(time.monotonic() - t_start)
        grades     = [r["grade"]["total"] for r in all_results if r["grade"]]
        avg_grade  = round(sum(grades) / len(grades), 1) if grades else 0
        flagged    = sum(1 for r in all_results if r["flags"]["needs_review"])
        plag       = sum(1 for r in all_results if r["flags"]["plagiarism"])

        print(f"\n{'='*60}")
        print(f"COMPLETE — {len(all_results)} students in {total_time}s")
        print(f"{'='*60}")
        print(f"  Average grade:       {avg_grade}/100")
        print(f"  Needs review:        {flagged} students")
        print(f"  Plagiarism flags:    {plag} students")
        print(f"  Output:              {output_path}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grade a SOLIDWORKS assignment")
    parser.add_argument("--students",   required=True,
                        help="Folder containing student .sldprt files")
    parser.add_argument("--solution",   required=True,
                        help="Path to solution .sldprt file")
    parser.add_argument("--output",     required=True,
                        help="Output folder for grades and STL files")
    parser.add_argument("--assignment", default="assignment",
                        help="Assignment name (used in output filenames, no spaces)")
    args = parser.parse_args()

    grade_assignment(
        students_folder = args.students,
        solution_path   = args.solution,
        output_folder   = args.output,
        assignment_name = args.assignment,
    )
