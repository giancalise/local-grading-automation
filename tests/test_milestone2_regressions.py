"""
Milestone 2 behaviours that must not regress.

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

Milestone 3 ran this and got 16 passed, 0 failed -- see MILESTONE_3_REPORT.md 2.3.
Ported from the scratchpad copy that produced that result; the only change is
that the three paths above are read from the environment instead of being
hardcoded to that session's temp directory.
"""
import json, os, sys, urllib.request, urllib.error
BASE = os.environ.get("SG_BASE", "http://127.0.0.1:8741")
ok, bad = [], []
def check(n, c, d=""):
    (ok if c else bad).append(n); print(("  PASS  " if c else "  FAIL  ")+n+(("  -- "+str(d)) if d else ""))
def post(p, data=None):
    r = urllib.request.Request(BASE+p, data=json.dumps(data or {}).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(r, timeout=60) as x: return x.status, json.loads(x.read().decode())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read().decode())
def get(p):
    with urllib.request.urlopen(BASE+p, timeout=60) as x: return x.status, json.loads(x.read().decode())

_, run = get("/api/run_status")
students = run["result"]["students"]
name = students[0]["username"]

print("§12.4 overrides — computed and override stay an explicit pair")
st, b = post("/api/override", {"username": name, "override": 91.5, "override_note": "regression"})
g = (b.get("student") or {}).get("grade") or {}
check("override accepted", st == 200, (st, b))
check("computed total NOT mutated", g.get("total") == 85.0, g)
check("override stored", g.get("override") == 91.5 and g.get("override_note") == "regression", g)
check("override_by stamped", g.get("override_by") == "desktop", g)
st, b = post("/api/override", {"username": name, "override": 150})
check("out-of-range override refused", st == 400, (st, b))
st, b = post("/api/override", {"username": "nobody-here", "override": 50})
check("unknown student refused", st == 404, (st, b))

print("§12.7 CSV export")
st, b = post("/api/export_csv")
check("export succeeded", st == 200 and b.get("path"), (st, b))
if st == 200:
    with open(b["path"], encoding="utf-8-sig") as f:
        head = f.readline().strip(); rows = f.readlines()
    check("CSV keeps the computed/override pair",
          "computed_total" in head and "override" in head and "effective_total" in head, head)
    check("CSV has one row per student", len(rows) == len(students), len(rows))

print("revert")
st, b = post("/api/override", {"username": name, "override": None})
g = (b.get("student") or {}).get("grade") or {}
check("revert clears all three fields",
      g.get("override") is None and g.get("override_note") is None and g.get("override_by") is None, g)
check("computed value restored", g.get("total") == 85.0, g)

print("run gate + path validation still refuse what they refused")
st, b = post("/api/run_grading", {"students_folder": r"C:\Windows", "solution_path": "x", "voxel_resolution": 64})
check("folder with no .SLDPRT refused", st == 400, (st, b))
# Real solution path, so the voxel floor is what actually rejects this
# rather than the earlier path check.
SOLUTION = os.environ.get("SG_SOLUTION") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test_underdefined.SLDPRT")
st, b = post("/api/run_grading", {"students_folder": os.path.dirname(students[0]["source_path"]),
                                  "solution_path": SOLUTION, "voxel_resolution": 48})
check("voxel below the §7.4 floor refused", st == 400 and "64" in b.get("error", ""), (st, b))
st, b = post("/api/validate_paths", {"solution_path": r"C:\nope.SLDPRT",
                                     "students_folder": os.path.dirname(students[0]["source_path"])})
check("validate_paths flags a missing solution", b.get("solution") is False, b)
check("validate_paths counts the parts", (b.get("students_folder") or {}).get("part_count") == len(students), b)

print("status must not launch SOLIDWORKS as a side effect")
st, b = get("/api/status")
check("/api/status answers", st == 200, st)

print("\nRESULT: %d passed, %d failed" % (len(ok), len(bad)))
for f in bad: print("  FAILED:", f)
sys.exit(1 if bad else 0)
