"""
Milestone 3 -- SPEC 12.6 row actions and the SPEC 15.3 invariant.

Run against a LIVE dev server that is already holding a COMPLETED grading run,
with SOLIDWORKS running. This is not a unit-test suite and has no fixtures of
its own -- it inspects the run the server is holding.

    # 1. start the server from source (no frozen build, no webview needed)
    # 2. POST /api/run_grading against SG_SUBS and wait for status "complete"
    # 3. set SG_BASE / SG_SUBS / SG_SOLUTION, then run this file

Environment:
    SG_BASE      server root          (default http://127.0.0.1:8741)
    SG_SUBS      the submissions folder the loaded run was graded from
    SG_SOLUTION  the solution part    (default <repo>/test_underdefined.SLDPRT)

SG_SUBS must be the folder the loaded run actually used: this file renames it
to prove SPEC 12.6's "file moved" path, then renames it back.

Milestone 3 ran this and got 36 passed, 0 failed -- see MILESTONE_3_REPORT.md 2.3.
Ported from the scratchpad copy that produced that result; the only change is
that the three paths above are read from the environment instead of being
hardcoded to that session's temp directory.
"""
import hashlib
import json
import os
import sys
import urllib.request

BASE = os.environ.get("SG_BASE", "http://127.0.0.1:8741")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBS = os.environ["SG_SUBS"]
SCR = os.path.dirname(SUBS)
SOLUTION = os.environ.get("SG_SOLUTION") or os.path.join(REPO, "test_underdefined.SLDPRT")

passes, fails = [], []


def check(name, ok, detail=""):
    (passes if ok else fails).append(name)
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  -- " + str(detail)) if detail else ""))


