"""
self_test.py
------------
Startup self-test (SPEC_v0.2 §2.4) — the backstop for §15.1's "no
swallowed exception may produce a score" invariant, and for Strategy A
packaging (§2.1): bundling the runtime only helps if a broken bundle is
caught immediately, not relocated silently to the instructor's machine.

Compares the bundled fixture part against itself and asserts the form
(shape) score is exactly 1.0. This one check catches a missing
scipy.ndimage hook, a broken trimesh bundle, or any future silent-zero
regression, before the app ever reports itself ready to grade.
"""

from __future__ import annotations

import sys
from pathlib import Path

FIXTURE_NAME = "test_underdefined.SLDPRT"


def _fixture_path() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller onedir/onefile: bundled data lives next to the exe
        # (onedir) or is unpacked to sys._MEIPASS (onefile).
        base = Path(sys.executable).resolve().parent
        candidate = base / FIXTURE_NAME
        if candidate.exists():
            return candidate
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / FIXTURE_NAME
        return candidate
    return Path(__file__).resolve().parent / FIXTURE_NAME


def run_self_test() -> dict:
    """
    Returns
    -------
    {
        "passed":  bool,
        "score":   float | None,
        "error":   str | None,   # short, machine-facing
        "detail":  str,          # instructor-facing explanation
    }

    Never raises — a failure here must become a displayable status, not a
    crash, since this runs before the app reports itself ready.

    Requires SolidWorks to ALREADY be running (checked via
    sw_detect.is_running(), which never launches anything). Verified live
    during Milestone 1: the comparison pipeline goes through
    sw_connection.get_connection(), whose default launch_if_not_running=True
    means calling this while SolidWorks is closed silently launches it via
    the same unreliable Dispatch() path documented in sw_detect.py's
    module docstring — which contradicts SPEC_v0.2 §3's explicit
    requirement that checking status must never launch SolidWorks as a
    side effect. So: no live SW, no self-test attempt — report that
    plainly instead of quietly triggering an unreliable launch.
    """
    result = {"passed": False, "score": None, "error": None, "detail": ""}

    try:
        import sw_detect
        if not sw_detect.is_running()["running"]:
            result["error"] = "SolidWorks is not running."
            result["detail"] = (
                "The self-test needs a live SolidWorks instance to compare "
                "the bundled fixture against itself. Launch SolidWorks from "
                "the System Ready panel, then retry — this check does not "
                "launch it for you, to avoid the unreliable auto-launch "
                "path (see sw_detect.py)."
            )
            return result
    except Exception as exc:
        result["error"] = f"Could not check SolidWorks status: {exc}"
        return result

    fixture = _fixture_path()
    if not fixture.exists():
        result["error"] = f"Bundled self-test fixture missing: {fixture}"
        result["detail"] = (
            f"The application was not built with {FIXTURE_NAME} included. "
            "This is a packaging error, not a grading error — refuse to "
            "grade and rebuild with the fixture bundled."
        )
        return result

    try:
        from tool_compare import compare_shapes
    except Exception as exc:
        result["error"] = f"Could not import the comparison pipeline: {exc}"
        result["detail"] = (
            "A bundled dependency failed to import (numpy / scipy / "
            "trimesh are the likely candidates). Check the build's "
            "--hidden-import list — scipy.ndimage in particular is "
            "invisible to static import scanning."
        )
        return result

    try:
        cmp_result = compare_shapes(str(fixture), str(fixture), form_only=True)
    except Exception as exc:
        result["error"] = f"Self-test comparison raised an exception: {exc}"
        result["detail"] = "compare_shapes() should never raise; this is itself a bug to fix."
        return result

    score = cmp_result.get("score")
    result["score"] = score

    if cmp_result.get("error"):
        result["error"] = cmp_result["error"]
        result["detail"] = (
            "The shape comparison could not be evaluated at all. The "
            "single most likely cause is a missing scipy.ndimage: trimesh "
            "needs it for VoxelGrid.fill() but declares scipy only as an "
            "optional extra, so a naive import scan misses it entirely. "
            "Rebuild with --hidden-import scipy.ndimage (see DISCOVERY_"
            "REPORT.md Phase 4.2)."
        )
        return result

    if score is None:
        result["error"] = "Self-test produced neither a score nor an error — should not happen."
        result["detail"] = "This is a bug in compare_shapes()'s error handling."
        return result

    if score != 1.0:
        result["error"] = f"Self-test form score is {score}, expected exactly 1.0."
        result["detail"] = (
            "Comparing the bundled fixture against itself should be a "
            "perfect match — both sides are literally the same file. A "
            "score below 1.0 means the voxelization/IoU pipeline is "
            "degraded, not that there's a real geometry mismatch."
        )
        return result

    result["passed"] = True
    result["detail"] = "Bundled fixture compared against itself: form score 1.0."
    return result


if __name__ == "__main__":
    r = run_self_test()
    print(r)
    sys.exit(0 if r["passed"] else 1)
