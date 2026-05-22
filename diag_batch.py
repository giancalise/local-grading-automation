"""
diag_batch.py
-------------
Optimized batch grading — grades all .sldprt files in a folder.

Architecture:
  Phase 0: Export solution STL once + pre-normalize mesh
  Phase 1: Per student — open → read all props + export STL → close
  Phase 2: Shape comparison (pure Python, no SW)

Threading note: COM calls (mass, sketches) run on the MAIN thread.
Only pure-Python operations (metadata string parsing) run on threads.
"""
import pythoncom
pythoncom.CoInitialize()
import time
import os
import tempfile
import shutil
import itertools
from pathlib import Path

SOLUTION_PATH  = r'C:\Users\gce4\Box\ES-19\CADFiles\Listed\0253.SLDPRT'
STUDENTS_FOLDER = r'C:\Users\gce4\Box\ES-19\Spring 2026\Grading\Section 1\Quiz 3\Problem_1'
VOXEL_RES = 24   # resolution for shape comparison (24 = fast, 32 = more accurate)

from popup_dismisser import ensure_dismisser_running
from sw_connection import get_connection, recover_from_stall, reset_connection
from tool_export import export_file
from tool_metadata import _read_summary_properties, _read_custom_properties, _filter_identity
from tool_mass import _read_mass_properties, _read_material
from tool_sketch import _read_sketch_statuses
from tool_compare import _normalize_mesh, _is_valid_mesh, _voxel_iou
import trimesh
import numpy as np

ensure_dismisser_running()

# -------------------------------------------------------
# PHASE 0: Export solution STL once + pre-normalize
# -------------------------------------------------------
print("=== PHASE 0: Preparing solution file ===")
t0 = time.time()
tmp_dir = tempfile.mkdtemp(prefix="grading_")
solution_stl = os.path.join(tmp_dir, "solution.stl")

export_result = export_file(SOLUTION_PATH, "STL", solution_stl)
if not export_result["success"]:
    print(f"FAILED to export solution STL: {export_result['error']}")
    exit(1)

solution_mesh = trimesh.load(solution_stl, force="mesh")
solution_norm = _normalize_mesh(solution_mesh)
print(f"  Solution STL exported and normalized in {time.time()-t0:.1f}s")

# -------------------------------------------------------
# PHASE 1: Grade each student
# -------------------------------------------------------
student_files = sorted(Path(STUDENTS_FOLDER).glob("*.SLDPRT"))
print(f"\n=== PHASE 1: Grading {len(student_files)} students ===\n")

results = []
conn = get_connection()

def grade_one(student_path, student_stl_path, attempt=1):
    """Open, read all props, export STL, close. Returns result dict."""
    result = {
        "file": student_path.name,
        "author": None,
        "last_saved_date": None,
        "mass": None,
        "volume": None,
        "material_name": None,
        "underdefined_sketches": [],
        "shape_score": None,
        "error": None,
    }

    try:
        doc, _ = conn.open_part_silent(str(student_path))
        doc.ForceRebuild3(False)

        # --- Read summary properties (metadata) ---
        meta = {
            "last_saved_by": None, "author": None, "last_saved_date": None,
            "custom_properties": {}, "raw_identity_properties": {}, "error": None,
        }
        _read_summary_properties(doc, meta)
        result["author"] = meta.get("author")
        result["last_saved_date"] = meta.get("last_saved_date")

        # --- Read mass properties ---
        mass = {
            "mass": None, "volume": None, "surface_area": None,
            "center_of_mass": None, "density": None,
            "material_assigned": False, "material_name": None, "error": None,
        }
        _read_mass_properties(doc, mass)
        _read_material(doc, mass)
        result["mass"]          = mass.get("mass")
        result["volume"]        = mass.get("volume")
        result["material_name"] = mass.get("material_name")

        # --- Read sketch status ---
        sketches = _read_sketch_statuses(doc)
        result["underdefined_sketches"] = [
            s["name"] for s in sketches if s["status"] == "UNDERDEFINED"
        ]

        # --- Export STL ---
        stl_result = export_file(str(student_path), "STL", student_stl_path)
        if not stl_result["success"]:
            result["error"] = f"STL export failed: {stl_result['error']}"

        conn.close_doc(str(student_path))

    except Exception as e:
        result["error"] = str(e)
        try: conn.close_doc(str(student_path))
        except: pass

        # Attempt crash recovery once
        if attempt == 1:
            print(f"  ⚠ Error on attempt 1, attempting SW recovery...")
            if recover_from_stall(timeout_s=10.0):
                return grade_one(student_path, student_stl_path, attempt=2)
            else:
                result["error"] = "SW crash — could not recover"

    return result


