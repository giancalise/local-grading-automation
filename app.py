"""
app.py
------
SolidGrade Desktop — packaged application entry point.

Implements, per SPEC_v0.2:
  §1   Platform & runtime (launch, port collision, shutdown)
  §2.4 Startup self-test
  §3   System Ready indicator (runtime + SolidWorks rows, Launch button)
  §10  Run wizard: native pickers, criteria, live check, live progress
  §12  Results table, three-state checks, overrides, CSV export

Milestone 2 changed three things about how this file is shaped:

1. The UI moved out of the inline INDEX_HTML string into ui/, styled per
   SOLIDGRADE_WEB_REFERENCE.md. Served by index()/ui_asset() below.

2. The window. Milestone 1 called webbrowser.open() and lived in a browser
   tab, which produced two problems found live: the page kept the picked
   paths only in JS memory so a refresh appeared to "lose the app" (the
   server had lost nothing — an instance from 2026-08-29 was still up and
   holding a complete 26-student run when this was diagnosed), and every
   launch opened another tab that never closed, leaving five throttled
   pollers and a server nothing ever shut down. run_window() now opens a
   real webview window whose lifetime IS the app's lifetime, and falls
   back to the browser if a webview cannot be created.

3. Three additive endpoints the styled UI needs and Milestone 1 had no
   use for: /api/validate_paths, /api/override, /api/export_csv. Every
   pre-existing endpoint kept its exact request and response shape.

Milestone 3 added §12.6's inline row actions on top of the same rule —
three more additive endpoints (/api/open_in_solidworks, /api/reveal_file,
/api/locate_sources) and no change to any existing one. §12.6 gated the
SOLIDWORKS open on §15.3 landing; it has landed and was re-verified live
in Milestone 2, so the open is unblocked, and it is written to keep that
invariant rather than assume it. There is deliberately NO "save a copy"
action: §12.6 and §13 both forbid caching student files.

Still out of scope and deliberately unbuilt: §9 ingestion/attribution,
assignment/roster models, §11.1 checkpointing, thumbnails, the
24-permutation search, and multi-part assignments.
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

# --- PyInstaller --noconsole gotcha (SPEC_v0.2 §1.3, R-15): with no
# console, sys.stdout/stderr can be None, and any print()/logging call
# would then raise. Redirect to a log file before anything else runs. ---
if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    _log_dir = os.path.dirname(sys.executable)
    _log_path = os.path.join(_log_dir, "solidgrade_desktop.log")
    _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file

from flask import Flask, jsonify, request, send_from_directory

import self_test as self_test_module
import sw_detect

APP_SIGNATURE = "solidgrade-desktop"
DEFAULT_PORT = 8731
MAX_PORT_ATTEMPTS = 10

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory state — this is a walking skeleton, not a persistence layer.
# Nothing here survives a restart, and nothing here should: no assignment
# model, no run history. One run at a time.
# ---------------------------------------------------------------------------
_state = {
    "self_test": None,
    # Where the current run's artifacts live, so /api/override and
    # /api/export_csv write back to what the run actually produced.
    "result_path": None,
    "output_folder": None,
    "run": {
        "status": "idle",   # idle | running | complete | error
        "current": 0,
        "total": 0,
        "filename": None,
        "elapsed_s": 0,
        "file_seconds": None,
        "result": None,     # full grade_assignment() JSON, dumped raw on completion
        "error": None,
    },
}
_run_lock = threading.Lock()

# Serializes ALL access to sw_connection's shared SolidWorksConnection
# singleton across Flask's per-request threads. Found live during
# Milestone 1 validation: with threaded=True, two concurrent requests can
# race on `_state["self_test"] is None` and both start a self-test
# (compare_shapes -> export_file -> get_connection()) at once, or a
# self-test can overlap a grading run — either way, two threads end up
# calling into the same raw COM dispatch pointer at once with no
# marshaling, which is the exact single-threaded-apartment hazard SPEC_v0.2
# §15.5 describes, just reached via a different path (Flask's thread pool
# instead of server.py's old threaded grading_batch or sw_timeout's worker
# thread). GetActiveObject-only calls (sw_detect.is_running) do NOT need
# this lock — each does its own fresh CoInitialize + ROT-marshaled
# attach, which is safe to call concurrently.
_com_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Health / self-test
# ---------------------------------------------------------------------------

@app.route("/healthz")
def healthz():
    return jsonify({"signature": APP_SIGNATURE, "status": "ok"})


def _self_test_is_cacheable(result: dict) -> bool:
    # A result of "SolidWorks isn't running, so we didn't even try" is a
    # precondition failure, not a verdict on the bundle — caching it would
    # permanently show a stale failure even after the user launches SW.
    return result["error"] != "SolidWorks is not running."


def _get_self_test_result() -> dict:
    if _state["self_test"] is None:
        with _com_lock:
            if _state["self_test"] is None:  # re-check: lost the race, don't rerun
                result = self_test_module.run_self_test()
                if _self_test_is_cacheable(result):
                    _state["self_test"] = result
                return result
    return _state["self_test"]


@app.route("/api/self_test")
def api_self_test():
    return jsonify(_get_self_test_result())


# ---------------------------------------------------------------------------
# System Ready indicator (§3)
# ---------------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    self_test_result = _get_self_test_result()

    sw_installed = sw_detect.is_installed()
    sw_running = sw_detect.is_running()

    ready = bool(self_test_result["passed"]) and bool(sw_running["running"])

    return jsonify({
        "ready": ready,
        "runtime": {
            "self_test_passed": self_test_result["passed"],
            "self_test_error": self_test_result["error"],
            "self_test_detail": self_test_result["detail"],
        },
        "solidworks": {
            "installed": sw_installed["installed"],
            "installed_error": sw_installed["error"],
            "running": sw_running["running"],
            "application_type": sw_running["application_type"],
            "application_type_label": sw_running["application_type_label"],
            "revision_number": sw_running["revision_number"],
            "release_year": sw_running["release_year"],
            "running_error": sw_running["error"],
        },
    })


@app.route("/api/launch_sw", methods=["POST"])
def api_launch_sw():
    return jsonify(sw_detect.launch_solidworks())


# ---------------------------------------------------------------------------
# Native folder/file pickers — a browser <input type=file> cannot return a
# server-side absolute path, and this app has no upload step (student
# files never leave the local filesystem). tkinter's native dialogs hand
# back a real path.
#
# These run in a completely separate, freshly-started process (this same
# program, re-invoked with a hidden flag), not inline inside a Flask
# request thread. Tkinter's underlying Tcl interpreter expects to own the
# thread it runs on; a Flask dev server with threaded=True hands each
# request to a new worker thread, and creating a Tk window there is
# unreliable on Windows — it can open off-screen/behind other windows or
# simply never respond. A fresh child process sidesteps this entirely: it
# gets its own real main thread with nothing else competing for it.
# ---------------------------------------------------------------------------

_DIALOG_FOLDER_FLAG = "--internal-pick-folder"
_DIALOG_FILE_FLAG = "--internal-pick-file"


def _run_dialog_subprocess(flag: str) -> str | None:
    # Hand back the result via a temp file rather than stdout: a
    # --noconsole-built frozen exe has no reliable stdout stream even when
    # re-invoked as a subprocess, but a real file on disk works the same
    # way regardless of console/frozen state.
    import tempfile
    result_path = tempfile.mktemp(prefix="solidgrade_dialog_", suffix=".txt")

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, flag, result_path]
    else:
        cmd = [sys.executable, os.path.abspath(__file__), flag, result_path]

    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        subprocess.run(cmd, timeout=300, creationflags=creationflags)
        if os.path.exists(result_path):
            with open(result_path, "r", encoding="utf-8") as f:
                path = f.read().strip()
            return path or None
        return None
    except Exception:
        return None
    finally:
        try:
            if os.path.exists(result_path):
                os.remove(result_path)
        except Exception:
            pass


def _native_dialog(kind: str) -> str | None:
    flag = _DIALOG_FOLDER_FLAG if kind == "folder" else _DIALOG_FILE_FLAG
    return _run_dialog_subprocess(flag)


def _dialog_worker_main(result_path: str) -> None:
    """
    Entry point when this program is re-invoked with one of the internal
    dialog flags. Runs exactly one native dialog on this fresh process's
    main thread and writes the chosen path (or nothing, if cancelled) to
    result_path. Never starts Flask, never runs the self-test.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", 1)
    root.update()  # force the topmost/withdraw state to actually apply before the dialog opens
    try:
        if _DIALOG_FOLDER_FLAG in sys.argv:
            path = filedialog.askdirectory(title="Select folder of student .SLDPRT files")
        else:
            path = filedialog.askopenfilename(
                title="Select solution .SLDPRT file",
                filetypes=[("SolidWorks Part", "*.SLDPRT *.sldprt"), ("All files", "*.*")],
            )
    finally:
        root.destroy()
    with open(result_path, "w", encoding="utf-8") as f:
        f.write(path or "")


