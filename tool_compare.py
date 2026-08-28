"""
tool_compare.py
---------------
MCP Tool 3 — compare_shapes

Compares the geometry of two .sldprt files using:
  1. Export both to STL via SW COM API
  2. Load meshes with trimesh
  3. Normalize: center + PCA align + unit bounding box scale
  4. Voxelize both at 64³ resolution
  5. Compute IoU (intersection / union) as shape similarity score

Normalization pipeline (form-only mode, default)
-------------------------------------------------
  - Translate centroid to origin
  - Align principal axes via PCA of vertex positions
    (makes orientation irrelevant)
  - Try all 8 axis-flip combinations, keep best IoU
    (handles PCA sign ambiguity on symmetric parts)
  - Scale longest bounding-box dimension to 1.0
    (makes scale irrelevant)

Score interpretation
--------------------
  1.0 = identical geometry
  0.8+ = very similar (minor differences)
  0.5-0.8 = similar shape, notable differences
  <0.5 = significantly different

Output schema
-------------
{
    "score":         float | None, # 0.0-1.0, or None if the check could not
                                    # be evaluated (never a swallowed-exception
                                    # zero — see SPEC_v0.2 §15.1)
    "method":        str,
    "details":       str,
    "volume_ratio":  float | None, # student_vol / solution_vol (mm³)
    "iou_score":     float | None,
    "error":         str | None
}
"""

from __future__ import annotations

import itertools
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from tool_export import export_file

logger = logging.getLogger(__name__)

# Voxelization resolution — higher = more accurate but slower
# 64 is a good balance for grading; 32 is faster, 128 is more precise
VOXEL_RESOLUTION = 64


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compare_shapes(
    student_filepath: str,
    solution_filepath: str,
    form_only: bool = True,
) -> dict:
    """
    Compare geometry of two .sldprt files.

    Parameters
    ----------
    student_filepath  : absolute path to student .sldprt
    solution_filepath : absolute path to solution .sldprt
    form_only         : if True (default), normalize scale and orientation
                        so only shape is compared.
                        if False, orientation and scale affect the score.

    Returns
    -------
    See module docstring for schema.
    """
    result: dict[str, Any] = {
        "score": None,
        "method": "normalized_pca_iou" if form_only else "raw_iou",
        "details": "",
        "volume_ratio": None,
        "iou_score": None,
        "error": None,
    }

    student  = Path(student_filepath).resolve()
    solution = Path(solution_filepath).resolve()

    for p, label in [(student, "student"), (solution, "solution")]:
        if not p.exists():
            result["error"] = f"{label} file not found: {p}"
            return result

    with tempfile.TemporaryDirectory() as tmp:
        # --- Stage A: Export both to STL ---
        student_stl  = os.path.join(tmp, "student.stl")
        solution_stl = os.path.join(tmp, "solution.stl")

        for src, dst, label in [
            (str(student),  student_stl,  "student"),
            (str(solution), solution_stl, "solution"),
        ]:
            export_result = export_file(src, "STL", dst)
            if not export_result["success"]:
                result["error"] = f"STL export failed for {label}: {export_result['error']}"
                return result

        # --- Stage B: Load meshes ---
        try:
            import trimesh
        except ImportError:
            result["error"] = "trimesh not installed. Run: pip install trimesh numpy scipy"
            return result

        try:
            student_mesh  = trimesh.load(student_stl,  force="mesh")
            solution_mesh = trimesh.load(solution_stl, force="mesh")
        except Exception as exc:
            result["error"] = f"Failed to load STL meshes: {exc}"
            return result

        if not _is_valid_mesh(student_mesh) or not _is_valid_mesh(solution_mesh):
            result["error"] = "One or both STL files produced invalid meshes."
            return result

        # --- Volume ratio (always computed, uses raw volumes) ---
        try:
            sv = abs(student_mesh.volume)
            rv = abs(solution_mesh.volume)
            if rv > 0:
                result["volume_ratio"] = round(sv / rv, 4)
        except Exception:
            pass

        # --- Stage C: Normalize and compare ---
        # No fallback on failure (SPEC_v0.2 §15.1): a check that could not
        # run must never produce a number in the score field under a
        # different method — that field means something else entirely and
        # callers that don't check `method` would silently misread it.
        try:
            if form_only:
                iou = _normalized_pca_iou(student_mesh, solution_mesh)
            else:
                iou = _raw_iou(student_mesh, solution_mesh)
        except Exception as exc:
            logger.exception("IoU computation failed")
            iou = None
            result["error"] = f"Shape comparison failed: {exc}"

        if iou is None:
            result["iou_score"] = None
            result["score"] = None
            if not result["error"]:
                result["error"] = "IoU computation could not be evaluated (voxelization failed)."
            result["details"] = "not evaluated — " + result["error"]
        else:
            result["iou_score"] = round(iou, 4)
            result["score"]     = round(iou, 4)
            result["details"]   = _describe_result(iou, result["volume_ratio"], form_only)

    return result