def post(path, data=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(data or {}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return r.status, json.loads(r.read().decode())


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def fingerprint(p):
    st = os.stat(p)
    return sha(p), st.st_mtime_ns, st.st_size


BASELINE_SHA = "899c98038d1ee227b2d12d7194f0e2cb7c86148d9baeb4453c1776b264ef995f"

print("=" * 72)
print("1. Prerequisite — source_path / students_folder in the result record")
print("=" * 72)
_, run = get("/api/run_status")
res = run.get("result") or {}
students = res.get("students") or []
check("run completed", run.get("status") == "complete", run.get("error"))
check("students_folder recorded at the result root",
      os.path.normcase(res.get("students_folder") or "") == os.path.normcase(SUBS),
      res.get("students_folder"))
check("every student has an absolute source_path",
      bool(students) and all(s.get("source_path") and os.path.isabs(s["source_path"]) for s in students),
      [s.get("source_path") for s in students])
check("source_path points at the real file on disk",
      all(os.path.isfile(s["source_path"]) for s in students))
check("source_path basename matches filename",
      all(os.path.basename(s["source_path"]).lower() == s["filename"].lower() for s in students))

print()
print("=" * 72)
print("2. SPEC §15.3 — student files unchanged BY THE RUN")
print("=" * 72)
after_run = {s["filename"]: fingerprint(s["source_path"]) for s in students}
for name, (h, mt, size) in sorted(after_run.items()):
    check("run left " + name + " byte-identical", h == BASELINE_SHA, h[:16])
check("run left the solution byte-identical", sha(SOLUTION) == BASELINE_SHA)

print()
print("=" * 72)
print("3. §12.6 row actions — path authorization")
print("=" * 72)
victim = students[0]["source_path"]

st, body = post("/api/reveal_file", {"path": r"C:\Windows\System32\notepad.exe"})
check("reveal refuses a path not in the run", st == 403 and body.get("reason") == "not_in_run", (st, body))

st, body = post("/api/open_in_solidworks", {"path": r"C:\Windows\System32\notepad.exe"})
check("open refuses a path not in the run", st == 403 and body.get("reason") == "not_in_run", (st, body))

st, body = post("/api/open_in_solidworks", {})
check("open refuses an empty path", st == 400 and body.get("reason") == "no_path", (st, body))

st, body = post("/api/reveal_file", {"path": victim})
check("reveal accepts a real student path", st == 200 and body.get("revealed"), (st, body))

st, body = post("/api/open_in_solidworks", {"path": SOLUTION})
check("open accepts the solution path", st == 200, (st, body))

print()
print("=" * 72)
print("4. §15.3 — the read-only OPEN does not modify the student file")
print("=" * 72)
before = fingerprint(victim)
st, body = post("/api/open_in_solidworks", {"path": victim})
check("open_in_solidworks succeeded", st == 200, (st, body))
check("SOLIDWORKS itself confirms IsOpenedReadOnly", body.get("read_only") is True, body)
check("server's own before/after hash says unchanged", body.get("unchanged") is True, body)
after = fingerprint(victim)
check("independent sha256 unchanged by the open", before[0] == after[0] == BASELINE_SHA,
      (before[0][:16], after[0][:16]))
check("mtime untouched by the open — never opened read-write", before[1] == after[1],
      (before[1], after[1]))
check("size unchanged", before[2] == after[2])

others = [s["source_path"] for s in students if s["source_path"] != victim]
for o in others:
    check("bystander " + os.path.basename(o) + " untouched", sha(o) == BASELINE_SHA)
check("solution untouched by the student open", sha(SOLUTION) == BASELINE_SHA)

print()
print("=" * 72)
print("5. §12.6 'file moved' — graceful, and recoverable via locate_sources")
print("=" * 72)
# SOLIDWORKS is holding the documents section 4 just opened, which locks the
# folder against rename. Close only the documents this test opened, by title —
# never CloseAllDocuments, which would throw away an instructor's own work.
def close_test_docs():
    import pythoncom, win32com.client
    pythoncom.CoInitialize()
    raw = pythoncom.GetActiveObject("SldWorks.Application")
    sw = win32com.client.dynamic.Dispatch(raw.QueryInterface(pythoncom.IID_IDispatch))
    for s_ in students:
        try:
            sw.CloseDoc(os.path.basename(s_["source_path"]))
        except Exception:
            pass
    try:
        sw.CloseDoc(os.path.basename(SOLUTION))
    except Exception:
        pass


close_test_docs()
check("SOLIDWORKS released the files it had open", True)

MOVED = os.path.join(SCR, "subs_moved")
if os.path.isdir(MOVED):
    import shutil
    shutil.rmtree(MOVED)
os.rename(SUBS, MOVED)
try:
    st, body = post("/api/open_in_solidworks", {"path": victim})
    check("open reports file_moved, not a crash",
          st == 404 and body.get("reason") == "file_moved", (st, body))
    st, body = post("/api/reveal_file", {"path": victim})
    check("reveal reports file_moved too",
          st == 404 and body.get("reason") == "file_moved", (st, body))

    st, body = post("/api/locate_sources", {"students_folder": MOVED})
    check("locate_sources re-links every student",
          st == 200 and body.get("matched") == len(students) and not body.get("unmatched"),
          (st, {k: v for k, v in body.items() if k != "result"}))
    check("locate_sources persisted to the results JSON on disk", body.get("saved") is True,
          body.get("save_error"))

    _, run2 = get("/api/run_status")
    new_paths = [s["source_path"] for s in run2["result"]["students"]]
    check("in-memory result now points at the new folder",
          all(os.path.normcase(os.path.dirname(p)) == os.path.normcase(MOVED) for p in new_paths),
          new_paths)

    st, body = post("/api/reveal_file", {"path": new_paths[0]})
    check("the re-linked path is now authorized and reveals", st == 200, (st, body))

    st, body = post("/api/reveal_file", {"path": victim})
    check("the OLD path is no longer authorized", st == 403, (st, body))

    st, body = post("/api/locate_sources", {"students_folder": os.path.join(SCR, "nope")})
    check("locate_sources refuses a folder that does not exist", st == 400, (st, body))
finally:
    os.rename(MOVED, SUBS)
    post("/api/locate_sources", {"students_folder": SUBS})

print()
print("=" * 72)
print("6. Nothing regressed — the results JSON on disk still parses and holds grades")
print("=" * 72)
ASSIGNMENT = res.get("assignmentName") or "M3_Test"
disk = os.path.join(REPO, "output", ASSIGNMENT, ASSIGNMENT + "_grades.json")
with open(disk, encoding="utf-8") as f:
    on_disk = json.load(f)
check("results JSON on disk parses", bool(on_disk.get("students")))
check("disk copy carries students_folder", bool(on_disk.get("students_folder")))
check("disk copy carries source_path for every student",
      all(s.get("source_path") for s in on_disk["students"]))
check("grades survived the locate_sources rewrites",
      all(isinstance((s.get("grade") or {}).get("total"), (int, float)) for s in on_disk["students"]))
check("§15.1 — shape_score is a real number, not a swallowed 0",
      all(isinstance(s["checks"]["shape_score"], float) for s in on_disk["students"]),
      [s["checks"]["shape_score"] for s in on_disk["students"]])
check("results were NOT written inside dist/", "dist" not in disk.lower().split(os.sep))

print()
print("=" * 72)
print("RESULT: {} passed, {} failed".format(len(passes), len(fails)))
for f in fails:
    print("  FAILED: " + f)
print("=" * 72)
sys.exit(1 if fails else 0)