@app.route("/api/pick_folder", methods=["POST"])
def api_pick_folder():
    path = _native_dialog("folder")
    return jsonify({"path": path})


@app.route("/api/pick_file", methods=["POST"])
def api_pick_file():
    path = _native_dialog("file")
    return jsonify({"path": path})


# ---------------------------------------------------------------------------
# Run grading (§10)
# ---------------------------------------------------------------------------

SLDPRT_EXTS = (".sldprt",)


def results_root() -> str:
    """
    Where grading results are written.

    Milestone 1 put this at `dirname(sys.executable)/output`, which for a
    frozen build is INSIDE dist/SolidGradeDesktop2/. That directory is
    owned by the build: PyInstaller's COLLECT step deletes and recreates it
    on every rebuild, and any installer would replace it on every update.
    Grading results are not build artifacts and must not live somewhere a
    rebuild can erase them. (This is not hypothetical — a Milestone 2
    rebuild destroyed a real 26-student run's STL set exactly this way.)

    Frozen builds therefore write to %LOCALAPPDATA%\\SolidGrade\\output,
    which no rebuild or reinstall touches. Running from source keeps the
    repo-relative output/ folder, which is convenient during development
    and is not in the path of any build step.
    """
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "SolidGrade", "output")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def resolve_solution_path(raw: str) -> tuple[str | None, str | None]:
    """
    Resolve a solution reference to a concrete .SLDPRT file path.

    Returns (path, error). Exactly one is non-None.

    SOLIDGRADE_WEB_REFERENCE.md §6.3 records that the web app writes
    `solutionStoragePath` in TWO different shapes depending on which button
    the instructor pressed: AssignmentDetail sends the first problem's
    concrete `solidworksFileUrl`, while GradingPage sends the bare folder
    prefix `solutions/{id}/` (its own comment says "Placeholder, adjust as
    needed"). A client consuming those jobs therefore receives two shapes
    for one field. DECISION (Milestone 2): accept both, defensively —
    a file is used directly; a directory is resolved to the single .SLDPRT
    inside it, and zero-or-many is a clear error rather than a guess.

    This also makes the native picker forgiving: an instructor who points
    the solution picker at a folder holding one part gets the sensible
    result instead of a validation failure.
    """
    if not raw:
        return None, "No solution file was chosen."

    if os.path.isfile(raw):
        if not raw.lower().endswith(SLDPRT_EXTS):
            return None, f"The solution must be a .SLDPRT file: {os.path.basename(raw)}"
        return raw, None

    if os.path.isdir(raw):
        parts = [
            os.path.join(raw, n) for n in sorted(os.listdir(raw))
            if n.lower().endswith(SLDPRT_EXTS) and os.path.isfile(os.path.join(raw, n))
        ]
        if len(parts) == 1:
            return parts[0], None
        if not parts:
            return None, f"No .SLDPRT file found in the solution folder: {raw}"
        # SPEC §10 step 1 / §15.2: exact match or fail. No regex fallback,
        # and no picking the alphabetically-first file and hoping.
        return None, (
            f"The solution folder holds {len(parts)} .SLDPRT files; it must hold "
            f"exactly one. Choose the specific solution part instead."
        )

    return None, f"Solution file not found: {raw}"