# ---------------------------------------------------------------------------
# Normalization + IoU
# ---------------------------------------------------------------------------

def _normalized_pca_iou(mesh_a, mesh_b) -> float | None:
    """
    Normalize both meshes (center, PCA align, unit scale) then
    compute voxel IoU. Tries all 8 PCA axis-flip combinations
    and returns the best score.

    Returns None (never 0.0) if every flip attempt failed to voxelize —
    a total failure to compute must not look like a computed score of
    zero overlap (SPEC_v0.2 §15.1).
    """
    a_norm = _normalize_mesh(mesh_a)
    b_norm = _normalize_mesh(mesh_b)

    best_iou: float | None = None

    # Try all 8 sign combinations for PCA axes to handle symmetry ambiguity
    for flips in itertools.product([1, -1], repeat=3):
        try:
            b_flipped = b_norm.copy()
            b_flipped.vertices *= np.array(flips)
            iou = _voxel_iou(a_norm, b_flipped, VOXEL_RESOLUTION)
            if iou is not None and (best_iou is None or iou > best_iou):
                best_iou = iou
        except Exception:
            pass

    return best_iou


def compare_meshes_normalized(
    stu_norm,
    sol_norm,
    voxel_resolution: int = VOXEL_RESOLUTION,
) -> tuple:
    """
    Compare two already-PCA-normalized meshes.
    Tries all 8 axis-flip combinations of student vs solution.

    Returns
    -------
    (iou, best_flip, alignment_transform)
      iou               : float 0-1, or None if voxelization failed on
                          every flip attempt (never a bare 0.0 — that
                          would be indistinguishable from a real
                          zero-overlap comparison; SPEC_v0.2 §15.1)
      best_flip         : [int, int, int]  e.g. [1, -1, 1]
      alignment_transform: list of 16 floats (4x4 row-major identity —
                           meshes are already in normalized space, viewer
                           just needs to reproduce the same PCA space)
    """
    best_iou: float | None = None
    best_flips = [1, 1, 1]

    for flips in itertools.product([1, -1], repeat=3):
        try:
            b_flipped = stu_norm.copy()
            b_flipped.vertices *= np.array(flips)
            iou = _voxel_iou(sol_norm, b_flipped, voxel_resolution)
            if iou is not None and (best_iou is None or iou > best_iou):
                best_iou   = iou
                best_flips = list(flips)
        except Exception:
            pass

    # Identity alignment — meshes are pre-normalized; viewer applies same PCA
    identity = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
    return best_iou, best_flips, identity


def save_viewer_stls(
    sol_norm,
    stu_norm,
    best_flip: list,
    sol_output_path: str,
    stu_output_path: str,
) -> None:
    """
    Save PCA-normalized solution and best-flip-aligned student meshes as STL.
    These are ready for direct overlay in the 3D viewer — no further transforms needed.

    Parameters
    ----------
    sol_norm        : PCA-normalized solution trimesh
    stu_norm        : PCA-normalized student trimesh  
    best_flip       : [x, y, z] sign multipliers from compare_meshes_normalized
    sol_output_path : where to write solution STL
    stu_output_path : where to write student STL
    """
    import copy
    from pathlib import Path

    # Solution — just save as-is (already normalized)
    sol_out = copy.deepcopy(sol_norm)
    Path(sol_output_path).parent.mkdir(parents=True, exist_ok=True)
    sol_out.export(sol_output_path)

    # Student — apply best_flip then save
    stu_out = copy.deepcopy(stu_norm)
    stu_out.vertices *= np.array(best_flip, dtype=float)
    Path(stu_output_path).parent.mkdir(parents=True, exist_ok=True)
    stu_out.export(stu_output_path)


def _raw_iou(mesh_a, mesh_b) -> float:
    """IoU without normalization — orientation and scale affect score."""
    return _voxel_iou(mesh_a, mesh_b, VOXEL_RESOLUTION)