for i, student_path in enumerate(student_files):
    t_student = time.time()
    name = student_path.name
    student_stl = os.path.join(tmp_dir, f"student_{i}.stl")

    print(f"[{i+1}/{len(student_files)}] {name}")
    result = grade_one(student_path, student_stl)

    # --- Shape comparison (pure Python, no SW) ---
    if result["error"] is None and os.path.exists(student_stl):
        try:
            student_mesh = trimesh.load(student_stl, force="mesh")
            if _is_valid_mesh(student_mesh):
                student_norm = _normalize_mesh(student_mesh)
                best_iou = 0.0
                for flips in itertools.product([1, -1], repeat=3):
                    try:
                        b = student_norm.copy()
                        b.vertices *= np.array(flips)
                        iou = _voxel_iou(solution_norm, b, VOXEL_RES)
                        if iou > best_iou:
                            best_iou = iou
                    except: pass
                result["shape_score"] = round(best_iou, 4)
        except Exception as e:
            result["error"] = f"shape comparison: {e}"

    elapsed = time.time() - t_student
    ud = result["underdefined_sketches"]
    print(f"  author={result['author']}  mass={round(result['mass'],4) if result['mass'] else 'N/A'}kg  "
          f"material={result['material_name']}  shape={result['shape_score']}  "
          f"underdefined={ud if ud else '✓'}  ({elapsed:.1f}s)")
    if result["error"]:
        print(f"  ⚠ ERROR: {result['error']}")

    results.append(result)

    # Memory cleanup between students
    import gc
    gc.collect()
    # Close any accidentally left-open docs
    try:
        app = conn.application
        docs = app.GetDocuments
        if callable(docs): docs = app.GetDocuments()
        if docs:
            for d in list(docs):
                try:
                    pn = d.GetPathName
                    if callable(pn): pn = d.GetPathName()
                    if pn and str(student_path) not in pn and SOLUTION_PATH not in pn:
                        app.CloseDoc(pn)
                        print(f"  Cleaned up leaked doc: {Path(pn).name}")
                except: pass
    except: pass

# -------------------------------------------------------
# SUMMARY TABLE
# -------------------------------------------------------
total_time = sum(time.time()-t0 for _ in [1])  # rough
print(f"\n=== SUMMARY — {len(results)} students ===")
print(f"{'Student':<35} {'Author':<12} {'Mass(kg)':<10} {'Shape':<8} {'Underdefined Sketches'}")
print("-" * 95)
for r in results:
    name = r['file'].replace('-Quiz3-1.SLDPRT','').replace('.SLDPRT','')
    ud_str = ', '.join(r['underdefined_sketches']) if r['underdefined_sketches'] else '✓ all defined'
    mass_str = f"{r['mass']:.4f}" if r['mass'] else 'N/A'
    print(f"  {name:<35} {str(r['author']):<12} {mass_str:<10} "
          f"{str(r['shape_score']):<8} {ud_str}")

# Cleanup
shutil.rmtree(tmp_dir, ignore_errors=True)
print(f"\nTotal wall time: {time.time()-t0:.0f}s for {len(results)} students")
print("Done.")
