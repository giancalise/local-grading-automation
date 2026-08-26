# SolidGrade Desktop — Discovery Report

**Scope:** Static analysis of the `local-grading-automation` repository against
`SPEC_v0.1_SolidGrade_Desktop.md`, plus empirical testing of the pure-Python
portions of the grading pipeline and forensic reading of the two committed log
files and three committed result artifacts.

**Method and confidence.** The COM layer cannot be executed here — there is no
Windows and no SolidWorks — so everything touching `win32com` is read, not run.
Where that limits confidence, it is flagged inline. Two things *were* executed:
the geometry-comparison pipeline (`tool_compare.py`, stubbed free of its COM
imports) was installed and run against synthetic meshes, and the committed logs
and result JSON were parsed for real timing and behavioural data from live runs
in March 2026. Findings from those two sources are marked **measured** and are
high confidence.

---

## Executive Summary

**Do this before reading the rest.** A live Google Cloud service-account private
key is still present in this repository's git history, at commit `1e619e9`, in
`firebase-service-account.json`. Commit `28e333c` deleted the file from the
working tree but not from history — `git show 1e619e9:firebase-service-account.json`
prints the private key. **Rotate that key.** Deleting the file again does not
help; the key must be revoked in the Google Cloud console.

**What actually exists.** A working, single-purpose grading pipeline for
single-body `.SLDPRT` parts, validated on **SolidWorks Student Edition**
(`ApplicationType=1` in all eight logged connections — not Desktop, and no
evidence anywhere of the "SolidWorks 2026 Desktop" the spec assumes). It performs
four checks — shape, volume, material, sketch-definition — and has produced real
grades for a 24-student quiz and a multi-problem midterm. The COM connection
layer, the four readers, the STL exporter and the popup dismisser are genuinely
reusable. That is roughly the bottom third of the spec.

**What does not exist.** Everything above the pipeline. There is no web server,
no HTML, no persistence model, no assignment model, no roster, no ingestion or
attribution logic, no checkpointing, no resume, no override mechanism, no
thumbnails, no criteria configuration of any kind. Rubric weights and thresholds
are module-level constants duplicated across two files and edited by hand. There
is no `requirements.txt`, no `pyproject.toml`, no config file of any type, and no
`.gitignore`. §§1, 3, 5, 6, 8, 9, 10, 11, 12, 13 of the spec are green-field.

**What the spec gets wrong.**
- **§6.4 thumbnails: the proposed OLE compound-document route is dead.** The
  sample `.SLDPRT` in this repo is not an OLE compound file (magic `99 01 9f 76`,
  not `d0cf11e0…`) and contains no BMP, PNG, JPEG or GIF stream. Document Manager
  SDK is the only remaining API route and it needs a separately licensed key from
  Dassault.
- **§14 lists modules that do not exist.** `dm_connection.py` is referenced in
  `sw_connection.py`'s docstring and is absent. The "timeout wrapper for stalling
  COM calls" exists as a file (`sw_timeout.py`) but is imported by nothing;
  `open_part_silent` advertises a `timeout` parameter and silently ignores it.
- **§11.3's optimism is misplaced.** The COM layer does not fail fast. With no
  timeout anywhere in the production path, a SolidWorks stall hangs the run
  indefinitely rather than producing a failed item.
- **§12.6's tension resolves in favour of keeping student files.** Grading is
  already destructive of the "never store submissions" rule in a subtler way —
  student files are opened read-write, not read-only (see Phase 6, R-3).

**The three findings that can silently produce a wrong grade.**

1. **Missing `scipy` gives every student a shape score of 0.0 with no error.**
   *Measured.* `scipy` appears in no import statement in this repo, but
   `trimesh`'s `VoxelGrid.fill()` needs `scipy.ndimage`, and `trimesh` declares
   `scipy` only as an optional extra. When it is absent, trimesh raises,
   `_voxel_iou` swallows the exception at `logger.debug` level and returns `0.0`,
   and the result still reports `method: "normalized_pca_iou"` and `error: null`.
   I ran this: an identical part compared against itself scores **0.0**, silently.
   This is the single most dangerous line in the codebase and it interacts
   directly with the §2 packaging decision.
2. **Symmetric parts fail catastrophically.** *Measured.* A cube compared against
   the same cube rotated 45° about Z scores **0.364**. PCA axes are degenerate for
   parts with equal principal moments, and the eight sign-flips the code tries
   cover only 8 of the 24 rotational alignments. A correct part gets a failing
   shape score.
3. **Filename collisions swap students' grades.** In `grading_agent.py`, the
   flatten step skips copying a file whose name already exists but *unconditionally*
   overwrites the identity-map entry for that name. Two students submitting
   `Part1.SLDPRT` means one file is graded and attributed to the other student.
   The spec's §9.1 "flat folder" case is precisely this scenario.

**Packaging recommendation: Strategy A (bundle), with a caveat.** The dependency
set is small (7 runtime packages) and all have CPython 3.14 Windows wheels.
Realistic PyInstaller onedir size is **250–400 MB**; onefile ~150 MB. Strategy B is
actively unsafe here because of finding #1 above: a detect-and-install check that
scans imports will not know `scipy` is required, will install a working-looking
environment, and will produce zeros. Bundle it, and add an explicit startup
self-test that compares a known part against itself and refuses to run if the
score is not 1.0.

**Realistic timing.** *Measured from the agent log:* **33–97 seconds per part
file**, at `VOXEL_RES=64`, and the number climbed steadily across a 90-minute
session grading the same five files repeatedly — evidence of SolidWorks
degradation under sustained use. Size the progress UI for ~60 s/file: a 20-student
× 4-problem assignment is **60–100 minutes**, not minutes.

---

## Phase 1 — Inventory

29 files. 27 Python (one unparseable), 3 result artifacts, 1 sample part, 2 logs,
1 stray empty file. No configuration files of any kind.

### 1.1 Production logic — the reusable core

| Path | Size | Purpose | State |
|---|---|---|---|
| `sw_connection.py` | 19.7 KB | COM connect, silent open, close, health check, stall recovery. Module-level singleton `get_connection()`. | **Functional with defects.** See 1.6. |
| `tool_mass.py` | 6.6 KB | Reads mass / volume / surface area / CoM / density / material from an open doc. | Functional. |
| `tool_metadata.py` | 8.6 KB | Reads `SummaryInfo` author + dates and custom properties. Three fallback strategies for custom props. | Functional; **the "author" field is misnamed** (see Phase 3). |
| `tool_sketch.py` | 5.3 KB | Sketch constraint status via raw DISPID probe (`IFeature` DISPID 7 → `ISketch` DISPID 48). | Functional on Student Edition; unverified elsewhere. |
| `tool_export.py` | 6.6 KB | `SaveAs`-based STL/STEP/IGES export with STL quality presets. | Functional. |
| `tool_compare.py` | 12.9 KB | STL → trimesh → PCA-normalize → 64³ voxel IoU. | **Functional but scale-blind and unsafe on symmetric parts.** See Phase 3. |
| `popup_dismisser.py` | 5.9 KB | `EnumWindows` polling thread that clicks OK/Yes on SolidWorks modal dialogs. | Functional and **load-bearing** — fired 76× in the agent log, once per file open. |
| `grade_assignment.py` | 24.5 KB | Batch grading, one problem, N students. Writes JSON + CSV + STLs. **This is the primary entry point.** | Functional; several defects (Phase 6). |
| `grade_midterm.py` | 19.9 KB | Batch grading, N problems × N students. Writes a styled two-sheet `.xlsx`. | Functional; **duplicates ~70% of `grade_assignment.py` with divergent constants.** |

### 1.2 Server / integration layer

| Path | Size | Purpose | State |
|---|---|---|---|
| `server.py` | 24.3 KB | FastMCP stdio server. 6 generic SolidWorks tools + 6 grading tools. | Functional as an MCP server. Contains a **threaded COM bug** (Phase 6, R-6) and a `save_file` tool that can modify student files. |
| `server_additions.py` | 9.8 KB | An earlier, **sequential** copy of server.py's grading-tool block, meant to be pasted in. | **Superseded / not importable** — references `mcp` and `log`, which are undefined at module scope. Ironically its `grading_batch` is the *correct* one. |
| `grading_agent.py` | 21.4 KB | Firebase bridge: polls Firestore for jobs, downloads from Storage, calls `grade_assignment`, uploads results. | **Broken as checked out** — requires `firebase-service-account.json`, deleted in `28e333c`. Also hardcodes `C:\Users\gce4\Documents\solidworks-mcp`. |

### 1.3 Canvas tooling — a separate, unconnected 3-script pipeline

| Path | Size | Purpose | State |
|---|---|---|---|
| `canvas_downloader.py` | 22.4 KB | Selenium-driven SpeedGrader download into per-student folders. Has retry/stability logic. | Standalone; interactive (`input()`); imported by nothing. |
| `canvas_reorganizer.py` | 16.8 KB | Interactive: infers problem number from filename, moves into `Problem_N/`, writes `submission_map.json`. | Standalone. **The only prior art for spec §9.** |
| `canvas_clicker.py` | 15.9 KB | Reads `submission_map.json`, clicks credit buttons in SpeedGrader. | Standalone. Out of scope for the desktop app. |
| `canvas_scraper.py` | 20.3 KB | An **earlier all-in-one** version ("v9") of downloader + reorganizer. | **Superseded** by the downloader/reorganizer split. |

### 1.4 Diagnostics / probes — all one-off, all hardcoded to one machine

