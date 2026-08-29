"""
app.py
------
SolidGrade Desktop — packaged application entry point.

Implements the Milestone 1 walking skeleton per SPEC_v0.2:
  §1   Platform & runtime (launch, port collision, shutdown)
  §2.4 Startup self-test
  §3   System Ready indicator (runtime + SolidWorks rows, Launch button)
  §10  Minimal run: folder/file pickers, run button, live progress
  §12  Raw JSON dump of results (no table — that's a later milestone)

Everything NOT in this list (assignments, rosters, ingestion/attribution,
results table, overrides, checkpointing, criteria config UI, thumbnails,
export/import, the 24-permutation search, performance work) is explicitly
out of scope for this milestone — see MILESTONE_1_REPORT.md.
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

from flask import Flask, jsonify, request

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

def _run_grading_thread(students_folder: str, solution_path: str, output_folder: str, assignment_name: str):
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
            )
        result_path = os.path.join(output_folder, f"{assignment_name}_grades.json")
        with open(result_path, "r", encoding="utf-8") as f:
            result_json = json.load(f)
        with _run_lock:
            _state["run"]["status"] = "complete"
            _state["run"]["result"] = result_json
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
    if not solution_path or not os.path.isfile(solution_path):
        return jsonify({"error": f"Solution file not found: {solution_path}"}), 400

    status = sw_detect.is_running()
    if not status["running"]:
        return jsonify({"error": "SolidWorks is not running. Launch it before grading."}), 409

    app_dir = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    output_folder = os.path.join(app_dir, "output", assignment_name)

    with _run_lock:
        _state["run"] = {
            "status": "running", "current": 0, "total": 0, "filename": None,
            "elapsed_s": 0, "file_seconds": None, "result": None, "error": None,
        }

    t = threading.Thread(
        target=_run_grading_thread,
        args=(students_folder, solution_path, output_folder, assignment_name),
        daemon=True,
    )
    t.start()
    return jsonify({"status": "started"})


@app.route("/api/run_status")
def api_run_status():
    with _run_lock:
        return jsonify(dict(_state["run"]))


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
    return jsonify({"status": "SolidGrade has shut down. You can safely close this tab."})


# ---------------------------------------------------------------------------
# UI (deliberately minimal — Step 5 of Milestone 1, not a design pass)
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return INDEX_HTML


INDEX_HTML = """<!doctype html>
<html>
<head><title>SolidGrade Desktop</title></head>
<body style="font-family: sans-serif; max-width: 900px; margin: 2em auto;">
<h1>SolidGrade Desktop <small style="color:#888">(walking skeleton)</small></h1>

<div id="ready-pill" style="padding:8px; border:1px solid #ccc; margin-bottom:1em;">
  Checking status...
</div>
<button onclick="expandStatus()">Details</button>
<button id="launch-btn" onclick="launchSW()" style="display:none;">Launch SolidWorks</button>
<pre id="status-detail" style="display:none; background:#f0f0f0; padding:1em;"></pre>

<hr>

<h2>Grade a folder</h2>
<div>
  <button onclick="pickSolution()">Pick solution .SLDPRT</button>
  <span id="solution-path">(none selected)</span>
</div>
<div>
  <button onclick="pickFolder()">Pick student folder</button>
  <span id="folder-path">(none selected)</span>
</div>
<div>
  Assignment name: <input id="assignment-name" value="SolidGrade_Run">
</div>
<div>
  <button id="run-btn" onclick="runGrading()" disabled>Run</button>
</div>

<h3>Progress</h3>
<pre id="progress">(not running)</pre>

<h3>Raw result JSON</h3>
<pre id="result-json">(no results yet)</pre>

<hr>
<button onclick="shutdown()" style="background:#c00; color:white;">Shut Down</button>
<div id="shutdown-msg"></div>

<script>
let solutionPath = null;
let folderPath = null;
let systemReady = false;

