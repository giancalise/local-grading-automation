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
import tempfile
import time
from pathlib import Path

import pythoncom
pythoncom.CoInitialize()

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
VOXEL_RES        = 64     # 64 = maximum quality; 48 = production; 24 = fast dev

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from popup_dismisser import ensure_dismisser_running
from sw_connection import get_connection, recover_from_stall
from tool_export import export_file
from tool_metadata import _read_summary_properties, _read_custom_properties, _filter_identity
from tool_mass import _read_mass_properties, _read_material, get_mass_properties
from tool_sketch import _read_sketch_statuses
from tool_compare import _normalize_mesh, _is_valid_mesh, compare_meshes_normalized, save_viewer_stls
import trimesh
import numpy as np


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


def compute_grade(shape_score, volume_ok, material_ok, sketch_ok) -> dict:
    """
    Volume-aware grading:
      - Volume correct + shape >= threshold  → full shape credit
      - Volume correct + shape < threshold   → proportional
      - Volume wrong                         → raw shape score (more penalizing)
    """
    shape_credit = (1.0 if shape_score >= SHAPE_THRESHOLD else shape_score) \
                   if volume_ok else shape_score
    shape_pts    = round(shape_credit * WEIGHT_SHAPE * 100, 1)
    volume_pts   = round((1.0 if volume_ok else 0.0) * WEIGHT_VOLUME * 100, 1)
    material_pts = round((1.0 if material_ok else 0.0) * WEIGHT_MATERIAL * 100, 1)
    sketch_pts   = round((1.0 if sketch_ok else 0.0) * WEIGHT_SKETCHES * 100, 1)
    return {
        "total":           round(shape_pts + volume_pts + material_pts + sketch_pts, 1),
        "shape_points":    shape_pts,
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
):
    """
    student_identity_map: optional dict mapping filename → {uid, display_name}
    When provided, grades use Firebase UID and display name instead of
    values derived from the filename or SolidWorks file metadata.
    """
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

            try:
                doc, _ = conn.open_part_silent(str(student_path))
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

                # Sketches
                sketches = _read_sketch_statuses(doc)
                record["checks"]["underdefined_sketches"] = [
                    s["name"] for s in sketches if s["status"] == "UNDERDEFINED"
                ]

                # Export STL to temp first, then copy to persistent destination
                stl_result = export_file(str(student_path), "STL", student_stl_tmp)
                conn.close_doc(str(student_path))

                if stl_result["success"]:
                    shutil.copy2(student_stl_tmp, student_stl_dest)
                else:
                    record["error"] = f"STL export failed: {stl_result['error']}"
                    record["flags"]["needs_review"] = True

            except Exception as e:
                record["error"] = str(e)
                record["flags"]["needs_review"] = True
                try: conn.close_doc(str(student_path))
                except: pass
                if recover_from_stall(timeout_s=10.0):
                    print(f"  ⚠ Recovered from SW stall")
                else:
                    print(f"  ✗ SW crash — could not recover")

            # Shape comparison (pure Python, no SW)
            if student_stl_dest.exists() and record["error"] is None:
                try:
                    # Load the raw STL we just exported for comparison
                    student_mesh = trimesh.load(str(student_stl_dest), force="mesh")
                    if _is_valid_mesh(student_mesh):
                        stu_norm = _normalize_mesh(student_mesh)
                        iou, best_flip, alignment = compare_meshes_normalized(
                            stu_norm, sol_norm, VOXEL_RES
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

            # Grading checks
            vol = record["checks"].get("volume_mm3")
            mat = record["checks"].get("material")
            record["checks"]["volume_ok"]   = bool(
                solution_volume and vol and
                abs(vol - solution_volume) / solution_volume <= VOLUME_TOLERANCE
            )
            record["checks"]["material_ok"] = bool(
                mat and solution_material and
                mat.lower() == solution_material.lower()
            )
            record["checks"]["sketches_ok"] = (
                len(record["checks"]["underdefined_sketches"]) == 0
            )

            shape_score = record["checks"]["shape_score"] or 0.0
            record["grade"] = compute_grade(
                min(shape_score, 1.0),
                record["checks"]["volume_ok"],
                record["checks"]["material_ok"],
                record["checks"]["sketches_ok"],
            )

            # Flag for review if grade < 85 or any check failed
            grade_total = record["grade"]["total"]
            if grade_total < 85 or not record["checks"]["volume_ok"] \
                    or not record["checks"]["material_ok"] \
                    or record["checks"]["underdefined_sketches"]:
                record["flags"]["needs_review"] = True

            # Track authors for plagiarism
            author = record["sw_author"]
            if author:
                if author not in author_map:
                    author_map[author] = []
                author_map[author].append(username)

            elapsed = round(time.monotonic() - t_student, 1)
            ud = record["checks"]["underdefined_sketches"]
            print(f"  author={record['sw_author']}  "
                  f"vol={'✓' if record['checks']['volume_ok'] else '✗'}  "
                  f"mat={'✓' if record['checks']['material_ok'] else '✗'}  "
                  f"shape={record['checks']['shape_score']}  "
                  f"sketches={'✓' if not ud else ud}  "
                  f"grade={grade_total}/100  ({elapsed}s)")

            all_results.append(record)
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
                "voxel_resolution": VOXEL_RES,
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