`diag.py` (5.0 KB, COM connectivity + open strategies), `diag_batch.py` (7.8 KB,
**the ancestor of `grade_assignment.py`**), `diag_crash.py` (1.3 KB, recovery),
`diag_export.py` (2.0 KB, STL API probe), `diag_mass.py` (1.6 KB, the probe that
established the `GetMassProperties` index map), `diag_popup.py` (1.7 KB, pywinauto
dialog identification), `diag_props.py` (2.3 KB, the probe that established the
`SummaryInfo` index map), `diag_sketch.py` (2.9 KB, **the probe that established
DISPID 7→48, with ground-truth expectations for 6 named files**), `diag_timing.py`
(1.5 KB, cache-effect timing).

All hardcode `C:\Users\gce4\Box\ES-19\...`. All are **historically valuable as the
provenance for the magic constants** and should be kept, but none is production
code. `diag_sketch.py` in particular is the only evidence that the sketch check was
validated against ground truth (19/19 per `tool_sketch.py`'s docstring).

### 1.5 Dead, junk, and artifacts

| Path | Verdict |
|---|---|
| `sw_timeout.py` (1.8 KB) | **Dead.** Imported by nothing. A stale `.pyc` in `__pycache__` proves it was wired in once and removed. |
| `test_firebase.py` (0.9 KB) | Dead — needs the deleted credential. |
| `python test_firebase.py` (1.2 KB) | **Junk.** A shell mishap: a chat transcript was redirected into a file whose name is a command line. Contains prose and markdown. Unparseable as Python. |
| `python` (0 bytes) | **Junk.** Same cause. |
| `__pycache__/*.pyc` (9 files, cpython-**314**) | Build artifacts, committed. Confirms **Python 3.14**. |
| `output/Quiz3_grades.json`, `.csv` | Real results, 24 students. **Schema does not match any current script** — no `checks`/`geometry`/`grade.override` keys, `flags` is a list not a dict. Produced by an intermediate version between `diag_batch.py` and today's `grade_assignment.py`. |
| `output/MT26_grades.xlsx` (25 KB) | Real midterm output from `grade_midterm.py`. |
| `test_underdefined.SLDPRT` (154 KB) | Sample part. Useful as a fixture. |
| `grading_agent.log` (1.0 MB), `solidworks_mcp.log` (163 KB) | Committed logs. **Forensically valuable** (all timing data in this report comes from them) but should not be in version control. |

### 1.6 Referenced but missing

- **`dm_connection.py`** — named in `sw_connection.py:21` as the home of Document
  Manager. Does not exist. This is the module the spec's §6.4 thumbnail plan
  implicitly depends on.
- **`firebase-service-account.json`** — required by `grading_agent.py` and
  `test_firebase.py`. Deleted from the tree; **still in git history**.
- **`requirements.txt` / `pyproject.toml`** — absent. No dependency is pinned
  anywhere. Answers spec §15.11: **there are no existing config file formats to
  adopt.**
- **`.gitignore`** — absent, which is why `__pycache__`, the logs, and the
  credential were all committed.
- **`submission_map.json`** — produced by `canvas_reorganizer.py`, consumed by
  `canvas_clicker.py`. Not in repo (runtime artifact). This is the closest thing
  to an existing ingestion data format; it is undocumented.

---

## Phase 2 — Dependency Graph

### 2.1 The production call graph

```
grading_agent.py  (Firebase polling loop — the cloud entry point)
    └── grade_assignment.grade_assignment()      ← THE REAL ENTRY POINT
         │
         ├── popup_dismisser.ensure_dismisser_running()
         ├── sw_connection.get_connection() ──► SolidWorksConnection (singleton)
         │        └── open_part_silent() ──► popup_dismisser.ensure_dismisser_running()
         │
         ├── tool_export.export_file()   ──► get_connection(), doc.SaveAs()
         ├── tool_metadata._read_summary_properties(doc)      ← private fn
         ├── tool_mass._read_mass_properties(doc)             ← private fn
         ├── tool_mass._read_material(doc)                    ← private fn
         ├── tool_sketch._read_sketch_statuses(doc)           ← private fn
         ├── tool_compare._normalize_mesh() / compare_meshes_normalized()
         │        └── _voxel_iou() ──► trimesh ──► [scipy.ndimage]  ← undeclared
         └── sw_connection.recover_from_stall()
```

`grade_midterm.py` has an identical shape, substituting `openpyxl` output.

### 2.2 True entry points

Four, in descending order of relevance to the desktop app:

1. **`grade_assignment.grade_assignment(...)`** — importable function *and* CLI.
   This is what the desktop app should call.
2. **`grade_midterm.grade_midterm(...)`** — same, multi-problem.
3. **`server.py` `__main__`** — MCP stdio server for Claude Desktop.
4. **`grading_agent.main()`** — Firebase daemon.

### 2.3 The MCP seam (spec §14.1 / §15.7)

**The coupling is trivially thin, and the separation already exists.** Every
grading tool in `server.py` is a two-line wrapper:

```python
@mcp.tool()
def grading_get_mass_properties(filepath: str) -> dict:
    log.info(...)
    result = _get_mass_properties(filepath)   # ← the real function, from tool_mass
    return result
```

`tool_*.py` import nothing from `mcp` and nothing from `server`. The dependency
runs strictly server → tools, never the reverse. **The desktop app can `import
tool_mass` today and delete nothing.** There is no extraction work to do.

The one wrinkle: `grade_assignment.py` and `grade_midterm.py` do not call the
public tool functions (`get_mass_properties(filepath)`), they call the **private
per-document readers** (`_read_mass_properties(doc)`) directly, to avoid
re-opening the file for each check. That is the right optimisation and it is why
per-file time is ~60 s and not ~4 minutes — but it means the private functions are
the de-facto public API. Formalise them: `read_mass(doc) -> dict` etc., taking an
open document, with the file-path wrappers layered on top.

### 2.4 Circular and surprising dependencies

- **No import cycles.** The graph is a clean DAG.
- **Surprising:** `sw_connection` imports `popup_dismisser` and calls it from
  inside `_open_part_silent_inner`. Connection management and GUI automation are
  entangled. For a packaged app this matters (Phase 6, R-5).
- **Surprising:** `grade_assignment.py` and `grade_midterm.py` execute
  `pythoncom.CoInitialize()` **at module import time**, before any function runs.
  A Flask/FastAPI app that imports these modules initialises COM on whatever
  thread happened to do the import — usually not the thread that will later make
  COM calls. This will need to move into an explicit init function.
- **Surprising:** `tool_compare.compare_shapes` opens both files through
  `export_file`, which itself calls `get_connection()` and `close_doc()`. Callers
  that already have the document open (i.e. all of them) trigger a redundant
  open/close cycle per file.

### 2.5 Duplicated functionality

| Duplicated thing | Where | Divergence |
|---|---|---|
| Mass-property reading | `tool_mass._read_mass_properties` **and** `server.get_mass_props` | Different APIs (`GetMassProperties` vs `CreateMassProperty`/`GetMassProperties2`) and **different units** — tool_mass returns mm³, server.py returns m³. |
| Batch grading orchestration | `grade_assignment` / `grade_midterm` / `diag_batch` | Three copies of the same loop. |
| Rubric + thresholds | `grade_assignment.py:88-99` **and** `grade_midterm.py:44-52` | `VOXEL_RES` is **64** in one and **24** in the other. The same submission gets different shape scores depending on which script grades it. |
| `compute_grade()` | Both graders | Byte-identical logic, different return keys. |
| `extract_username()` | Both graders | Identical. |
| MCP grading-tool block | `server.py` **and** `server_additions.py` | server.py's version is threaded (broken); server_additions' is sequential (correct). |
| Canvas download | `canvas_downloader.py` **and** `canvas_scraper.py` | scraper is the superseded v9. |

### 2.6 Clean seams for the desktop app

Three cut points, all clean:

1. **`tool_*.py` + `sw_connection.py` + `popup_dismisser.py` → a `solidgrade.cad`
   package.** No changes needed beyond making the `_read_*(doc)` functions public
   and removing the import-time `CoInitialize`.
2. **Grading orchestration → a `solidgrade.grading` package.** Requires real work:
   collapse the three copies into one, and lift the rubric constants into a
   passed-in config object. This is the boundary where spec §7 (criteria
   inheritance) plugs in.
3. **Output → `solidgrade.results`.** Today, JSON/CSV/XLSX writing is inlined in
   the graders. The desktop app needs structured data, not files; the writers
   become optional exporters.

The Firebase layer (`grading_agent.py`) is **not** a seam — it is a peer
consumer of the same core, and answers spec §15.6: **nothing in the cloud
front end is reusable, and the desktop version should be fully decoupled.** The
web app is Firebase/Firestore-shaped (jobs collection, Storage prefixes, Auth
UIDs as identity) and the desktop app is filesystem-shaped. The only thing worth
carrying over is the **results JSON schema** documented in `grade_assignment.py`'s
docstring — which is already richer than what the code emits and is a reasonable
starting point for §12.

---

## Phase 3 — Capability Audit

Four checks exist. The spec's §7.2 table lists exactly these four and names them
correctly, but gets the units and the reliability wrong in several places.

### 3.1 Shape comparison — `tool_compare.compare_shapes`

- **Measures:** intersection-over-union of two filled 64³ voxel grids, after each
  mesh is independently centred, PCA-aligned and scaled to unit max-extent; best
  of 8 axis sign-flips.
- **Inputs:** two absolute `.SLDPRT` paths, `form_only: bool = True`.
- **Output:** `{score: float 0–1, method: str, details: str, volume_ratio: float|None, iou_score: float|None, error: str|None}`.
- **Units:** dimensionless. `volume_ratio` is student/solution from the *mesh*
  volumes, not the SolidWorks volumes.
- **Execution time:** dominates the ~60 s/file budget. Two STL exports (~3 s each
  from SolidWorks) plus 8 voxelisations at 64³.

**Measured behaviour** (synthetic meshes, this repo's code, `VOXEL_RESOLUTION=64`):

| Case | IoU | Verdict |
|---|---|---|
| Identical part | **1.0000** | correct |
| Same shape at **2× scale** | **1.0000** | **scale is normalized away** |
| Same shape modeled **in inches** (25.4×) | **1.0000** | **wrong units score perfect** |
| Box 40×20×10 vs 40×20×14 (genuinely wrong) | 0.7391 | correctly fails 0.95 |
| **Cube vs same cube rotated 45° about Z** | **0.3640** | **correct part scores 0.36** |
| Sphere, coarse vs fine tessellation | 0.9916 | ~0.8 % noise floor |
| Cylinder vs same cylinder spun 40° | 0.9995 | correct |
| **Identical part, `scipy` unavailable** | **0.0000**, `error: null` | **silent total failure** |

Three consequences:

1. **The scale-blindness is deliberate and documented as a feature.**
   `server.py`'s docstring says: *"a correct part modeled off the wrong plane or
   in inches instead of mm will still score well."* For a CAD course where
   dimensional accuracy is the point, this hands 65 of 100 points to a part
   modeled at the wrong size. The only thing catching it is the ±1 % volume
   check, worth 10 points. **This is a rubric design decision the humans must
   confirm, not a bug** — but the spec's §7.2 "Shape comparison" row must say so
   explicitly.
2. **PCA degeneracy on symmetric parts is a genuine defect.** For parts with two
   or three equal principal moments (cubes, square prisms, regular polygonal
   solids — common in intro CAD assignments) the PCA frame is arbitrary and the
   8 sign-flips cannot recover it. Fix: search the 24 axis-permutation × sign
   combinations, not 8; and detect near-equal eigenvalues and fall back to a
   coarse rotational search.
3. **The `volume_ratio` fallback silently changes what `score` means.** If IoU
   throws, the code sets `score = 1 - |1 - volume_ratio|` and `method =
   "volume_ratio_fallback"` — a number in the same field with completely
   different semantics. Two parts of identical volume and totally different shape
   score 1.0. Any consumer that reads `score` without checking `method` is wrong.
   `grade_assignment.py` does not check `method`.

**Noise floor, from the field.** In `output/Quiz3_grades.json`, 17 of 24 students
have `volume_mm3` agreeing to ~13 significant figures (18366.50138628642…), i.e.
geometrically identical models — yet their shape scores span **0.9681 to 1.0000**.
That run used `VOXEL_RES=24`. So the practical noise floor is ~3 % at res 24 and
~0.8 % at res 64 (measured above). The 0.95 threshold sits only ~1.5 noise-widths
above the res-24 floor. **Use 64. Do not let anyone set it lower for speed
without understanding this.**

### 3.2 Mass properties — `tool_mass.get_mass_properties`

- **Measures:** `IModelDoc2.GetMassProperties` (a *property*, not a method, on
  this build), plus `MaterialIdName`.
- **Output:** `{mass: kg, volume: mm³, surface_area: mm², center_of_mass: {x,y,z} mm, density: kg/mm³, material_assigned: bool, material_name: str|None, error: str|None}`.
- **Index map used:** `[0..2]` CoM, `[3]` volume m³, `[4]` surface area m², `[5]` mass kg.
- **Reliability:** the values are almost certainly correct — they were
  cross-validated against brass density and the field data is self-consistent.
  **But the comment justifying them is wrong**, and that matters. `tool_mass.py`
  claims this ordering is a *"non-standard order"* peculiar to Student Edition.
  It is not: `(CoM×3, volume, surface area, mass, inertia×6)` is the ordering
  documented for `IModelDoc2::GetMassProperties`. The code is right for the wrong
  reason. **Consequence:** the spec's §15.8 worry about "non-standard property
  index orders across editions" is, for this call, unfounded — the risk of the
  index map differing on Desktop is low. *Confidence: high on the ordering,
  medium that no edition deviates; verify on Desktop before shipping.*
- **`density` is in kg/mm³** — an unusual unit (brass ≈ 8.5e-6). It is computed
  and returned but never consumed by any grader. Either surface it with the unit
  spelled out or drop it.
- **Failure mode:** if `GetMassProperties` returns fewer than 6 elements the code
  sets `error` and returns — but callers in `grade_assignment.py` do not check
  that error. `volume` stays `None`, `volume_ok` evaluates to `False`, and the
  student loses 10 points plus the shape-credit bonus **for a read failure they
  did not cause**. No flag distinguishes "wrong volume" from "could not read
  volume". *This is a silent-wrong-grade path; see Phase 6, R-2.*

### 3.3 Metadata — `tool_metadata.get_file_metadata`

- **Measures:** `doc.SummaryInfo(i)` at fixed indices, plus custom properties via
  three fallback strategies.
- **Output:** `{last_saved_by, author, last_saved_date (ISO-8601), custom_properties: dict, raw_identity_properties: dict, error}`.
- **Index map used:** `[5]` → `author`, `[6]/[7]` created/saved short, `[8]/[9]` long.

**The `author` field is misnamed, and this changes what the plagiarism check
means.** In the SolidWorks `swSummInfoField_e` enum, index 5 is `swSumInfoSavedBy`
— *last saved by* — while the creator is at a lower index. The code reads index 5
into a field it calls `author`, and leaves the correctly-named `last_saved_by`
field permanently `None`.

**The field data corroborates this.** In `output/Quiz3_grades.json`,
`Kondo.Rachel-Quiz3-1.SLDPRT` has `sw_author: "GCE4"` — the instructor's own login
— with `last_saved_date: 2026-03-14`, two weeks after every other submission and
one day before the grading run. That is exactly what "last saved by" does when an
instructor opens and saves a student's file. A creator field would still say
"Kondo". *Confidence: high, on enum knowledge plus corroborating data. Verify by
running `diag_props.py` and reading indices 2 and 5 side by side.*

Consequences: (a) any student who opens a classmate's file and saves inherits it;
(b) any instructor who touches a file erases the student's identity — as happened
here; (c) the field is still *useful* for plagiarism, but it must be labelled
"last saved by" in the UI, and spec §9.4's "file metadata author field" signal
must be re-described.

Other reliability notes, all visible in the field data: authors observed include
`ccampb11`, `KChan10` (university logins — useful) alongside `light`, `Finnk`,
`laver`, `willi`, `Sara`, `Allison` (personal-machine account names — useless for
matching). Roughly **25 % of the sample is unusable for roster matching.** Spec
§9.4 correctly ranks this signal third; the data says it should be third and
weighted low.

### 3.4 Sketch status — `tool_sketch.check_sketch_status`

- **Measures:** for each `ProfileFeature`/`3DProfileFeature`, invokes raw
  **DISPID 7** on `IFeature` to get the `ISketch`, then raw **DISPID 48** on
  `ISketch` for a status integer.
- **Output:** `{underdefined_count: int, underdefined_sketch_names: [str], all_sketches: [{name, status}], method: "dispid_probe", error}`.
- **Status map:** `3=FULLY_DEFINED`, `2=UNDERDEFINED` — **empirically confirmed
  against ground truth**, 19/19 per the docstring, with the fixtures listed in
  `diag_sketch.py`. `1=OVERDEFINED` and `0=NO_SOLUTION` are explicitly labelled
  **hypotheses, never confirmed with test data.**
- **Reliability: this is the most fragile check in the system.** Raw DISPIDs are
  not a public contract. They are stable within a build and Dassault has no
  obligation to keep them stable across releases or editions. The code was written
  because named dispatch was "locked out" on Student Edition (`tool_sketch.py`
  docstring) — a symptom that is itself edition-specific, meaning **on Desktop the
  named `ISketch::GetFullyDefinedStatus` may simply work.**
- **Failure mode: fails to `"UNKNOWN"`, and `"UNKNOWN"` is counted as passing.**
  `_get_sketch_status` catches every exception and returns `UNKNOWN`; the callers
  filter for `status == "UNDERDEFINED"`, so an UNKNOWN sketch contributes nothing
  to `underdefined_count`, `sketches_ok` comes back `True`, and the student is
  awarded the full 15 points. **If DISPID 48 changes meaning in a future
  SolidWorks release, every student silently passes the sketch check.** See Phase
  6, R-1.

### 3.5 Plagiarism — inline in the graders, not a tool module

- **Measures:** groups students by identical `sw_author` string; any group of size
  > 1 flags every member.
- **Reliability: untested in the field.** In the only committed dataset all 24
  authors are distinct, so this code path has never fired on real data.
- **Two defects.** (i) In `grade_assignment.py`, `author_map` is keyed with the
  *filename-derived* username (line 447) but the self-exclusion at line 468
  compares against `record["username"]`, which is the *Firebase display name*
  when an identity map is supplied. The names never match, so **a student is
  listed as their own plagiarism partner.** `grade_midterm.py` does not have this
  bug. (ii) With "author" actually meaning "last saved by", any cohort working on
  shared lab machines under one login will be flagged en masse.

### 3.6 Checks the spec does not mention

- **`volume_ratio`** (in `compare_shapes`) — computed, returned, never used.
- **Surface area, centre of mass, density** — read and returned by `tool_mass`,
  never used by any grader. Free additional checks if the spec wants them.
- **`last_saved_date`** — captured and written to results. Not scored, but this is
  the natural signal for a late-submission or post-deadline-edit check.
- **STEP / IGES export** — `tool_export` supports both; nothing calls them.
- **`compare_models`** (MCP tool) — a human-readable A/B property diff.
  Superseded by the grading tools.

---

## Phase 4 — Dependency and Packaging Assessment

### 4.1 The exact dependency set

Derived by AST-walking every parseable `.py` file. Nothing is version-pinned
anywhere in the repository.

**Required by the production grading path** (what the desktop app needs):

| Package | Import(s) | Compiled? | Notes |
|---|---|---|---|
| `pywin32` | `win32com`, `pythoncom`, `win32api`, `win32con`, `win32gui` | **C ext** | The COM and window layer. |
| `numpy` | `numpy` | **C ext** | ~12.6 MB wheel, ~40 MB installed. |
| `trimesh` | `trimesh` | pure Python | 0.7 MB. Declares only `numpy` as a hard dep. |
| **`scipy`** | **none — undeclared** | **C ext** | **Required at runtime by `trimesh.voxel.morphology.fill_holes`.** 37.4 MB wheel, ~120 MB installed. |
| `openpyxl` | `openpyxl` | pure Python | Only for `grade_midterm.py`'s xlsx. See §12.7 below. |

**Required only by paths the desktop app should drop:**

| Package | Used by | Verdict |
|---|---|---|
| `mcp` | `server.py` | Not needed — desktop app calls the tools directly. |
| `firebase-admin` | `grading_agent.py`, `test_firebase.py` | Not needed — drop the cloud path. Pulls in grpc, google-api-core, protobuf — a large transitive tree. |
| `requests` | `grading_agent.py` | Not needed. |
| `selenium` | all four `canvas_*.py` | Not needed for grading; see §15.5 below. Also needs a matching ChromeDriver, which is its own distribution problem. |
| `pywinauto` | `diag_popup.py` only | Not needed. The production dismisser uses raw `win32gui`. |

**So: 5 packages for the core app, 4 of them with compiled extensions.** Plus
whichever web framework is chosen (Flask 0.1 MB or FastAPI 0.14 MB + uvicorn,
both pure Python).

### 4.2 The `scipy` landmine

Worth stating separately because it drives the Strategy A/B decision.

`scipy` is imported in **zero** files in this repository. It appears once, as a
string, in an error message: `"trimesh not installed. Run: pip install trimesh
numpy scipy"`. Any dependency check built by scanning imports will conclude scipy
is not needed.

But `trimesh/voxel/base.py` defines `fill(self, method="holes")`, and
`fill_holes` calls `scipy.ndimage.binary_fill_holes`. `tool_compare._voxel_iou`
calls `.fill()` with no arguments — so it takes the `"holes"` path, every time.
`trimesh` wraps the scipy import in `try/except` and substitutes an
`ExceptionWrapper`, so the failure surfaces only when the function is called —
inside `_voxel_iou`'s bare `except Exception: return 0.0`.

**I ran this.** With `scipy.ndimage` replaced by trimesh's `ExceptionWrapper`,
comparing an identical part against itself returned `0.0`, with no exception, no
log at INFO level, and no `error` field set. Every student would score 0 on the
65-point shape check and the report would look normal.

### 4.3 PyInstaller feasibility

**Python version.** `__pycache__` contains `cpython-314` bytecode and the log
paths reference `Python314`. This is **Python 3.14** — very new. I checked PyPI:
`numpy`, `scipy` and `pywin32` all publish `cp314` Windows x64 wheels, so the
runtime is viable, but it is close to the frontier and PyInstaller hooks for
3.14 are less battle-tested than for 3.12. **Consider pinning the bundled runtime
to 3.12** — nothing in this codebase needs 3.13+ syntax, and the hook ecosystem
is more mature there.

**Bundling difficulty, package by package:**

| Package | Risk | Mitigation |
|---|---|---|
| `numpy` | Low | Mature PyInstaller hook. |
| `scipy` | **Medium** | Ships hundreds of extension modules and data files; the stock hook usually handles it but the bundle is large. Verify `scipy.ndimage` specifically survives. |
| `trimesh` | **Medium** | Pure Python but **lazy-imports** its optional deps. PyInstaller's static analysis will miss them. Needs explicit `--hidden-import scipy.ndimage` (and `--hidden-import scipy.sparse` if `_to_dense` ever hits the sparse path). |
| `pywin32` | **Medium** | `win32com.client.dynamic` uses runtime dispatch; the `win32com` package needs its `gen_py` handling configured. **Critically, the code deliberately avoids early binding** ("early binding (gencache) breaks OpenDoc on Student Edition") — good news for packaging, since gencache is the part that breaks under PyInstaller. |
| `openpyxl` | Low | Pure Python. |
| Flask/FastAPI | Low | Well-trodden. |

**Estimated size.** From measured wheel sizes and typical 2.5–3× expansion:

| Component | Installed |
|---|---|
| CPython runtime + stdlib | ~30 MB |
| numpy | ~40 MB |
| scipy | ~120 MB |
| pywin32 | ~25 MB |
| trimesh + openpyxl + web framework | ~5 MB |
| **PyInstaller onedir total** | **250–400 MB** |
| **PyInstaller onefile (compressed)** | **~130–180 MB**, with a 5–15 s first-launch unpack |

Both are fine for a desktop install. The spec's "several hundred MB" guess is
accurate.

### 4.4 Recommendation: **Strategy A — bundle the runtime**

Reasoning, in order of weight:

1. **Strategy B cannot detect the dependency that matters.** As established
   above, `scipy` is invisible to import-scanning and its absence is silent and
   grade-corrupting. A guided installer that runs `pip install trimesh numpy` —
   the natural conclusion from reading this codebase — produces a system that
   reports success and grades everyone at 0 on shape. Strategy B converts a
   packaging problem into a wrong-grades problem.
2. **The set is small and every piece has a Windows wheel.** Five packages, four
   compiled, all with `cp314` (and `cp312`) win_amd64 wheels. This is an easy
   bundle by PyInstaller standards. The spec's stated worry — "the build may be
   finicky" — is warranted for scipy but is a one-time developer cost, not a
   per-instructor risk.
3. **Strategy B needs a working Python on the instructor's machine**, and a
   silent `pip install` needs network access through whatever the university
   proxies, plus possible elevation. Each is a support call. The whole point of
   §2 is that there are no support calls.
4. Size is not a real constraint. 300 MB is smaller than SolidWorks by three
   orders of magnitude, and the machine already has SolidWorks.

**Conditions on the recommendation:**

- Pin every dependency in a lockfile. The absence of one today is why this
  question is open at all.
- Add `--hidden-import scipy.ndimage` and verify the frozen binary, not the dev
  environment.
- **Ship a startup self-test** and make it part of the §3 "System Ready"
  indicator: compare the bundled sample part (`test_underdefined.SLDPRT`) against
  itself and assert the shape score is 1.0. This catches the scipy failure, a
  broken trimesh bundle, and any future silent-zero regression in one cheap
  check. Without this, Strategy A merely moves the failure from the instructor's
  machine to the build machine.
- Consider pinning to Python 3.12 rather than 3.14 for hook maturity.

---

## Phase 5 — Spec Reconciliation

Legend: **EXISTS** · **PARTIAL** · **BUILD** (from scratch) · **WRONG** (spec is
incorrect or infeasible).

### §1 Platform & Runtime

| Item | Status | Notes |
|---|---|---|
| Windows only | EXISTS | Hard requirement of pywin32 + COM. |
| **CAD target "SolidWorks 2026"** | **WRONG (needs correction)** | Every logged connection reports `ApplicationType=1` = **Student Edition**. All magic constants (`SummaryInfo` indices, DISPID 7/48, `GetMassProperties` as a property) were derived on Student Edition. The spec should read "validated against SolidWorks Student Edition; Desktop unverified" until someone runs the diag scripts on a Desktop install. |
| Flask/FastAPI + HTML front end | BUILD | Nothing exists. |
| Single `.exe` | BUILD | See Phase 4. |
| §1.1 silent launch, no console | BUILD | Note: `grade_assignment.py` communicates exclusively via `print()`, including box-drawing and emoji. All of it must be replaced with structured progress events. |
| §1.1.4 **[VERIFY] port in use** | **BUILD** — nothing in the repo bears on this. Standard resolution: `SO_REUSEADDR`-free bind attempt on a fixed port; on `EADDRINUSE`, probe `/healthz` — if it answers with the app's own signature, open the browser at that port and exit; otherwise increment. Recommend a fixed default (e.g. 8731) so the URL is stable and bookmarkable. |
| §1.2 graceful shutdown | PARTIAL | `sw_connection.disconnect()`, `close_all_docs()` and `reset_connection()` exist and are the right primitives. Note `disconnect()` deliberately never calls `CoUninitialize()`; on process exit that is fine. |

### §2 Dependency Management

**Resolved.** See Phase 4. Recommendation: **Strategy A**, with a mandatory
self-test. §2.2 (check on every launch, block grading if unsatisfied) is BUILD,
and the self-test above should be part of that gate.

### §3 System Status Indicator

| Item | Status | Notes |
|---|---|---|
| Python row | BUILD | |
| SolidWorks version display | PARTIAL | `solidworks_health_check()` returns `version` (from `RevisionNumber`) and `application_type_label`. Note `RevisionNumber` is a build number like `34.x`, not "2026" — a mapping table is needed. |
| Edition caveat, non-blocking | PARTIAL | `application_type_label` already distinguishes Desktop / Student Edition / 3DExperience. **Reframe the caveat around *edition*, not year** — that is where the actual risk lives. |
| "No SolidWorks found" | **WRONG / BUILD** | **`solidworks_health_check()` cannot detect "not installed" or "not running."** It calls `win32com.client.dynamic.Dispatch`, which is `CoCreateInstance` — for a registered local server that **launches SolidWorks** if it is not running, then reports `running: True`. Despite the docstrings and log lines saying "GetActiveObject", that function is never called anywhere in the repo (grep confirms: it appears only in comments and log strings), and "Launching new SolidWorks instance" never appears in either log — consistent with Dispatch always succeeding. **To build §3 you need a real detector:** `pythoncom.GetActiveObject("SldWorks.Application")` for running-state, and a registry probe (`HKLM\SOFTWARE\SolidWorks`) or `CLSIDToProgID`/`LocalServer32` lookup for installed-state. Neither exists. *Confidence: high on the code reading; the COM activation semantics should be confirmed on the machine — it is a two-minute test.* |
| **Launch SolidWorks** button + auto-poll | PARTIAL | The polling primitive exists (`_is_sw_alive`). The launch is accidental today — `_try_create()` does the same `Dispatch` and additionally sets `Visible`. Needs to become deliberate. |

### §4 Information Architecture / §4.1 Scope tabs

**BUILD.** No UI exists. Assemblies and Drawings: correctly deferred — every
reader in `tool_*.py` hardcodes `swDocPART = 1`.

### §5 Home Screen — **BUILD** entirely.

Note §5.1's "results file moved" error is a real scenario today: `grade_assignment`
writes results to a `--output` folder with no registry of past runs.

### §6 Assignments

| Item | Status | Notes |
|---|---|---|
| §6.1 creation flow | BUILD | No assignment entity exists. Today an "assignment" is a `--assignment` string used as a filename prefix. |
| §6.1 **[VERIFY] class section required?** | **Unresolvable from code** — no roster concept exists anywhere. Human decision; see Phase 7, Q3. My recommendation: **required**, because §9.5 blocks the run until every active roster student is matched or marked missing, which is impossible without a section. |
| §6.2 point defaults | BUILD | Both graders hardcode a 100-point scale (`* 100` in `compute_grade`). Per-part point values do not exist. |
| §6.3 part editor | BUILD | Drawing files and reference images have no representation. |
| §6.4 **[VERIFY] thumbnails** | **Spec route is WRONG.** *Measured:* `test_underdefined.SLDPRT` starts `99 01 9f 76`, **not** the OLE signature `d0 cf 11 e0 a1 b1 1a e1`. Modern (2015+) SLDPRT is a proprietary container, not an OLE compound document, so **there is no compound-document preview stream to read.** I scanned the whole file for PNG/JPEG/BMP/GIF signatures — none. The only compressed stream (17 KB zlib at offset 10766) decodes to a non-image payload. **Remaining options, in order:** (1) **SolidWorks Document Manager SDK** — `ISwDMDocument.GetPreviewPNG`, works without opening SolidWorks and is the right answer, but requires a **separately licensed DM key from Dassault** and the `dm_connection.py` referenced in `sw_connection.py:21` **does not exist**; (2) render the STL the pipeline already exports — free, consistent, and the solution STL is produced anyway during grading; (3) generic placeholder. **Recommendation: (2).** It costs nothing extra, works on every edition, and needs no license. Drop the DM SDK unless the license is already owned. *Caveat: I cannot distinguish "this file has no preview" from "this file's preview is in a format I did not recognise" — but the container format finding alone kills the spec's stated approach.* |
| §6.5 export/import zip | BUILD | |

### §7 Grading Criteria

| Item | Status | Notes |
|---|---|---|
| §7.1 three-tier inheritance | BUILD | **Nothing configurable exists.** Weights and thresholds are module constants in two files, edited by hand, and they **disagree** (`VOXEL_RES` 64 vs 24). |
| §7.2 **[VERIFY] enumerate real checks** | **RESOLVED — see Phase 3.** The spec's four rows are the right four. Corrections to the table: |

| Check | Real threshold parameter | Real unit | Current default | Recommendation |
|---|---|---|---|---|
| Shape comparison | min IoU | dimensionless 0–1 | `SHAPE_THRESHOLD = 0.95` | Keep 0.95 **only at `VOXEL_RES=64`**; the noise floor at res 24 is ~3 %. Expose resolution as a criteria field with 64 as the floor, not the ceiling. |
| Mass properties | volume tolerance, **fractional not percent** | `VOLUME_TOLERANCE` compares `abs(vol-sol)/sol` — so `0.01` means ±1 % | `0.01` | Fine. Label it "±1 %" in the UI, store it as a fraction. **Note the spec says "mass properties" but the code checks volume only** — mass is read and never compared. |
| Material | exact case-insensitive string match on material name | string | no tolerance | Brittle: "Brass" vs "Brass, Soft Yellow" fails. Consider a configurable allow-list per part. |
| Sketch definition | count of underdefined allowed | integer | implicitly **0** — `sketches_ok = (count == 0)` | Make the allowance configurable as §7.2 says; today it is hardcoded all-or-nothing. |
| **(missing from spec)** plagiarism | none — any shared "author" flags | — | always on | Should be a toggleable check with its own weight per §7.2. |

Also note the current rubric is **not** a weighted average of independent checks
— `compute_grade` couples volume and shape (`shape_credit` is boosted to 1.0 only
if `volume_ok`). Spec §7.2's "each check has a weight" model does not describe the
existing behaviour. Either the coupling is preserved as a named rule or it is
dropped; it cannot be expressed in a flat weight table. **Human decision.**

| §7.3 JSON criteria config | BUILD | Nothing to adopt (§15.11 answered: no config formats exist). |

### §8 Class Sections — **BUILD** entirely.

No roster concept exists at any layer. The Firebase path used Auth UIDs as
identity, which does not transfer. §8.3 CSV column-mapping: no prior art.

### §9 Submission Ingestion & Roster Matching

| Item | Status | Notes |
|---|---|---|
| §9.1 structure auto-detection | PARTIAL — weakly | `grade_midterm.find_problem_folders()` handles the **by-problem** layout (regex for a trailing digit on directory names). `canvas_reorganizer.guess_problem_number()` is the real prior art: it recognises 4-digit codes with a base offset, short codes (`MT1`,`P2`,`Q1`,`HW3`), and plain numbers. **Port that function.** Nothing detects flat or by-student layouts. |
| §9.2 extension filtering | PARTIAL | Both graders glob `*.SLDPRT` / `*.sldprt` with case-insensitive dedup. **Nothing reports what was ignored** — §9.2's "display the ignored set" is BUILD. |
| §9.3 duplicate resolution | **BUILD, and urgently** | Today's behaviour is worse than absent. `grade_assignment` dedups by lowercased *filename*, keeping the first. `grading_agent` skips copying a name that already exists **but overwrites the identity-map entry anyway** — so with two `Part1.SLDPRT`, student A's geometry is graded under student B's name. `canvas_reorganizer.strip_chrome_duplicate_suffix()` exists and is the right seed for handling Canvas `-2` suffixes. "Most recent" resolution needs mtime or the `last_saved_date` the metadata reader already captures. |
| §9.4 matching signals | PARTIAL | Signal 1 (filename tokens): `extract_username()` — `stem.split('-')[0]` — is the entire implementation. It works on `Baik.Ellen-Quiz3-1.SLDPRT` and fails completely on Canvas-mangled names: in the agent log it yielded `BSsFnYZm46NmhXoAvysz_1774142755760_Baik.Ellen`. Signal 2 (parent folder): only in `grading_agent` (folder = Firebase UID). Signal 3 (metadata author): available, **but see §3.3 — it is "last saved by", and ~25 % of field values are personal-machine names.** Signal 4 (fuzzy): does not exist. No confidence score exists. |
| §9.5 pre-flight review + blocking | BUILD | **This is the single largest and most valuable piece of new work**, and the spec is right to call it the highest-risk subsystem. |
| §9.6 LLM-assisted detection | BUILD | Reasonable as a stretch. Note the folder listing is the only input needed, so it is cheap and offline-safe to defer. |
| §9.7 normalization | BUILD | |

### §10 Run Grading Wizard

Steps 1–4 and 6: **BUILD**. Step 5 (SolidWorks live check): **PARTIAL** — the
health-check function exists but cannot distinguish not-installed from
not-running (see §3 above).

**§10.4 [VERIFY] should run-time criteria changes persist back to the
assignment?** Not resolvable from code — no criteria persistence exists. **Human
decision** (Phase 7, Q4). Recommendation: **apply to the run only, and record the
effective criteria inside the run's result record** (the existing JSON already
does exactly this: `rubric` and `thresholds` are embedded per run). That makes
every historical result self-describing and reproducible, which matters when an
instructor is defending a grade. Offer an explicit "save these as the assignment
default" button rather than implicit write-back.

### §11 Run Resilience & Resume

| Item | Status | Notes |
|---|---|---|
| §11.1 checkpointing | **BUILD — nothing exists.** | Results are written **only after all students complete** (Phase 3 of `grade_assignment`). A crash at student 19 of 20 loses everything. At ~60 s/file this is a 20-minute loss on a small assignment and over an hour on a midterm. |
| §11.2 resume / retry / start fresh | BUILD | Beware: the current code **overwrites the student's exported STL with a PCA-normalized version** after comparison (`save_viewer_stls` at the end of the loop writes to the same `student_stl_dest` the mesh was loaded from). Re-running over an existing output folder therefore re-normalizes an already-normalized mesh. **Any resume implementation must not treat the output folder as idempotent** until this is fixed. |
| §11.3 **[VERIFY] is continuous polling needed?** | **RESOLVED: the spec's assumption does not hold. A heartbeat or a timeout is required.** The reasoning in §11.3 depends on the COM layer failing fast. It does not: **`open_part_silent()` accepts a `timeout` parameter, documents "Raises SWTimeoutError if SW stalls during open", and then never uses it** — the parameter is dead, and the function calls straight through to `_open_part_silent_inner`. `sw_timeout.py` implements exactly the needed wrapper and is **imported by nothing** (a stale `.pyc` shows it was wired in once and removed). So a hung COM call blocks the grading thread forever with no timer anywhere. `recover_from_stall()` does use a threaded ping with a timeout — but it is only reachable from the `except` branch, which a hang never reaches. **Cheapest fix, and it is genuinely cheap: wrap every COM entry point in `with_timeout(...)`, which already exists.** Then §11.3's optimism becomes true and no heartbeat is needed. |

### §12 Results View

| Item | Status | Notes |
|---|---|---|
| §12.1–12.3 table, pivots, pass/flag | PARTIAL (data only) | The `needs_review` flag already implements §12.3's core semantic, and `grade_midterm`'s xlsx Overview sheet is a working prototype of the §12.1 student × problem grid with exactly the ✓ / ⚠ / ⚑ / — vocabulary. **Reuse that design language.** No web UI exists. |
| §12.4 overrides | PARTIAL (schema only) | `grade_assignment.py`'s **docstring** specifies `override`, `override_note`, `override_by` and the code emits those keys as `None` — but nothing ever reads or writes them, and the committed `output/Quiz3_grades.json` does not contain them at all. The schema is aspirational. Retaining the original computed value (§12.4) is not designed for; add an explicit `computed` vs `override` pair rather than mutating in place. |
| §12.5 notes | BUILD | |
| §12.6 **[VERIFY] student files after the run** | **RESOLVED — keep a path reference, and fix the read-only problem first.** The tension the spec worries about is smaller than a problem it does not mention: **student files are already opened read-write.** `open_part_silent` tries four strategies in order, and only strategy 3 (`OpenDoc6`) passes `swOpenDocOptions_ReadOnly`. Strategy 1 is a bare `OpenDoc(path, 1)` — no flags, no read-only — and the log shows it succeeding routinely. Combined with `ForceRebuild3` on every file and a `SaveAs` during export, the app is touching student submissions with a writable handle. **Resolve §12.6 by:** (a) reordering the open strategies so `OpenDoc6` with `Silent\|ReadOnly` is tried **first** — `close_doc` already hard-refuses `save=True`, so the intent is clearly there; (b) storing the **absolute source path** in the result record and opening from it on demand, with a graceful "file moved" message. Do **not** cache copies: it multiplies the FERPA surface for no functional gain, and §13's rule is worth keeping. |
| §12.7 **[VERIFY] is xlsx export still needed?** | **Partially resolvable.** `grade_midterm.py` already produces a rich two-sheet formatted workbook via `openpyxl`, and `output/MT26_grades.xlsx` shows it was used. That is a *human-readable report*, not an LMS import file — and its value (the colour-coded grid) is exactly what §12.1 replaces in-browser. **The Canvas grade-import format is not determinable from this repo**: `canvas_clicker.py` enters grades by *clicking buttons in SpeedGrader*, which is strong evidence that no working CSV import path was ever established. **Recommendation: ship CSV, drop xlsx, and treat "what Canvas actually accepts" as a human question** (Phase 7, Q5) — the answer is a specific column layout that must be obtained from the instructor's Canvas instance, not guessed. Dropping `openpyxl` also removes a dependency. |

### §13 App-Managed Storage — **BUILD** entirely.

Today every path is a CLI argument or a hardcoded absolute path. Two notes:
(a) the "never permanently store submissions" rule is currently violated in
spirit by `grading_agent.py`, which calls `blob.make_public()` on every uploaded
STL and results JSON — **student names and grades were published to
world-readable URLs**; this is a good reason to keep the desktop app off the
network entirely. (b) "results rendering must never require Excel" is already
half-true — the JSON path is complete; only `grade_midterm` is Excel-bound.

### §14 Reuse From Existing Code Base — item by item

| Spec claim | Reality |
|---|---|
| COM connect / silent open / close / health check / stall recovery | **EXISTS** (`sw_connection.py`). Caveats: "silent" is only true on the 3rd open strategy; "health check" cannot detect not-running; "stall recovery" is unreachable from a real stall. |
| Author / dates / custom properties reader | **EXISTS** (`tool_metadata.py`). "Author" is really "last saved by". |
| Mass, volume, surface area, CoM, density, material reader | **EXISTS** (`tool_mass.py`). Fully functional; more is read than is used. |
| STL export + PCA-normalized voxel IoU | **EXISTS** (`tool_export.py`, `tool_compare.py`). Scale-blind by design; broken on symmetric parts; silently zero without scipy. |
| Sketch constraint status reader | **EXISTS** (`tool_sketch.py`). Fragile raw-DISPID probe; fails open. |
| STL / STEP / IGES export | **EXISTS**. STEP/IGES untested — no caller. |
| Popup dismisser | **EXISTS** and is load-bearing (76 dismissals in one log). |
| Timeout wrapper for stalling COM calls | **EXISTS AS A FILE, WIRED TO NOTHING.** Spec §14 implies it is in use. It is not. |
| Current MCP server exposing the above | **EXISTS** (`server.py`). |

**§14.1 (= §15.7) key architectural question — RESOLVED.** The coupling is
already minimal; see Phase 2.3. No extraction is required. The real refactor is
different from the one the spec anticipates: it is **collapsing the three
duplicated batch-grading loops into one and lifting the rubric constants into
configuration.**

### §15 Open Questions — status

| # | Question | Answer |
|---|---|---|
| 1 | Bundle vs detect-and-install | **Answered — Strategy A.** Phase 4.4. |
| 2 | Complete dependency list | **Answered.** Phase 4.1. 5 core packages; `scipy` is undeclared and mandatory. |
| 3 | SolidWorks thumbnail extraction | **Answered — spec's route is dead.** Not an OLE file. Use STL render. §6.4 above. |
| 4 | Batch orchestration files | **Answered.** `grade_assignment.py` (single-problem) and `grade_midterm.py` (multi-problem) both exist and work; `diag_batch.py` is their ancestor. All three duplicate each other. |
| 5 | Canvas-scraping logic — keep or supersede? | **Mostly superseded, but salvage two functions.** The Selenium download/click layer is out of scope for a local desktop app (needs Chrome + ChromeDriver + interactive login, and `canvas_clicker` writes grades back by clicking buttons — a separate product). But `canvas_reorganizer.guess_problem_number()` and `strip_chrome_duplicate_suffix()` are directly the §9.1/§9.3 logic and should be ported. |
| 6 | Reusable web/cloud front end? | **Answered — none, decouple fully.** Phase 2.6. Salvage the results JSON schema only. |
| 7 | Extracting tools from MCP | **Answered — already separate.** Phase 2.3. |
| 8 | DISPID / index-order reliability across editions | **Partially answered.** `GetMassProperties` ordering is standard, not edition-specific — low risk. `SummaryInfo` index 5 is a real semantic error, not an edition quirk. **DISPID 7/48 is the genuine edition risk** and it fails *open* (Phase 3.4). All evidence is from Student Edition; nothing is known about Desktop. Needs a run of `diag_props.py`/`diag_sketch.py` on a Desktop machine. |
| 9 | Is the popup dismisser still needed? | **Answered — yes, absolutely, on Student Edition.** It fired 76 times in one agent log, once per file open, on the "SOLIDWORKS Design" `#32770` dialog. Packaging concerns: Phase 6, R-5. Whether Desktop Edition raises the same dialog is **unknown** — the "educational use only" nag is Student-specific, so on Desktop the dismisser may become optional. Keep it either way; it also catches "newer version"/"older version" prompts. |
| 10 | Can grading be parallelized? | **Answered — no, not across SolidWorks.** Phase 6, R-6. |
| 11 | Existing config file formats | **Answered — there are none.** No requirements.txt, pyproject, ini, yaml, or app config anywhere. Clean slate. |
| 12 | Realistic per-file grading time | **Answered — 33–97 s, median ~60 s, and it degrades.** Phase 6, R-7. |

---

## Phase 6 — Risk Register

Ordered by severity. The first three can produce wrong grades that nobody notices.

### R-1 · CRITICAL · Silent wrong grades: three paths where a failure scores as a result

The system's design philosophy is "catch every exception, return a default,
continue." For a batch grader that is exactly backwards: a swallowed exception
becomes a number in a gradebook.

| Path | Trigger | Result | Evidence |
|---|---|---|---|
| **`scipy` absent** | Any environment where trimesh is installed without the `easy` extra | **Every** shape score is `0.0`; `method` still says `"normalized_pca_iou"`; `error` is `null` | **Measured** — I reproduced it |
| **DISPID 48 changes meaning** | A SolidWorks upgrade, or a different edition | Every sketch reads `UNKNOWN`; `UNKNOWN` is not `UNDERDEFINED`; `sketches_ok = True`; **every student gets the full 15 points** | Code reading, `tool_sketch.py:_get_sketch_status` |
| **Mass read fails** | Material unassigned, corrupt file, COM hiccup | `volume` is `None` → `volume_ok = False` → student loses 10 points **and** the shape-credit boost, indistinguishable from an actually-wrong volume | Code reading, `grade_assignment.py` volume check |

**Why it's risky:** the output looks identical to a correct run. There is no
"this check did not execute" state anywhere in the schema — every check is
boolean, and failure collapses into `False` (or, worse, `True`).

**What de-risks it:**
- Add a third state to every check: `pass` / `fail` / **`not_evaluated`**, and
  make `not_evaluated` force `needs_review` and *withhold* points rather than
  awarding or deducting them.
- Never let a swallowed exception produce a score. `_voxel_iou`'s
  `except Exception: return 0.0` must return `None`.
- Ship the startup self-test from Phase 4.4 (identical part must score 1.0).
- Make `UNKNOWN` sketch status count as `not_evaluated`, not as passing.

### R-2 · CRITICAL · Wrong-student attribution

Three independent mechanisms swap or mangle identity:

1. **Filename collision overwrites identity** (`grading_agent.py:309–323`): the
   file copy is skipped if the name exists, but `student_identity_map[name]` is
   assigned unconditionally. Two `Part1.SLDPRT` submissions → one graded, both
   attributed to the second student. **The spec's §9.1 "flat folder" is this
   scenario by definition.**
2. **`extract_username` is a single `split('-')[0]`**. On the real Canvas-derived
   names in the agent log it produced `BSsFnYZm46NmhXoAvysz_1774142755760_Baik.Ellen`
   — which then became the STL filename and the plagiarism-map key.
3. **Wrong-solution matching** (`grade_midterm.find_solution_file`): if the exact
   `SE0000230N.SLDPRT` is absent, it falls back to `re.search(rf'0*{n}$', stem)`.
   For problem 1 that pattern matches `SE00002311` (problem 11). **An entire
   problem's cohort silently graded against the wrong solution**, with no error —
   every student would just score badly and look like they failed.

**What de-risks it:** §9.5's blocking pre-flight review is the correct answer and
should be built first. Additionally: make attribution a hard key (student ID +
part), never a derived string; make solution lookup exact-match-or-fail with no
regex fallback; hash file contents to detect true duplicates.

### R-3 · HIGH · Student files are opened read-write and modified

`open_part_silent` tries `OpenDoc(path, 1)` **first** — no options, no read-only
flag. Only the third fallback (`OpenDoc6`) passes `swOpenDocOptions_Silent |
swOpenDocOptions_ReadOnly`, and the log shows the first strategy succeeding
routinely. Every file then gets `ForceRebuild3(False)` and a `SaveAs` during STL
export.

**Why it's risky:** this is a graded artifact and potentially an academic-integrity
exhibit. A rebuild can change stored geometry state; a crash mid-operation with a
writable handle can corrupt a submission the student cannot resubmit. The
codebase clearly *intends* read-only — `close_doc` raises `ValueError` on
`save=True` with the comment "student files must never be modified" — the open
path just doesn't honour it. The field data shows the risk is not theoretical:
`Kondo.Rachel-Quiz3-1.SLDPRT` has a `last_saved_date` of 2026-03-14 and
`sw_author: GCE4` — that file was saved by the instructor's account after
submission.

**What de-risks it:** reorder the strategies (`OpenDoc6` with `Silent|ReadOnly`
first); copy each submission to a scratch directory and grade the copy, never the
original; set the copy read-only on the filesystem.

### R-4 · HIGH · No checkpointing under a 60–100 minute run

Results are written only after the final student. Any interruption — SolidWorks
crash, sleep, accidental close — loses the entire run. At the measured rate a
midterm is 60–100 minutes of exposure with a single point of failure at the end.

**What de-risks it:** §11.1's per-student append-only checkpoint file, written
after each file. This is a small piece of work with a very high payoff and should
land before any UI polish. Watch the STL-overwrite idempotency problem noted in
§11.2 above.

### R-5 · HIGH · The popup dismisser in a packaged, non-interactive context

**It is required.** 76 dismissals in one agent log, one per file open, on the
Student Edition "SOLIDWORKS Design" `#32770` dialog. Without it every open blocks
forever — and since nothing has a timeout (R-8), forever means forever.

**Why packaging makes it riskier:**
- It calls `EnumWindows` every 150 ms across **all** top-level windows and clicks
  any `Button` whose text is `Yes` or `OK` inside a window whose title contains
  `"solidworks"`. The rule list includes a bare `("solidworks", "#32770", ["Yes","OK"])`
  catch-all. **It will click "Yes" on a SolidWorks dialog it was never meant to
  answer** — including, plausibly, a "Save changes?" prompt on a student file.
  Given R-3, that is a data-loss path.
- Windows' UIPI blocks `SendMessage` across integrity levels. If the packaged
  `.exe` runs at a different elevation than SolidWorks, **the dismisser silently
  stops working** — `EnumWindows` still enumerates, the click just does nothing,
  and the log shows no dismissals. First symptom is an unexplained hang.
- It is a `daemon` thread doing GUI work with no window message pump of its own —
  fine today, but PyInstaller's bootloader and any tray-icon work later share
  that space.

**What de-risks it:** narrow the rules to exact known titles and remove the
`["Yes", "OK"]` catch-all — enumerate specific dialogs and log-and-skip anything
unrecognised; assert integrity-level parity at startup and surface a clear error
if the app and SolidWorks differ; count dismissals and alert if a file open takes
> N seconds with zero dismissals (that is the UIPI failure signature).

### R-6 · HIGH · SolidWorks cannot be parallelized — and one file already tries

**Answer to §15.10: strict serialization.** SolidWorks' COM interface is a
single-threaded-apartment automation server with one global `ActiveDoc`. The
pipeline's whole structure — one connection singleton, `close_doc` by path,
`GetUserPreferenceDoubleValue` mutated globally for STL quality — assumes one
operation at a time.

**`server.py`'s `grading_batch` violates this today.** It spawns three threads
that all call methods on the same `doc` COM pointer, none of which calls
`CoInitialize`, and its docstring asserts *"These are all read-only calls on an
already-open document, safe to parallelize."* That is not how COM apartments
work: a raw dispatch pointer used from a foreign thread without marshalling
yields `RPC_E_WRONGTHREAD` at best. Worse, each thread's `join(timeout=30)`
returns on timeout and the code then reads a **partially populated** result dict
— which is truthy, so it is reported as complete data. `server_additions.py`
contains the earlier, correct, sequential version of exactly this function.

**What is parallelizable:** the pure-Python half. Mesh normalization and voxel IoU
touch no COM and account for a large share of the ~60 s. A producer/consumer
split — one serialized SolidWorks thread exporting STLs, a worker pool doing
comparisons — is safe and could roughly halve wall time. That is the only
parallelism worth pursuing.

**What de-risks it:** delete the threading from `server.py`'s `grading_batch`
(or replace the file's version with `server_additions.py`'s); confine all COM to
one dedicated thread with an explicit `CoInitialize`; parallelize only downstream
of the STL.

### R-7 · MEDIUM-HIGH · SolidWorks degrades under sustained load

**Measured, from `grading_agent.log`,** nine consecutive jobs grading the same
5–6 files:

| Job | Students | Wall time | Per file |
|---|---|---|---|
| 1 | 5 | 2 m 45 s | 33 s |
| 2 | 5 | 2 m 47 s | 33 s |
| 3 | 5 | 4 m 07 s | 49 s |
| 4 | 5 | 4 m 52 s | 58 s |
| 5 | 5 | 4 m 28 s | 54 s |
| 6 | 5 | 5 m 35 s | 67 s |
| 7 | 5 | 7 m 07 s | 85 s |
| 8 | 5 | 8 m 06 s | 97 s |
| 9 | 6 | 6 m 52 s | 69 s |

**Per-file time roughly tripled over ~90 minutes on identical inputs.** The
SolidWorks process persists across jobs (the connection singleton is never reset
between them), so this is consistent with accumulating documents, handles or
memory inside SolidWorks. `grade_assignment` calls `gc.collect()` per student —
Python-side, which does not help. `diag_batch.py` additionally sweeps for leaked
open documents after each student; **that sweep did not survive into
`grade_assignment.py`.**

**Why it's risky:** a full midterm is 80+ files. If the trend holds, the last
files take 3× the first, and the run stretches from an estimated 45 minutes to
over 2 hours — which then interacts with R-4 (no checkpoints).

**What de-risks it:** port `diag_batch.py`'s leaked-document sweep back in; call
`close_all_docs()` periodically; consider recycling the SolidWorks process every
N files (kill and reconnect) — with checkpointing in place this is cheap;
instrument per-file duration and surface the trend in the progress UI.
*Confidence: medium-high. The correlation is strong and monotonic but I cannot
rule out an external cause on that machine, e.g. Firebase upload contention.
Reproduce with a single 40-file run before committing to process recycling.*

### R-8 · MEDIUM-HIGH · No timeout anywhere in the production path

Covered under §11.3 above. `open_part_silent`'s `timeout` parameter is documented
and ignored; `sw_timeout.with_timeout` exists and is imported by nothing. A stalled
COM call hangs the run indefinitely, and `recover_from_stall()` is unreachable
because it only runs from an `except` branch a hang never reaches.

**What de-risks it:** wire up the module that already exists. This is close to a
one-line-per-call-site change and it converts an indefinite hang into a failed
item — which is precisely what §11.3 assumes is already true.

### R-9 · MEDIUM · Shape scoring is wrong for symmetric parts

Measured: a cube rotated 45° scores **0.364**. See Phase 3.1. Intro CAD
assignments are full of prisms and symmetric solids.

**What de-risks it:** extend the flip search to all 24 axis permutations × signs;
detect near-degenerate PCA eigenvalues (ratio within a few percent) and mark the
result low-confidence, forcing manual review; consider a rotationally invariant
descriptor as a cross-check.

### R-10 · MEDIUM · Rubric constants duplicated and divergent

`VOXEL_RES` is 64 in `grade_assignment.py` and 24 in `grade_midterm.py`. Given the
measured noise floor (≈0.8 % at 64, ≈3 % at 24) **the same submission gets
materially different shape scores depending on which script graded it**, and at
res 24 the 0.95 threshold is barely above noise. Weights and thresholds are
likewise duplicated.

**What de-risks it:** §7's criteria object, with resolution as a first-class
field and a hard floor of 64.

### R-11 · MEDIUM · Plagiarism check is untested and mis-specified

Never fired on real data (24/24 distinct authors in the only dataset). The
self-exclusion bug (Phase 3.5) means a flagged student is listed as their own
partner. And with "author" meaning "last saved by", a lab-machine cohort under a
shared login is a mass false positive.

**What de-risks it:** build a fixture with known duplicates before shipping;
rename the field to `last_saved_by` throughout; treat it as a *review prompt*,
never an accusation, and make that language explicit in the UI.

### R-12 · MEDIUM · Global SolidWorks preference mutation

`tool_export._set_stl_quality` writes `swSTLDeviation` and `swSTLAngleTolerance`
into the user's SolidWorks preferences and restores them in a `finally`. A crash
or kill between set and restore **leaves the instructor's SolidWorks configured at
grading tolerances permanently**, affecting their own modelling work. It is also a
correctness risk: if two operations interleave, one restores the other's values.

**What de-risks it:** restore in a process-level `atexit` as well as the `finally`;
persist the original values to disk before mutating so they can be recovered
after a crash.

### R-13 · MEDIUM · Credential exposure (already occurred)

The GCP service-account private key is in git history at `1e619e9`. Separately,
`grading_agent.py` calls `blob.make_public()` on every uploaded STL and on the
results JSON — **student names, filenames and grades were published to
world-readable Google Storage URLs**, several of which are recorded verbatim in
the committed `grading_agent.log`.

**What de-risks it:** rotate the key now; treat the log files as containing
student data and remove them from version control; the desktop app's fully-local
architecture eliminates this class of risk going forward, which is a strong
independent argument for the direction the spec takes.

### R-14 · LOW-MEDIUM · Python 3.14 on the packaging frontier

See Phase 4.3. Wheels exist; hooks are young. Pin to 3.12 unless something needs
otherwise.

### R-15 · LOW · `print()`-based progress

Every grader communicates via `print()`, including box-drawing characters and
emoji. Under §1.1's "no console window, ever" all of it must become structured
events. Mechanical, but it touches every function and is easy to under-scope.
Note also that emoji in a Windows console requires a UTF-8 code page — a
latent `UnicodeEncodeError` on any machine that hasn't set one.

---

## Phase 7 — Open Questions for the Humans

Ordered by how much each blocks the build.

### Q1 · Is scale-blind shape comparison the intended rubric? — **BLOCKS §7**
**Why it matters:** *Measured* — a part modeled at 2× scale, or in inches instead
of millimetres, scores a perfect 1.0 on the 65-point shape check. Only the
10-point volume check catches it, and only at ±1 %. This is not a bug; it is a
documented design choice (`server.py` advertises it as a feature). But it decides
what the product is: a *form* checker or a *dimensional accuracy* checker. Every
threshold in §7.2 depends on the answer.
**Options:** (a) keep form-only, and rely on volume for scale — cheap, current
behaviour; (b) score form and scale separately, with independent weights — my
recommendation, since it makes "right shape, wrong size" legible to the instructor
instead of collapsing it into one number; (c) make it a per-assignment criteria
toggle, which is more work but fits §7's three-tier model naturally.

### Q2 · Will grading run on SolidWorks Desktop, Student Edition, or both? — **BLOCKS §3, gates all COM work**
**Why it matters:** every magic constant in this codebase — the `SummaryInfo`
indices, the DISPID 7→48 sketch probe, `GetMassProperties` being a property, the
four-strategy open ladder, the entire need for the popup dismisser — was derived
on **Student Edition**, and the logs confirm nothing else has ever been used. The
spec assumes SolidWorks 2026 Desktop. If Desktop is the target, all of it needs
re-validation, and some of it (the DISPID probe) may be replaceable with the
supported named API.
**Options:** (a) target Student Edition, matching reality, and treat Desktop as
uncertified; (b) target Desktop and budget a re-validation pass — run
`diag_props.py`, `diag_sketch.py`, `diag_mass.py`, `diag_export.py` on a Desktop
machine, roughly a day; (c) support both, with an edition-dispatch layer behind
each reader. **The diag scripts are exactly the right tool for (b) — this is
their remaining purpose.**

### Q3 · Is a Class Section required at assignment creation? — **BLOCKS §6.1, §8, §9**
**Why it matters:** §9.5's blocking gate ("every active roster student is either
matched or explicitly marked as missing") is unimplementable without a roster.
Making the section optional means building two ingestion modes.
**Options:** (a) required — simpler, one code path, and matches how the tool will
actually be used; (b) optional, with an "ungraded roster" fallback that matches
files to each other but not to people — meaningfully more work in the highest-risk
subsystem. **Recommend (a).**

### Q4 · Do run-time criteria changes persist back to the assignment? — **BLOCKS §10.4**
**Why it matters:** it determines whether a historical result can be reproduced.
**Options:** (a) run-only, with the effective criteria embedded in the result
record — the existing JSON already does this and it makes every past grade
self-explaining; (b) write back to the assignment, which silently re-interprets
older runs; (c) prompt each time. **Recommend (a) plus an explicit "save as
assignment default" button.**

### Q5 · What column format does the instructor's Canvas actually accept? — **BLOCKS §12.7**
**Why it matters:** the existing Canvas integration enters grades by *clicking
buttons in SpeedGrader* (`canvas_clicker.py`), which strongly suggests no working
CSV import path was ever established. The format is instance- and
assignment-specific and cannot be derived from this repository.
**Options:** (a) obtain one real Canvas gradebook export and match it — half an
hour of the instructor's time, and it settles whether `openpyxl` can be dropped;
(b) ship generic CSV and let the instructor paste; (c) keep the xlsx report as a
human-readable artifact separate from any LMS import.

### Q6 · Should the coupling between the volume and shape checks be preserved? — **BLOCKS §7.2**
**Why it matters:** `compute_grade` is not a weighted sum of independent checks.
Shape credit is rounded up to full only when volume is correct; otherwise the raw
IoU is used. §7.2's flat "each check has a weight" table cannot express this.
**Options:** (a) preserve it as a named, documented rule with its own UI
affordance; (b) drop it for a pure weighted sum — simpler and matches the spec,
but changes every historical grade; (c) make it a toggle. Note this rule is
currently what makes the scale-blindness survivable (Q1), so answer Q1 first.

### Q7 · How long may student files be referenced after a run? — **§12.6, §13**
**Why it matters:** §12.6's "open student submission in SolidWorks" needs the
file. My recommendation (path reference, graceful failure) is in Phase 5. But the
instructor should confirm the retention posture, particularly given that the
previous cloud version made student work world-readable (R-13).
**Options:** (a) path reference only, no copies — recommended; (b) cached copies
with an explicit expiry; (c) copies retained for the life of the assignment.

### Q8 · What happens to the Canvas download tooling? — **§9, product scope**
**Why it matters:** the four `canvas_*.py` scripts are ~75 KB of working
Selenium automation covering download *and* grade write-back. The spec's §9
assumes the instructor already has a folder of files, which supersedes the
downloader — but says nothing about grade write-back, which `canvas_clicker.py`
does today and which the instructor presumably still needs.
**Options:** (a) out of scope; instructor downloads manually, uploads grades
manually; (b) port only `guess_problem_number` / `strip_chrome_duplicate_suffix`
into ingestion and drop the rest — recommended, and it avoids bundling Chrome and
ChromeDriver; (c) keep Canvas automation as a separate companion tool.

### Q9 · What is the grading throughput requirement? — **§10.6, §11**
**Why it matters:** *measured* 33–97 s per file, degrading over a session
(R-7). A 20-student × 4-problem midterm is 60–100 minutes. If the instructor
expects to start a run and have results in ten minutes, the answer is a
producer/consumer split (R-6) and possibly a lower voxel resolution — which
directly degrades accuracy (R-10). This is an explicit accuracy/speed trade the
humans should make, not one that should be settled by a constant in a file.

### Q10 · Is the plagiarism check an accusation or a prompt? — **§7.2, §12.3**
**Why it matters:** it has never fired on real data, its underlying signal is
"last saved by" rather than "author", and shared lab logins will trigger it
en masse. The UI wording and whether it affects the score are policy questions
with real consequences for students.

---

## Appendix — What I could not determine

Stated explicitly, per the brief.

- **Anything requiring live COM.** Every claim about `OpenDoc` behaviour, DISPID
  values, `SummaryInfo` indices, `Dispatch` activation semantics and dialog
  behaviour is from code reading plus the committed logs. The highest-value
  confirmations, in order: (1) does `Dispatch("SldWorks.Application")` launch
  SolidWorks when it is not running (decides §3); (2) is `SummaryInfo(5)`
  last-saved-by or author (decides §9.4 weighting); (3) does the DISPID 7→48
  probe work on Desktop Edition. Each is a few minutes on the target machine.
- **Whether `test_underdefined.SLDPRT` contains a preview at all.** I established
  the container is not OLE and holds no recognisable image stream, which rules
  out the spec's approach — but I cannot distinguish "no preview saved" from "an
  encoding I did not recognise." The Document Manager SDK question is a licensing
  question, not a technical one.
- **Whether the R-7 slowdown is SolidWorks or the machine.** The correlation is
  strong and monotonic across nine jobs on identical inputs, but the runs also
  involved Firebase uploads. One clean 40-file local run would settle it.
- **STEP and IGES export.** Supported by `tool_export`; no caller and no evidence
  either was ever run.
- **`grade_midterm.py`'s current state.** `output/MT26_grades.xlsx` proves it ran
  successfully at some point, but its result schema (like Quiz3's) does not match
  today's code, so I cannot confirm the committed version is the one that
  produced it.
- **Overdefined and no-solution sketch statuses.** `tool_sketch.py` labels values
  1 and 0 as unconfirmed hypotheses. Only 2 and 3 have ground truth behind them.