async function refreshStatus() {
  const r = await fetch('/api/status');
  const s = await r.json();
  systemReady = s.ready;
  const pill = document.getElementById('ready-pill');
  const launchBtn = document.getElementById('launch-btn');
  if (s.ready) {
    pill.style.background = '#cfc';
    pill.textContent = 'System Ready';
    launchBtn.style.display = 'none';
  } else {
    pill.style.background = '#fcc';
    pill.textContent = 'Not Ready — ' +
      (!s.runtime.self_test_passed ? 'self-test failed' :
       !s.solidworks.running ? 'SolidWorks not running' : 'unknown');
    launchBtn.style.display = s.solidworks.installed && !s.solidworks.running ? 'inline' : 'none';
  }
  document.getElementById('status-detail').textContent = JSON.stringify(s, null, 2);
  document.getElementById('run-btn').disabled = !systemReady || !solutionPath || !folderPath;
}

function expandStatus() {
  const el = document.getElementById('status-detail');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function launchSW() {
  document.getElementById('ready-pill').textContent = 'Launching SolidWorks...';
  await fetch('/api/launch_sw', {method: 'POST'});
  pollUntilReady();
}

function pollUntilReady() {
  const iv = setInterval(async () => {
    await refreshStatus();
    if (systemReady) clearInterval(iv);
  }, 3000);
}

async function pickSolution() {
  const r = await fetch('/api/pick_file', {method: 'POST'});
  const d = await r.json();
  if (d.path) {
    solutionPath = d.path;
    document.getElementById('solution-path').textContent = d.path;
  }
  refreshStatus();
}

async function pickFolder() {
  const r = await fetch('/api/pick_folder', {method: 'POST'});
  const d = await r.json();
  if (d.path) {
    folderPath = d.path;
    document.getElementById('folder-path').textContent = d.path;
  }
  refreshStatus();
}

async function runGrading() {
  const assignmentName = document.getElementById('assignment-name').value || 'SolidGrade_Run';
  const r = await fetch('/api/run_grading', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      students_folder: folderPath,
      solution_path: solutionPath,
      assignment_name: assignmentName,
    }),
  });
  const d = await r.json();
  if (d.error) {
    alert(d.error);
    return;
  }
  document.getElementById('run-btn').disabled = true;
  pollRunStatus();
}

function pollRunStatus() {
  const iv = setInterval(async () => {
    const r = await fetch('/api/run_status');
    const s = await r.json();
    document.getElementById('progress').textContent =
      `${s.status} — file ${s.current}/${s.total}: ${s.filename || ''} ` +
      `(last file ${s.file_seconds ?? '?'}s, elapsed ${s.elapsed_s}s)`;
    if (s.status === 'complete') {
      document.getElementById('result-json').textContent = JSON.stringify(s.result, null, 2);
      document.getElementById('run-btn').disabled = false;
      clearInterval(iv);
    } else if (s.status === 'error') {
      document.getElementById('result-json').textContent = 'ERROR: ' + s.error;
      document.getElementById('run-btn').disabled = false;
      clearInterval(iv);
    }
  }, 1000);
}

async function shutdown() {
  const r = await fetch('/api/shutdown', {method: 'POST'});
  const d = await r.json();
  document.getElementById('shutdown-msg').textContent = d.status;
}

refreshStatus();
setInterval(refreshStatus, 8000);
</script>
</body>
</html>
"""


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


def main():
    port, is_existing = _find_port()

    if is_existing:
        webbrowser.open(f"http://127.0.0.1:{port}")
        return

    # The self-test runs lazily on first /api/status call, not here — the
    # HTTP server (and therefore the browser tab) should come up
    # immediately; the UI shows "checking..." while the self-test (which
    # can take ~40s, since it does a full live SolidWorks round-trip) runs.
    atexit.register(_shutdown_cleanup)

    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    # threaded=True: the self-test and grading run each make long-running
    # blocking SolidWorks COM calls; without this the single-threaded dev
    # server would freeze the whole UI (including status polling) for the
    # duration of each one.
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    if _DIALOG_FOLDER_FLAG in sys.argv or _DIALOG_FILE_FLAG in sys.argv:
        # Re-invoked by _run_dialog_subprocess() to show exactly one native
        # dialog in a clean process and exit — never starts Flask or the
        # self-test. The result path is the last command-line argument.
        _dialog_worker_main(sys.argv[-1])
    else:
        main()