def count_student_parts(folder: str) -> int:
    try:
        return sum(
            1 for n in os.listdir(folder)
            if n.lower().endswith(SLDPRT_EXTS) and os.path.isfile(os.path.join(folder, n))
        )
    except OSError:
        return 0


def _run_grading_thread(students_folder: str, solution_path: str, output_folder: str,
                        assignment_name: str, voxel_resolution: int):
    def on_progress(p: dict):
        with _run_lock:
            _state["run"].update({
                "current": p["current"],
                "total": p["total"],
                "filename": p["filename"],
                "elapsed_s": p["elapsed_s"],
                "file_seconds": p["file_seconds"],
            })

    try:
        from grade_assignment import grade_assignment
        with _com_lock:
            grade_assignment(
                students_folder=students_folder,
                solution_path=solution_path,
                output_folder=output_folder,
                assignment_name=assignment_name,
                progress_callback=on_progress,
                voxel_resolution=voxel_resolution,
            )
        result_path = os.path.join(output_folder, f"{assignment_name}_grades.json")
        with open(result_path, "r", encoding="utf-8") as f:
            result_json = json.load(f)
        with _run_lock:
            _state["run"]["status"] = "complete"
            _state["run"]["result"] = result_json
            # Remembered so /api/override and /api/export_csv write back to
            # the same artifact the run produced, rather than guessing at it.
            _state["result_path"] = result_path
            _state["output_folder"] = output_folder
    except Exception as exc:
        with _run_lock:
            _state["run"]["status"] = "error"
            _state["run"]["error"] = str(exc)


@app.route("/api/run_grading", methods=["POST"])
def api_run_grading():
    with _run_lock:
        if _state["run"]["status"] == "running":
            return jsonify({"error": "A grading run is already in progress."}), 409

    data = request.get_json(force=True)
    students_folder = data.get("students_folder")
    solution_path = data.get("solution_path")
    assignment_name = data.get("assignment_name") or "SolidGrade_Run"

    if not students_folder or not os.path.isdir(students_folder):
        return jsonify({"error": f"Students folder not found: {students_folder}"}), 400
    if count_student_parts(students_folder) == 0:
        # Otherwise this starts a run that grades nobody and reports success.
        return jsonify({"error": (
            f"No .SLDPRT files in the submissions folder: {students_folder}"
        )}), 400

    solution_path, solution_error = resolve_solution_path(solution_path)
    if solution_error:
        return jsonify({"error": solution_error}), 400

    # SPEC_v0.2 §7.4 / D3: hard floor of 64 — resolution is a criteria
    # field, not a speed lever, and §7.5 marks the form check "valid only at
    # resolution >= 64". The web app's grading_jobs documents currently ask
    # for 48 (SOLIDGRADE_WEB_REFERENCE.md §6.3); anything below the floor is
    # refused here rather than quietly producing an invalid form score.
    raw_voxel = data.get("voxel_resolution", 64)
    try:
        voxel_resolution = int(raw_voxel)
    except (TypeError, ValueError):
        return jsonify({"error": f"Voxel resolution must be a whole number, got {raw_voxel!r}."}), 400
    if voxel_resolution < 64:
        return jsonify({"error": (
            f"Voxel resolution {voxel_resolution} is below the hard floor of 64 "
            f"(SPEC §7.4). The form score is only valid at 64 or above."
        )}), 400

    status = sw_detect.is_running()
    if not status["running"]:
        return jsonify({"error": "SolidWorks is not running. Launch it before grading."}), 409

    output_folder = os.path.join(results_root(), assignment_name)

    with _run_lock:
        _state["run"] = {
            "status": "running", "current": 0, "total": 0, "filename": None,
            "elapsed_s": 0, "file_seconds": None, "result": None, "error": None,
        }
        # Drop the previous run's artifact paths so an override can never
        # be written into the wrong assignment's grades file.
        _state["result_path"] = None
        _state["output_folder"] = None

    t = threading.Thread(
        target=_run_grading_thread,
        args=(students_folder, solution_path, output_folder, assignment_name, voxel_resolution),
        daemon=True,
    )
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/run_status")
def api_run_status():
    with _run_lock:
        return jsonify(dict(_state["run"]))


# ---------------------------------------------------------------------------
# Additive endpoints (Milestone 2). None of the endpoints above changed
# shape; these add three things the styled UI needs and the Milestone 1
# screen had no use for.
# ---------------------------------------------------------------------------