def _normalize_mesh(mesh):
    """
    Return a copy of mesh with:
      - centroid translated to origin
      - vertices rotated to align with principal axes (PCA)
      - scaled so longest bounding box dimension = 1.0
    """
    import trimesh
    m = mesh.copy()

    # 1. Center at origin
    m.vertices -= m.vertices.mean(axis=0)

    # 2. PCA alignment — rotate to principal axes of vertex cloud
    try:
        cov = np.cov(m.vertices.T)
        eigenvalues, eigenvectors = np.linalg.eigh(cov)
        # Sort by descending eigenvalue (largest variance first)
        idx = np.argsort(eigenvalues)[::-1]
        axes = eigenvectors[:, idx]
        # Ensure right-handed coordinate system
        if np.linalg.det(axes) < 0:
            axes[:, 2] *= -1
        m.vertices = m.vertices @ axes
    except Exception as exc:
        logger.debug("PCA alignment failed, using unaligned mesh: %s", exc)

    # 3. Scale to unit bounding box
    extents = m.bounding_box.extents
    max_extent = extents.max()
    if max_extent > 1e-10:
        m.vertices /= max_extent

    return m


def _voxel_iou(mesh_a, mesh_b, resolution: int) -> float | None:
    """
    Voxelize both meshes at the same resolution and compute
    intersection-over-union of the filled voxel grids.

    Returns None — never 0.0 — when the comparison could not be computed
    (degenerate geometry, or voxelization/fill failure e.g. missing scipy).
    A swallowed exception must never look like a computed zero-overlap
    score (SPEC_v0.2 §15.1 — this is the single most important line in
    this module).
    """
    # Compute a common pitch that covers both meshes
    extents_a = np.abs(mesh_a.bounding_box.extents)
    extents_b = np.abs(mesh_b.bounding_box.extents)
    max_extent = max(extents_a.max(), extents_b.max())
    pitch = max_extent / resolution

    if pitch < 1e-10:
        logger.warning("Voxel pitch degenerate (max_extent=%s) — not evaluated.", max_extent)
        return None

    try:
        vox_a = mesh_a.voxelized(pitch=pitch).fill()
        vox_b = mesh_b.voxelized(pitch=pitch).fill()
    except Exception as exc:
        logger.error("Voxelization failed — shape check NOT evaluated: %s", exc)
        return None

    # Convert to dense boolean grids at the same shape
    a_grid = _to_dense(vox_a)
    b_grid = _to_dense(vox_b)

    # Pad to same shape
    a_grid, b_grid = _pad_to_same_shape(a_grid, b_grid)

    intersection = np.logical_and(a_grid, b_grid).sum()
    union        = np.logical_or(a_grid,  b_grid).sum()

    if union == 0:
        logger.warning("Voxel union is empty (both grids empty) — not evaluated.")
        return None

    return float(intersection) / float(union)


def _to_dense(voxel_grid) -> np.ndarray:
    """Convert a trimesh VoxelGrid to a dense boolean numpy array."""
    try:
        return voxel_grid.matrix.astype(bool)
    except Exception:
        return np.zeros((1, 1, 1), dtype=bool)


def _pad_to_same_shape(a: np.ndarray, b: np.ndarray):
    """Zero-pad both arrays to the same shape."""
    shape = np.maximum(a.shape, b.shape)
    pa = np.zeros(shape, dtype=bool)
    pb = np.zeros(shape, dtype=bool)
    pa[:a.shape[0], :a.shape[1], :a.shape[2]] = a
    pb[:b.shape[0], :b.shape[1], :b.shape[2]] = b
    return pa, pb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_mesh(mesh) -> bool:
    try:
        return (
            hasattr(mesh, "vertices")
            and hasattr(mesh, "faces")
            and len(mesh.vertices) > 0
            and len(mesh.faces) > 0
        )
    except Exception:
        return False


def _describe_result(iou: float, volume_ratio: float | None, form_only: bool) -> str:
    if iou >= 0.90:
        quality = "excellent match"
    elif iou >= 0.75:
        quality = "good match"
    elif iou >= 0.50:
        quality = "partial match"
    elif iou >= 0.25:
        quality = "poor match"
    else:
        quality = "very poor match / likely incorrect shape"

    mode = "form-only (scale+orientation normalized)" if form_only else "exact (scale+orientation matter)"
    vr_str = f", volume_ratio={volume_ratio:.3f}" if volume_ratio is not None else ""
    return f"{quality} | IoU={iou:.3f}{vr_str} | mode={mode}"