@app.route("/api/validate_paths", methods=["POST"])
def api_validate_paths():
    """
    Re-check paths the UI restored from localStorage after a page load.

    Without this, a restored path that has since been moved or deleted
    would render in the picker's green "chosen" state and the instructor
    would only discover it was wrong when they pressed Run — after
    committing to a run. Cheap to check, so check it.
    """
    data = request.get_json(force=True) or {}
    out = {"solution": None, "students_folder": None}

    raw_solution = data.get("solution_path")
    if raw_solution:
        resolved, error = resolve_solution_path(raw_solution)
        out["solution"] = False if error else {"path": resolved}

    folder = data.get("students_folder")
    if folder:
        out["students_folder"] = (
            {"part_count": count_student_parts(folder)} if os.path.isdir(folder) else False
        )

    return jsonify(out)


def _find_student(students: list, username: str, filename: str | None):
    for s in students:
        if (s.get("username") or s.get("uid")) == username:
            return s
    if filename:
        for s in students:
            if s.get("filename") == filename:
                return s
    return None


@app.route("/api/override", methods=["POST"])
def api_override():
    """
    Set or clear a manual grade override — SPEC_v0.2 §12.4.

    §12.4 requires `computed` and `override` be stored as an EXPLICIT PAIR
    and never mutated in place, so the auto-generated value is always
    retrievable. That is exactly what happens here: grade.total and the
    four per-check point values are never touched; only override,
    override_note and override_by are written. Sending override=null
    reverts (the one-click revert §12.4 asks for).

    The result JSON on disk is updated too, so an override survives a
    restart — the schema already reserves these three fields
    (SOLIDGRADE_WEB_REFERENCE.md §6.4), they were simply never written by
    anything until now.
    """
    data = request.get_json(force=True) or {}
    username = data.get("username")
    if not username:
        return jsonify({"error": "No student identified."}), 400

    override = data.get("override")
    if override is not None:
        try:
            override = float(override)
        except (TypeError, ValueError):
            return jsonify({"error": f"Override must be a number, got {override!r}."}), 400
        if not (0 <= override <= 100):
            return jsonify({"error": "Override must be between 0 and 100."}), 400

    with _run_lock:
        result = _state["run"].get("result")
        if not result or not result.get("students"):
            return jsonify({"error": "No results are loaded."}), 409

        student = _find_student(result["students"], username, data.get("filename"))
        if student is None:
            return jsonify({"error": f"No student named {username} in these results."}), 404

        grade = student.setdefault("grade", {})
        grade["override"] = override
        grade["override_note"] = data.get("override_note") if override is not None else None
        grade["override_by"] = "desktop" if override is not None else None

        result_path = _state.get("result_path")
        snapshot = json.loads(json.dumps(result))
        student_copy = json.loads(json.dumps(student))

    # Write outside the lock — the grading thread only touches _state["run"]
    # under it, and a slow disk should not block a status poll.
    if result_path:
        try:
            tmp = f"{result_path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, default=str)
            os.replace(tmp, result_path)   # atomic; never a half-written grade file
        except Exception as exc:
            return jsonify({"error": f"Override applied in memory but not saved: {exc}",
                            "student": student_copy}), 500

    return jsonify({"student": student_copy})


CSV_COLUMNS = [
    "username", "filename", "sw_author", "last_saved_date",
    "shape_status", "shape_score", "volume_status", "volume_mm3",
    "material_status", "material", "mass_kg",
    "sketches_status", "underdefined_sketches",
    "shape_points", "volume_points", "material_points", "sketch_points",
    "computed_total", "override", "override_note", "override_by", "effective_total",
    "plagiarism", "plagiarism_with", "needs_review", "error",
]


@app.route("/api/export_csv", methods=["POST"])
def api_export_csv():
    """
    SPEC_v0.2 §12.7 — CSV of the full table INCLUDING computed values,
    overrides and override markers. (§12.7 also says: no xlsx.)

    grade_assignment.py already writes a CSV of its own, but that one is
    produced before any override exists and has no column for them, which
    is precisely what §12.7 asks for. Written server-side rather than
    offered as a browser download because the webview shell blocks
    page-initiated downloads; the instructor gets a real path on disk.
    """
    import csv as _csv

    with _run_lock:
        result = _state["run"].get("result")
        if not result or not result.get("students"):
            return jsonify({"error": "No results to export."}), 409
        snapshot = json.loads(json.dumps(result))
        output_folder = _state.get("output_folder")
        result_path = _state.get("result_path")

    if output_folder:
        target_dir = output_folder
    elif result_path:
        target_dir = os.path.dirname(result_path)
    else:
        target_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                                     else os.path.abspath(__file__))

    name = snapshot.get("assignmentName") or "SolidGrade_Run"
    safe = "".join(c for c in name if c.isalnum() or c in "-_ ").strip() or "SolidGrade_Run"
    path = os.path.join(target_dir, f"{safe}_grades_reviewed.csv")

    try:
        os.makedirs(target_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            w.writeheader()
            for s in snapshot["students"]:
                grade = s.get("grade") or {}
                checks = s.get("checks") or {}
                flags = s.get("flags") or {}
                override = grade.get("override")
                computed = grade.get("total")
                sketches = checks.get("underdefined_sketches") or []
                w.writerow({
                    "username": s.get("username") or s.get("uid"),
                    "filename": s.get("filename"),
                    "sw_author": s.get("sw_author"),
                    "last_saved_date": s.get("last_saved_date"),
                    "shape_status": checks.get("shape_status"),
                    "shape_score": checks.get("shape_score"),
                    "volume_status": checks.get("volume_status"),
                    "volume_mm3": checks.get("volume_mm3"),
                    "material_status": checks.get("material_status"),
                    "material": checks.get("material"),
                    "mass_kg": checks.get("mass_kg"),
                    "sketches_status": checks.get("sketches_status"),
                    "underdefined_sketches": "; ".join(sketches),
                    "shape_points": grade.get("shape_points"),
                    "volume_points": grade.get("volume_points"),
                    "material_points": grade.get("material_points"),
                    "sketch_points": grade.get("sketch_points"),
                    # The computed/override pair is preserved as a pair in
                    # the export too — §12.4's "the original is always
                    # retrievable" has to survive leaving the app.
                    "computed_total": computed,
                    "override": override,
                    "override_note": grade.get("override_note"),
                    "override_by": grade.get("override_by"),
                    "effective_total": computed if override is None else override,
                    "plagiarism": flags.get("plagiarism"),
                    "plagiarism_with": flags.get("plagiarism_with"),
                    "needs_review": flags.get("needs_review"),
                    "error": s.get("error"),
                })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"path": path})


# ---------------------------------------------------------------------------
# Inline SOLIDWORKS / Explorer actions on a result row — SPEC_v0.2 §12.6
# ---------------------------------------------------------------------------
#
# §12.6 asks for two things and forbids a third:
#
#   * Open the submission (or the solution) in SOLIDWORKS, on demand,
#     "implemented by storing the absolute source path in the result record"
#     — which is what grade_assignment.py's new `source_path` /
#     `students_folder` fields now do — "with a graceful 'file moved'
#     message."
#   * Reveal the file where it actually lives.
#   * NO cached copies. §12.6's own words: that "multiplies the FERPA
#     surface for no functional gain", and §13 lists student submissions
#     under "Never stored". There is deliberately no "save a copy" action
#     here, and one must not be added quietly.
#
# §12.6 also said the SOLIDWORKS open "is only safe once §15.3 lands".
# §15.3 has landed (verified live in Milestone 2: student files stay
# byte-identical across a run, mtime untouched), so this is unblocked —
# but only if the open itself keeps that invariant, which is the whole
# design of _open_readonly_in_solidworks below.

def _file_fingerprint(path: str) -> dict | None:
    """(sha256, size, mtime_ns) of a file, or None if it cannot be read."""
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        st = os.stat(path)
        return {"sha256": h.hexdigest(), "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    except OSError:
        return None


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _authorized_paths() -> set:
    """
    The set of files a row action is allowed to touch: every student's
    source_path in the loaded result, plus the solution.

    These endpoints take a path from the page, and a path from a client is
    a path from outside. Even on a loopback-only desktop server (§1.4), an
    endpoint that opens or reveals ANY path the caller names is a general
    file-launching primitive; one that only acts on files the loaded result
    already refers to is the feature that was actually asked for. Cheap to
    constrain, so constrain it.
    """
    with _run_lock:
        result = _state["run"].get("result") or {}
        students = result.get("students") or []
        allowed = {_norm(s["source_path"]) for s in students if s.get("source_path")}
        sol = (result.get("solution") or {}).get("file")
    if sol:
        allowed.add(_norm(sol))
    return allowed


def _resolve_row_target(data: dict):
    """
    Validate a row-action path. Returns (path, error_response).

    The three failure modes are kept distinct on purpose: not-in-this-run
    is a bug or a stale page, missing-file is §12.6's "file moved" case and
    is the one the instructor will actually hit, and no-path-recorded is
    the pre-Milestone-3 result that never stored one.
    """
    raw = (data or {}).get("path")
    if not raw:
        return None, (jsonify({
            "error": "This result has no recorded path for that file.",
            "reason": "no_path",
        }), 400)

    if _norm(raw) not in _authorized_paths():
        return None, (jsonify({
            "error": "That file is not part of the loaded results.",
            "reason": "not_in_run",
        }), 403)

    if not os.path.isfile(raw):
        # §12.6's graceful "file moved" path. The submission was never
        # copied (§13), so a moved or deleted original is a normal state,
        # not a crash.
        return None, (jsonify({
            "error": "The file is no longer at " + raw + ". It may have been moved, "
                     "renamed or deleted since this run was graded.",
            "reason": "file_moved",
            "path": raw,
        }), 404)

    return os.path.abspath(raw), None


@app.route("/api/reveal_file", methods=["POST"])
def api_reveal_file():
    """
    Show the file in File Explorer with it selected. No COM, no SOLIDWORKS,
    nothing opened — the cheapest half of §12.6.
    """
    path, err = _resolve_row_target(request.get_json(force=True) or {})
    if err:
        return err

    try:
        # Passed as a COMMAND STRING, not an argument list, and deliberately.
        # A list goes through subprocess.list2cmdline, which quotes the whole
        # "/select,C:\Some Folder\part.SLDPRT" token when the path contains a
        # space — and explorer.exe does not accept that form, so it silently
        # opens the wrong window. The documented form is
        # `explorer /select,"<path>"`, which is what this builds. The path is
        # not attacker-controlled: _resolve_row_target has already checked it
        # against the loaded result's own files.
        #
        # explorer.exe also returns exit code 1 even on success, so its
        # return code is not a result — only a failure to spawn it at all is.
        subprocess.Popen('explorer /select,"' + os.path.normpath(path) + '"', close_fds=True)
    except Exception as exc:
        return jsonify({"error": "Could not open File Explorer: " + str(exc)}), 500

    return jsonify({"revealed": path})


def _open_readonly_in_solidworks(path: str) -> dict:
    """
    Open one part in the RUNNING SOLIDWORKS, visible, read-only.

    Three things about this are deliberate and load-bearing.

    1. **Its own COM attach, on this thread.** It does not touch
       sw_connection's shared singleton. That object was created on
       whichever thread first needed it (usually the grading thread), and
       reaching into a raw dispatch pointer from a Flask request thread is
       the exact single-threaded-apartment hazard §15.5 describes —
       Milestone 1 proved it corrupts the connection. A fresh
       CoInitialize + GetActiveObject on the calling thread gets a properly
       marshaled proxy of its own, which is the same pattern
       sw_detect.is_running() already uses safely from request threads.

    2. **GetActiveObject, never Dispatch.** Clicking "open this student's
       file" must not become a way to launch SOLIDWORKS. If it is not
       running, that is an error the instructor resolves with the Launch
       control they already have.

    3. **swOpenDocOptions_ReadOnly, and no read-write fallback.**
       sw_connection.open_part_silent() has a three-strategy ladder whose
       second and third rungs (OpenDoc2, bare OpenDoc) have no read-only
       flag at all — that ladder is exactly what §15.3 was written against,
       and grade_assignment.py only tolerates it because it hands
       SOLIDWORKS a scratch copy rather than the original. Here there IS no
       scratch copy: this is the instructor's real student file, opened for
       them to look at. So a failure to open read-only is reported as a
       failure. It is never retried in a mode that could write.
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        try:
            raw = pythoncom.GetActiveObject("SldWorks.Application")
        except Exception:
            raise RuntimeError(
                "SOLIDWORKS is not running. Launch it first, then try again."
            )

        # GetActiveObject hands back a PyIUnknown, which has to be
        # QueryInterface'd to IDispatch before it can be wrapped — found
        # live: passing the PyIUnknown straight to dynamic.Dispatch fails
        # with "'PyIUnknown' object has no attribute 'GetTypeInfo'".
        #
        # Late binding only from there. sw_connection.py records that early
        # binding (gencache) breaks OpenDoc on Student Edition, which is the
        # edition this machine runs.
        sw = win32com.client.dynamic.Dispatch(
            raw.QueryInterface(pythoncom.IID_IDispatch))

        try:
            sw.Visible = True
        except Exception:
            pass  # Already visible, or the property is refused; not fatal.

        SW_DOC_PART = 1
        # swOpenDocOptions_ReadOnly is 2. Verified live this session, and
        # worth stating plainly because sw_connection.py has it as 32:
        # opening with 32 leaves IsOpenedReadOnly False (32 is
        # swOpenDocOptions_AutoMissingConfig), opening with 2 leaves it
        # True. See MILESTONE_3_REPORT.md.
        SW_OPEN_READ_ONLY = 2

        # Errors and Warnings are [out] parameters and must be passed as real
        # BYREF variants. Also found live: passing plain 0, 0 raises
        # "Type mismatch" (argErr 5), because pywin32 has no type info for a
        # dynamic dispatch and sends them as [in] longs.
        from win32com.client import VARIANT
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

        doc = sw.OpenDoc6(path, SW_DOC_PART, SW_OPEN_READ_ONLY, "",
                          errors, warnings)

        if doc is None:
            # Note what does NOT happen here: there is no second strategy.
            # sw_connection's ladder falls back to OpenDoc2 and bare OpenDoc,
            # neither of which can express read-only at all. Falling back
            # that way would open the instructor's real student file
            # writable, which is the precise thing §15.3 forbids. A file
            # that will not open read-only is not opened.
            raise RuntimeError(
                "SOLIDWORKS would not open the file read-only, so it was not "
                "opened at all (error code %s). It was NOT retried in a mode "
                "that could write." % errors.value
            )

        # Ask SOLIDWORKS what it actually did, rather than trusting the flag
        # that was passed. Under late binding these read as PROPERTIES, not
        # methods — doc.IsOpenedReadOnly() raises "bool is not callable" —
        # so read the attribute and only call it if it turns out callable.
        def _sw_flag(name):
            try:
                v = getattr(doc, name)
            except Exception:
                return None
            try:
                return bool(v() if callable(v) else v)
            except Exception:
                return None

        read_only = _sw_flag("IsOpenedReadOnly")

        if read_only is False:
            # A writable student file left open on screen is one Ctrl+S away
            # from a §15.3 violation. Close it again and report the failure.
            try:
                sw.CloseDoc(doc.GetTitle)
            except Exception:
                pass
            raise RuntimeError(
                "SOLIDWORKS opened the file writable despite being asked for "
                "read-only, so it was closed again. The file was not modified."
            )

        # Bring the document to the front so the instructor sees the file
        # they clicked, rather than whatever was already on screen.
        try:
            sw.ActivateDoc3(os.path.basename(path), False, 0, 0)
        except Exception:
            pass

        return {"read_only": read_only, "view_only": _sw_flag("IsOpenedViewOnly")}
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


@app.route("/api/open_in_solidworks", methods=["POST"])
def api_open_in_solidworks():
    """
    §12.6 "Open student submission" / "Open solution", read-only.

    The response reports whether the file was byte-identical before and
    after the open. That check is not decoration: this endpoint is the one
    thing in the product that hands a real student submission to
    SOLIDWORKS, and §15.3 is the invariant it could break. The open is
    read-only by construction (above); this proves it per click rather
    than trusting it.
    """
    data = request.get_json(force=True) or {}
    path, err = _resolve_row_target(data)
    if err:
        return err

    with _run_lock:
        running = _state["run"]["status"] == "running"
    if running:
        # SOLIDWORKS is single-threaded (§15.5) and a run owns it for the
        # duration. Opening a document underneath a live grading loop would
        # interleave with its own open/rebuild/export cycle.
        return jsonify({"error": (
            "A grading run is using SOLIDWORKS. Wait for it to finish, then open the file."
        ), "reason": "run_in_progress"}), 409

    before = _file_fingerprint(path)

    try:
        with _com_lock:
            opened = _open_readonly_in_solidworks(path)
    except Exception as exc:
        return jsonify({"error": str(exc), "reason": "open_failed"}), 502

    after = _file_fingerprint(path)
    unchanged = bool(before and after and before["sha256"] == after["sha256"])
    if before and after and not unchanged:
        # Should be impossible with a read-only open. If it ever happens it
        # is a §15.3 violation and must be shouted about, not logged quietly.
        print("  !! SPEC 15.3 VIOLATION: " + path + " changed during a read-only open "
              "(" + before["sha256"][:12] + " -> " + after["sha256"][:12] + ")")

    return jsonify({
        "opened": path,
        # What SOLIDWORKS itself reports (IsOpenedReadOnly), not what was
        # requested. None means the edition would not answer.
        "read_only": opened.get("read_only"),
        "unchanged": unchanged,
        "sha256": (after or {}).get("sha256"),
    })


@app.route("/api/locate_sources", methods=["POST"])
def api_locate_sources():
    """
    Re-point a loaded result at the folder its submissions now live in.

    Results graded before Milestone 3 carry only `filename` (a basename) —
    there is no absolute path in them at all, so §12.6's row actions have
    nothing to act on. Rather than leaving those results permanently inert,
    the instructor can name the submissions folder once and every row that
    matches a file in it gets its `source_path` filled in.

    Matching is by exact basename, case-insensitively. No fuzzy matching,
    no stem-prefix guessing: §15.2 is explicit that attribution must not be
    inferred, and pointing "Open" at the wrong student's file is precisely
    the class of mistake that rule exists to prevent. A file that does not
    match by name is simply left unlinked.
    """
    data = request.get_json(force=True) or {}
    folder = data.get("students_folder")
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "Folder not found: " + str(folder)}), 400

    try:
        on_disk = {
            n.lower(): os.path.join(folder, n)
            for n in os.listdir(folder)
            if n.lower().endswith(SLDPRT_EXTS) and os.path.isfile(os.path.join(folder, n))
        }
    except OSError as exc:
        return jsonify({"error": "Could not read the folder: " + str(exc)}), 400

    if not on_disk:
        return jsonify({"error": "No .SLDPRT files in " + folder}), 400

    with _run_lock:
        result = _state["run"].get("result")
        if not result or not result.get("students"):
            return jsonify({"error": "No results are loaded."}), 409

        matched, unmatched = 0, []
        for s in result["students"]:
            name = s.get("filename")
            hit = on_disk.get(str(name).lower()) if name else None
            if hit:
                s["source_path"] = os.path.abspath(hit)
                matched += 1
            else:
                unmatched.append(name)

        result["students_folder"] = os.path.abspath(folder)
        result_path = _state.get("result_path")
        snapshot = json.loads(json.dumps(result))

    saved, save_error = False, None
    if result_path:
        try:
            tmp = result_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, default=str)
            os.replace(tmp, result_path)   # atomic, same as /api/override
            saved = True
        except Exception as exc:
            save_error = str(exc)

    return jsonify({
        "matched": matched,
        "unmatched": unmatched,
        "total": len(snapshot["students"]),
        "students_folder": snapshot["students_folder"],
        "saved": saved,
        "save_error": save_error,
        "result": snapshot,
    })


# ---------------------------------------------------------------------------
# Shutdown (§1.2)
# ---------------------------------------------------------------------------

def _shutdown_cleanup():
    try:
        from sw_connection import close_all_docs, reset_connection
        close_all_docs()
        reset_connection()
    except Exception:
        pass
    try:
        from popup_dismisser import stop_dismisser
        stop_dismisser()
    except Exception:
        pass
    try:
        from tool_export import _current_backup, _restore_stl_quality
        if _current_backup["app"] is not None:
            _restore_stl_quality(
                _current_backup["app"], _current_backup["deviation"], _current_backup["angle"]
            )
    except Exception:
        pass


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    _shutdown_cleanup()

    def _die():
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()

    # SPEC_v0.2 §1.2 mandates this exact string:
    #   "SolidGrade has shut down. You can safely close this tab."
    # It was written when the UI was a browser tab, and it is still exactly
    # right in the browser-fallback path, so that path returns it verbatim.
    # In the webview shell there is no tab — the window is the app and it
    # goes away with the process — so telling the instructor to close a tab
    # would be an instruction they cannot follow. Reality differs from the
    # spec here only because the shell changed; see MILESTONE_2_REPORT.md.
    message = (
        "SolidGrade has shut down."
        if _window is not None
        else "SolidGrade has shut down. You can safely close this tab."
    )
    return jsonify({"status": message})


# ---------------------------------------------------------------------------
# UI — Milestone 2. Static files under ui/, styled per
# SOLIDGRADE_WEB_REFERENCE.md. Replaces Milestone 1's deliberately-unstyled
# inline INDEX_HTML string.
# ---------------------------------------------------------------------------

def _resource_path(*parts: str) -> str:
    """
    Locate a bundled resource in both the dev tree and a PyInstaller build.
    onedir puts --add-data next to the exe; onefile unpacks to _MEIPASS.
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        candidate = os.path.join(base, *parts)
        if os.path.exists(candidate):
            return candidate
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return os.path.join(meipass, *parts)
        return candidate
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *parts)


@app.route("/")
def index():
    return send_from_directory(_resource_path("ui"), "index.html")


@app.route("/ui/<path:filename>")
def ui_asset(filename: str):
    # send_from_directory refuses traversal outside the directory itself.
    return send_from_directory(_resource_path("ui"), filename)


@app.after_request
def _no_store(resp):
    # A stale cached app.js/styles.css inside an embedded webview is very
    # hard to diagnose from the outside — the window just looks wrong with
    # no way to hard-reload. The payloads are a few tens of KB from
    # localhost, so caching buys nothing here.
    resp.headers["Cache-Control"] = "no-store"
    return resp




# ---------------------------------------------------------------------------
# Launch sequence (§1.1)
# ---------------------------------------------------------------------------

def _probe_existing_instance(port: int) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("signature") == APP_SIGNATURE
    except Exception:
        return False


def _find_port() -> tuple[int, bool]:
    """Returns (port, is_existing_instance). See SPEC_v0.2 §1.1.4."""
    port = DEFAULT_PORT
    for _ in range(MAX_PORT_ATTEMPTS):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            sock.close()
            return port, False
        except OSError:
            sock.close()
            if _probe_existing_instance(port):
                return port, True
            port += 1
    raise RuntimeError(f"Could not bind any port in range {DEFAULT_PORT}-{port}")


# ---------------------------------------------------------------------------
# The window (§1.1)
# ---------------------------------------------------------------------------
#
# Milestone 1 shipped the UI as a browser tab. Two problems came out of
# that, both diagnosed live rather than guessed at:
#
#   - "Refreshing the browser loses the app." The server was never the
#     problem — an instance launched 2026-08-29 was still up two days
#     later, answering /healthz in 31ms and still holding a complete
#     26-student run. The page threw its own state away on reload. Fixed
#     on the UI side (ui/app.js boot()).
#
#   - Nothing owned the app's lifetime. Every launch opened another tab
#     and closed none, and closing the last tab left the server running
#     forever. The Milestone 1 log shows the signature clearly: five
#     /api/status calls arriving together once every 60 seconds — five
#     abandoned tabs, each clamped to the background-timer floor.
#
# A real window fixes the second structurally: one window, and when it
# closes the app shuts down properly (SPEC §1.2 cleanup included). If a
# webview cannot be created, fall back to the browser rather than failing
# to start at all — a degraded UI beats no UI.

_window = None


@app.route("/api/focus", methods=["POST"])
def api_focus():
    """
    Asks an already-running instance to surface its window, so launching
    the app a second time raises the existing window instead of opening a
    second one. This is what keeps the single-instance guard (§1.1.4) from
    reintroducing the multiple-tabs problem in window form.
    """
    if _window is None:
        return jsonify({"focused": False, "reason": "running without a window"})
    try:
        _window.show()
        _window.on_top = True
        _window.on_top = False
        return jsonify({"focused": True})
    except Exception as exc:
        return jsonify({"focused": False, "reason": str(exc)})


def _serve(port: int) -> None:
    # threaded=True: the self-test and grading run each make long-running
    # blocking SolidWorks COM calls; without this the single-threaded dev
    # server would freeze the whole UI (including status polling) for the
    # duration of each one.
    app.run(host="127.0.0.1", port=port, debug=False,
            use_reloader=False, threaded=True)


def _wait_for_server(port: int, timeout: float = 15.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


def _post_to_instance(port: int, path: str) -> bool:
    import urllib.request
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}",
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def run_window(port: int) -> bool:
    """
    Open the app in a real window. Returns True if a window was shown (and
    has since been closed), False if no webview could be created — in
    which case the caller falls back to the browser.
    """
    global _window
    try:
        import webview
    except Exception as exc:
        print(f"[window] pywebview unavailable ({exc}); falling back to the browser.")
        return False

    try:
        _window = webview.create_window(
            "SolidGrade",
            f"http://127.0.0.1:{port}",
            width=1280, height=860,
            min_size=(940, 600),
            # A grading run takes tens of seconds per file and cannot be
            # resumed (§11.1 checkpointing is not built yet), so an
            # accidental window close is expensive. Confirm it.
            confirm_close=True,
        )
        # EdgeChromium explicitly: WebView2 is present on Windows 11 and is
        # the only backend worth running here. Naming it means a missing
        # runtime fails loudly at start rather than silently falling back
        # to the ancient MSHTML renderer, which cannot render this UI.
        webview.start(gui="edgechromium")
        return True
    except Exception as exc:
        print(f"[window] could not create a webview window ({exc}); falling back to the browser.")
        _window = None
        return False


def main():
    port, is_existing = _find_port()

    if is_existing:
        # §1.1.4: another copy already owns the port. Raise its window
        # rather than starting a second UI onto the same server.
        if not _post_to_instance(port, "/api/focus"):
            webbrowser.open(f"http://127.0.0.1:{port}")
        return

    # The self-test runs lazily on first /api/status call, not here — the
    # HTTP server (and therefore the window) should come up immediately;
    # the UI shows "checking..." while the self-test (which can take ~40s,
    # since it does a full live SolidWorks round-trip) runs.
    atexit.register(_shutdown_cleanup)

    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    if not _wait_for_server(port):
        print(f"[startup] server did not come up on port {port}")
        return

    if run_window(port):
        # The window was closed. The window IS the app (this is the whole
        # point of moving off a browser tab), so run the same §1.2 cleanup
        # the Shut Down control runs, then exit. os._exit because Flask's
        # server thread is a daemon with no clean stop hook.
        _shutdown_cleanup()
        os._exit(0)

    # No webview: degrade to the Milestone 1 behaviour rather than not
    # starting. Here the server genuinely does outlive the browser tab, so
    # Shut Down remains the only way to end it — as it was in Milestone 1.
    webbrowser.open(f"http://127.0.0.1:{port}")
    threading.Event().wait()


if __name__ == "__main__":
    if _DIALOG_FOLDER_FLAG in sys.argv or _DIALOG_FILE_FLAG in sys.argv:
        # Re-invoked by _run_dialog_subprocess() to show exactly one native
        # dialog in a clean process and exit — never starts Flask or the
        # self-test. The result path is the last command-line argument.
        _dialog_worker_main(sys.argv[-1])
    else:
        main()
