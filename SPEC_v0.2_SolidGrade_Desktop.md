# SolidGrade Desktop — Spec v0.2

**Supersedes:** `SPEC_v0.1_SolidGrade_Desktop.md`
**Basis:** v0.1 plus `DISCOVERY_REPORT.md`, plus three product decisions recorded
in §0.2.

**Purpose:** A local desktop application that lets an engineering instructor build
CAD assignments, ingest student submissions, run automated SolidWorks-based
grading checks, and review and override results — without ever touching a
terminal.

**Explicit non-goal:** This tool does not replace grading. It is a *triage* tool.
Its job is to confirm the submissions that are unambiguously correct so the
instructor never has to open them, and to surface everything else for manual
review.

**The governing principle of v0.2:** a check that did not run must never look like
a check that passed, and must never look like a check that failed. Discovery found
three separate paths that silently produce wrong grades. Everything in §15 exists
because of them, and §15 outranks every feature in this document.

---

## 0. Preconditions and Decisions

### 0.1 Immediate remediation — do before any build work

These are not build tasks. They are outstanding problems in the current repo.

1. **Rotate the Google Cloud service-account key.** The private key is live in git
   history at commit `1e619e9`. Deleting the file again does nothing; it must be
   revoked in the Google Cloud console.
2. **Audit and revoke public Storage URLs.** `grading_agent.py` called
   `blob.make_public()` on every results JSON and STL. Student names, filenames
   and grades were published to world-readable URLs, several recorded verbatim in
   the committed `grading_agent.log`.
3. **Remove `grading_agent.log` and `solidworks_mcp.log` from version control**
   and add a `.gitignore`. They contain student data.
4. **Delete the two junk files** `python` and `python test_firebase.py`.

### 0.2 Product decisions made after discovery

| # | Decision |
|---|---|
| **D1** | **Form and scale are scored separately.** Shape comparison no longer normalizes scale away silently. See §7.3. This supersedes v0.1 §7.2 and resolves the discovery report's Q1 and Q6. |
| **D2** | **Both SolidWorks editions are targets, and both require validation.** Student Edition is the only edition with evidence behind it. Desktop / 3DExperience is unvalidated. See §16. |
| **D3** | **Throughput must improve, but never by reducing accuracy.** Voxel resolution has a hard floor of 64 and is not a speed lever. Speed comes from §11.4. |

### 0.3 Decisions taken by default

Recorded here so they are visible and easy to reverse. Each was an open question
in the discovery report; each has a default chosen with its rationale.

| Q | Decision | Rationale |
|---|---|---|
| Class section required at assignment creation? | **Required** | §9.6's blocking gate is unimplementable without a roster. One code path instead of two, in the highest-risk subsystem. |
| Do run-time criteria changes persist to the assignment? | **Run-only**, with effective criteria embedded in the result record, plus an explicit *Save as assignment default* button | Makes every historical grade self-describing and reproducible. Matters when defending a grade. |
| Excel export? | **Drop it. CSV only.** | The xlsx was a human-readable report, which §12 replaces in-browser. Removes `openpyxl`. Canvas import format remains open — §17.1. |
| Student file retention after a run? | **Absolute path reference only. No copies retained.** | Keeps the FERPA surface minimal. §12.6. |
| Canvas Selenium tooling? | **Out of scope.** Port two functions, drop the rest. | Avoids bundling Chrome and ChromeDriver. §9.2. |
| Plagiarism check framing? | **A review prompt, never an accusation.** | The signal is weaker than v0.1 assumed. §7.7. |

---

## 1. Platform & Runtime

| Decision | Value |
|---|---|
| OS | Windows only |
| CAD target | SolidWorks **Student Edition and Desktop / 3DExperience**, per D2 — see §16 |
| Architecture | Local Python web server (Flask or FastAPI) + HTML/CSS/JS front end |
| Client | User's default browser at `localhost:8731` |
| Network | **None.** No outbound network in the core product. See §1.4. |
| Runtime | Python **3.12**, bundled — not 3.14, see §2.3 |
| Distribution | Single Windows `.exe` (PyInstaller onedir) |

### 1.1 Launch
1. User double-clicks the `.exe`.
2. Server starts silently. No console window, ever.
3. Default browser opens to `http://localhost:8731`.
4. **Port collision handling.** Attempt to bind 8731. On `EADDRINUSE`, probe
   `GET /healthz`. If it answers with this app's signature, open the browser at
   that port and exit — a second launch attaches to the running instance rather
   than failing. Otherwise increment and retry up to ten ports, surfacing the
   chosen port in the UI.

### 1.2 Shutdown
A prominent **Shut Down** control in the app header. On click: release SolidWorks
COM references, close any documents the app opened, restore any mutated
SolidWorks preferences (§15.7), flush checkpoint state, terminate the process.
Display *"SolidGrade has shut down. You can safely close this tab."* The app does
not close the tab programmatically.

### 1.3 Progress and output
All grading progress is emitted as **structured events** consumed by the front
end. The existing graders communicate exclusively through `print()`, including
box-drawing characters and emoji; all of it is replaced. Note that the emoji also
carry a latent `UnicodeEncodeError` on any console not set to UTF-8 — another
reason the console goes away entirely.

### 1.4 No network
The core product makes no outbound connections. This is a deliberate reversal of
the Firebase architecture, which published student data to world-readable URLs.
The single exception is §9.7's optional LLM-assisted structure detection, which is
off by default, requires the user to supply their own key, and sends only a
directory listing — never file contents, never student names where avoidable.

### 1.5 Deferred
System tray icon; idle auto-shutdown; assembly grading; drawing grading; Canvas
integration of any kind.

---

## 2. Dependency Management and Packaging

### 2.1 Strategy A — bundle the runtime

**Decided.** Discovery established that detect-and-install is not merely more
work, it is unsafe: `scipy` is required at runtime by `trimesh.VoxelGrid.fill()`
but appears in **zero import statements** in the codebase. Any dependency check
built by scanning imports concludes scipy is unnecessary, installs a
working-looking environment, and produces a shape score of 0.0 for every student
with `error: null`. Strategy B converts a packaging problem into a wrong-grades
problem.

### 2.2 Dependency set

Core, all bundled, all pinned in a lockfile:

| Package | Compiled | Note |
|---|---|---|
| `pywin32` | yes | COM and window layer. Late binding only — never `gencache` |
| `numpy` | yes | |
| `scipy` | yes | **Undeclared in the source. Mandatory.** `--hidden-import scipy.ndimage` |
| `trimesh` | no | Lazy-imports its optional deps; static analysis will miss them |
| Flask or FastAPI | no | |

Dropped: `mcp`, `firebase-admin`, `requests`, `selenium`, `pywinauto`,
`openpyxl`.

### 2.3 Build notes
- **Pin Python 3.12.** The repo is on 3.14; wheels exist but PyInstaller hooks are
  young. Nothing in the codebase needs 3.13+ syntax.
- Expected onedir size 250–400 MB. Acceptable — the machine already runs
  SolidWorks.
- **Verify the frozen binary, not the dev environment.** Build and test the `.exe`
  early and continuously, not at the end. Every packaging assumption — hidden
  console, COM access from a frozen process, dismisser behaviour — is only true
  if verified from the executable.

### 2.4 Startup self-test — mandatory gate
On every launch, before the app reports ready:
1. Compare the bundled fixture part (`test_underdefined.SLDPRT`) against itself.
2. Assert the form score is **1.0**.
3. If it is not, **refuse to grade** and surface a specific error.

This single check catches the scipy failure, a broken trimesh bundle, and any
future silent-zero regression. Without it, Strategy A merely relocates the failure
from the instructor's machine to the build machine.

---

## 3. System Status Indicator

A single combined **System Ready** pill in the header — quiet when healthy,
assertive when not. Click expands to three rows.

### 3.1 Runtime row
Bundled runtime present and the §2.4 self-test passing. Because the runtime is
bundled, this row is normally trivially green; its real job is reporting a failed
self-test.

### 3.2 SolidWorks row
- **Installed / not installed** — determined by registry probe
  (`HKLM\SOFTWARE\SolidWorks`) or `CLSIDToProgID` / `LocalServer32` lookup.
- **Running / not running** — determined by
  `pythoncom.GetActiveObject("SldWorks.Application")`.
- **Edition and version** — from `ApplicationType` and `RevisionNumber`, with a
  build-number-to-year mapping table. `RevisionNumber` returns a build number like
  `34.x`, not "2026".
- **Launch SolidWorks** button inline on this row when installed but not running.
  Starts an instance, shows a spinner, auto-polls until COM responds, flips green
  with no further user action.

**Critical correction to v0.1.** The existing `solidworks_health_check()` *cannot*
detect either of the first two states. It calls
`win32com.client.dynamic.Dispatch`, which is `CoCreateInstance` — for a registered
local server this **launches SolidWorks** and then reports `running: True`.
Despite docstrings and log strings saying otherwise, `GetActiveObject` is never
called anywhere in the repo. Both detectors must be built.

### 3.3 Edition caveat
Frame the caveat around **edition**, not year — that is where the risk lives. If
the running edition has not passed the §16 validation suite on this machine,
display a non-blocking notice saying so and link to the validation run. Do not
hard-block.

---

## 4. Information Architecture

```
Home
├── System Ready indicator (header, all screens)
├── Create New Assignment  [button]
├── Recent Grading Runs    [cards]
└── All Assignments        [cards]

Assignment Editor
├── Metadata (title, course, due date, total points, class section)
├── Parts list (Part 1..N scaffold)
│   └── Part Editor (solution, drawing, image, points, criteria override)
└── Grading criteria (assignment-level override)

Run Grading Wizard
├── 1. Solution verification
├── 2. Select submissions folder
├── 3. Ingestion + attribution review        ← blocking
├── 4. Criteria confirmation
├── 5. SolidWorks live check                 ← blocking
└── 6. Run + live progress

Results View
└── Grading table (pivot: by student / by problem)

Class Sections
└── Section editor (roster)

Settings
├── Default grading criteria (export / import)
├── Edition validation status
└── Optional LLM API key
```

**Scope tabs.** Parts, Assemblies, Drawings are all surfaced. Only **Parts** is
functional; the others are visible, disabled, labeled **Coming Soon**. Every
reader in `tool_*.py` hardcodes `swDocPART = 1`.

---

## 5. Home Screen

### 5.1 Recent Grading Runs
Card: assignment name · thumbnail (§6.4) · run date · students graded · average
score · **count of items needing review** · link to results.

The review count belongs on the card. It is the number the instructor actually
acts on.

If the results record is missing: *"Results not found — they may have been renamed
or removed."* No relink flow in v1.

### 5.2 All Assignments
Card: name · thumbnail · part count · last graded date · **Run Grading** button ·
body click opens the Assignment Editor.

---

## 6. Assignments

### 6.1 Creation
Required: assignment title · number of parts · total point value · **class
section**.
Optional: course name · due date.

On submit the app scaffolds Part 1 … Part N as empty, clearly-marked
*unconfigured* rows, fillable in any order. The overview shows at a glance which
parts are complete.

### 6.2 Point values
Each part defaults to `total_points / number_of_parts`, individually overridable.
If part values diverge from the assignment total, warn — do not block.

### 6.3 Part editor
| Field | Required | Notes |
|---|---|---|
| Solution file (`.SLDPRT`) | **Yes** | Copied into app-managed storage on add |
| Point value | **Yes** | Pre-filled by even split |
| Grading criteria | Inherits | Assignment-level, which inherits global |
| Drawing file (`.SLDDRW`) | No | Recommended |
| Reference image | No | Recommended |
| Part name | No | Defaults to "Part N" |

### 6.4 Thumbnails — approach changed

**v0.1's approach is dead.** Discovery established that modern `.SLDPRT` is not an
OLE compound document — the sample file's magic is `99 01 9f 76`, not
`d0cf11e0…` — so there is no compound-document preview stream to read, and a scan
for BMP/PNG/JPEG/GIF signatures found none.

**Approach for v0.2: render the exported STL.** The grading pipeline already
exports a solution STL. Render it offscreen at part-add time and cache the PNG in
app storage. This costs nothing extra, works on every edition, and requires no
license.

The Document Manager SDK (`ISwDMDocument.GetPreviewPNG`) is the only real API
route and is **not pursued** — it requires a separately licensed key from
Dassault, and the `dm_connection.py` module referenced in `sw_connection.py:21`
does not exist. Revisit only if the license is already owned.

Assignment thumbnail = first part's thumbnail.

### 6.5 Export / import
A single zip containing assignment metadata, the effective criteria config, and
all solution files, drawings and reference images. **Never** student submissions,
results, or roster data. Import unpacks into the recipient's app-managed storage
and recreates the assignment.

---

## 7. Grading Criteria and Rubric

### 7.1 Three-tier inheritance
1. **Global default** — Settings. The baseline.
2. **Assignment-level override** — optional, and where most customization happens.
3. **Part-level override** — optional, expected rare.

Each level shows plainly whether it is inheriting or overriding, with one-click
revert.

**Nothing configurable exists today.** Weights and thresholds are module-level
constants duplicated across `grade_assignment.py` and `grade_midterm.py`, and they
**disagree** — `VOXEL_RES` is 64 in one and 24 in the other, which means the same
submission gets materially different shape scores depending on which script ran.
Lifting these into a criteria object is the core refactor of §14.

### 7.2 Every check reports three states

`pass` · `fail` · **`not_evaluated`**

`not_evaluated` is not a synonym for either other state. It forces
`needs_review`, and it **withholds** the check's points rather than awarding or
deducting them. This is the single most important structural change in v0.2 and
the reason for §15.

### 7.3 Form and scale are separate checks — D1

v0.1 inherited the existing behaviour, in which shape comparison normalizes scale
away entirely. Discovery measured the consequence: a part modeled at 2× scale, or
in inches instead of millimetres, scores a **perfect 1.0** on the largest check in
the rubric. Only the volume check caught it, at ±1 %, for a tenth of the points.

v0.2 splits this into two independently weighted, independently thresholded
checks:

| Check | Measures | Threshold |
|---|---|---|
| **Form** | PCA-normalized voxel IoU — shape irrespective of size | min IoU, default **0.95** |
| **Scale** | Ratio of the student's largest bounding-box extent to the solution's | tolerance, default **±1 %** |

Both are reported, both are visible in the results table, and *"right shape, wrong
size"* becomes legible to the instructor rather than collapsing into one number.

**This also removes the volume/shape coupling.** The existing `compute_grade` is
not a weighted sum — shape credit is boosted to full only when volume is correct.
That coupling existed to make scale-blindness survivable. With scale scored
directly, it is unnecessary. **The rubric becomes a flat weighted sum of
independent checks**, which is what v0.1 §7.2 assumed all along and which the code
did not actually do.

### 7.4 Voxel resolution — D3
Resolution is a criteria field with a **hard floor of 64**. It is not a speed
lever.

Measured noise floors: ~0.8 % at resolution 64, ~3 % at resolution 24. In the
committed Quiz 3 results — run at 24 — seventeen students had volumes agreeing to
thirteen significant figures, meaning geometrically identical models, yet their
shape scores spanned 0.9681 to 1.0000. At resolution 24 the 0.95 threshold sits
roughly 1.5 noise-widths above the floor. Speed comes from §11.4, not from here.

### 7.5 Check reference

| Check | Threshold | Unit | Default | Notes |
|---|---|---|---|---|
| Form | min IoU | dimensionless 0–1 | 0.95 | Valid only at resolution ≥ 64 |
| Scale | max deviation | fraction | 0.01 (±1 %) | New in v0.2 |
| Volume | max deviation | fraction | 0.01 (±1 %) | Stored as fraction, labeled "±1 %" in UI. Note the existing code checks volume only — **mass is read and never compared** |
| Material | name match | string | exact, case-insensitive | Brittle: "Brass" vs "Brass, Soft Yellow" fails. Support a per-part allow-list |
| Sketch definition | underdefined allowed | integer | 0 | Currently hardcoded all-or-nothing; make configurable |
| Plagiarism prompt | — | — | on | §7.7 |

### 7.6 Symmetric-part handling
Discovery measured a cube compared against the same cube rotated 45° about Z
scoring **0.364**. PCA axes are degenerate when principal moments are equal —
cubes, square prisms, regular polygonal solids, which is most of an intro CAD
assignment. The eight sign-flips the code tries cover only 8 of 24 rotational
alignments.

Required:
1. Search all **24** axis-permutation × sign combinations, not 8.
2. Detect near-equal PCA eigenvalues (ratio within a few percent) and, when
   detected, mark the form result **low confidence**, which forces
   `needs_review` regardless of score.

### 7.7 Plagiarism — reframed
The signal is weaker than v0.1 assumed, for three reasons established in
discovery:
- The field the code calls `author` is actually **last saved by**
  (`swSumInfoSavedBy`). Any instructor who opens a student's file inherits it —
  which already happened: one Quiz 3 submission carries `sw_author: GCE4`.
- Roughly **25 %** of observed values are personal-machine account names
  (`light`, `Finnk`, `Sara`) rather than university logins.
- Students on shared lab machines under one login trigger it en masse.

Therefore:
- Rename the field to `last_saved_by` **everywhere**, including the UI.
- The check produces a **review prompt, never an accusation**, and the UI wording
  must say so.
- It is toggleable with its own weight, per §7.1.
- Fix the self-exclusion bug: `author_map` is keyed with the filename-derived
  username but self-exclusion compares against the display name, so **a flagged
  student is currently listed as their own plagiarism partner**.
- Build a fixture with known duplicates before shipping. This code path has never
  fired on real data — all 24 authors in the only committed dataset are distinct.

### 7.8 Criteria config file
Any criteria set serializes to portable JSON. Settings exposes **Export** and
**Import** so instructors can hand each other a rubric as a single file. There is
no existing format to adopt — the repo contains no configuration files of any
kind.

---

## 8. Class Sections

Persistent, first-class entities independent of any assignment. Built once,
reused across every assignment for that class, across semesters. Nothing like this
exists today at any layer.

**Roster fields:** first name, last name, email — **required**. Student ID —
optional but strongly improves matching. Arbitrary additional identifiers
(username, login, alias) — optional.

**Bulk import:** CSV with a column-mapping step, so arbitrary source formats map
onto the fields above. No prior art exists.

**Per-student status:** Active · Dropped · Excluded / Do Not Grade. Non-active
students are skipped by new runs but retain all historical results.

---

## 9. Submission Ingestion and Attribution

The highest-risk subsystem, and the largest piece of new work. Discovery confirmed
this and found three separate live mechanisms that swap student identity (§15.2).
**Build this before any UI polish.**

### 9.1 Structure auto-detection
Classify the selected folder as **flat**, **by problem**, **by student**, or
**mixed / inconsistent**.

Prior art to port: `canvas_reorganizer.guess_problem_number()` recognises 4-digit
codes with a base offset, short codes (`MT1`, `P2`, `Q1`, `HW3`), and plain
numbers. `grade_midterm.find_problem_folders()` handles the by-problem case via a
trailing-digit regex. Nothing detects flat or by-student layouts.

### 9.2 Canvas tooling — scope
The four `canvas_*.py` scripts are out of scope. They require Chrome, ChromeDriver
and an interactive login, and `canvas_clicker.py` writes grades back by clicking
SpeedGrader buttons, which is a separate product.

**Port exactly two functions** into ingestion:
`guess_problem_number()` and `strip_chrome_duplicate_suffix()`.

### 9.3 Filtering
Retain only recognized SolidWorks extensions. **Display the ignored set** so the
instructor can confirm nothing important was dropped — this does not exist today.

### 9.4 Duplicate resolution
Resolve to the **most recent** submission, by filesystem mtime cross-checked
against the `last_saved_date` the metadata reader already captures. Surface every
resolution in the review screen.

Current behaviour is worse than absent and must be replaced outright:
`grade_assignment` dedups by lowercased filename keeping the first, and
`grading_agent` skips copying a colliding name **but overwrites the identity-map
entry anyway** — so two students submitting `Part1.SLDPRT` results in one file
graded and attributed to the other student. That is the flat-folder case by
definition.

### 9.5 Matching signals
Combined into an explicit confidence score per file:

| # | Signal | Current state |
|---|---|---|
| 1 | Filename tokens vs roster names / IDs / emails | `extract_username()` is a single `split('-')[0]`. On real Canvas-derived names it produced `BSsFnYZm46NmhXoAvysz_1774142755760_Baik.Ellen` |
| 2 | Parent folder name vs roster | Exists only in the Firebase path |
| 3 | **`last_saved_by`** metadata | Available, but ~25 % unusable — weight it low, and label it correctly |
| 4 | Fuzzy / nearest match | Does not exist |

Attribution keys must be **hard keys — student ID plus part — never a derived
string**.

### 9.6 Pre-flight review — blocking
High-confidence matches auto-assign and display as resolved. Everything ambiguous
lands in a **Needs Attribution** list showing filename, extracted metadata, and
ranked suggestions. The instructor confirms or assigns manually.

**Start Grading remains disabled until every retained file is attributed to a
student and a part, and every active roster student is either matched or
explicitly marked as no-submission.**

### 9.7 Optional LLM-assisted detection
Off by default. Requires a user-supplied key. Sends only the directory listing.
Output is always a suggestion for human confirmation, never applied automatically.

### 9.8 Normalization
Produce one canonical internal representation regardless of input pattern. All
downstream logic and UI read from that form only.

---

## 10. Run Grading Wizard

1. **Solution verification** — confirm every part's solution is present in app
   storage; prompt to relocate if missing. **Exact match or fail.** No regex
   fallback (§15.2).
2. **Select submissions folder** — prompted fresh every run.
3. **Ingestion and attribution** — §9. Blocking.
4. **Criteria confirmation** — effective criteria with live toggles and weights.
   Applies to this run only; the effective set is embedded in the result record. A
   separate explicit **Save as assignment default** button writes back.
5. **SolidWorks live check** — §3.2 detectors, immediately before start. If
   unavailable, block with an inline Launch button and recheck so the user never
   backs out of the wizard.
6. **Run** — live progress: current student, current part, N of M, elapsed, and
   **per-file duration trend** (§11.5).

---

## 11. Resilience, Checkpointing and Performance

### 11.1 Checkpointing — build first
Write an append-only checkpoint **after each file**, recording per student per
part: pending / complete / failed, with failure reason and timestamp.

Today results are written only after the final student completes. At the measured
rate, a midterm is 60–100 minutes of exposure with a single point of failure at
the very end.

**Idempotency warning.** The current code overwrites the student's exported STL
with a PCA-normalized version *after* comparison, writing to the same path the
mesh was loaded from. Re-running over an existing output folder therefore
re-normalizes an already-normalized mesh. **Fix this before implementing resume**
— write normalized meshes to a distinct path.

### 11.2 Interruption recovery
On detecting an incomplete run, present:

> *X complete · Y failed · Z remaining*

with three explicit choices: **Resume** · **Retry failures** · **Start fresh**
(destructive, requires confirmation). Never auto-resume.

### 11.3 Timeouts — required, and nearly free
v0.1 §11.3 assumed the COM layer fails fast. **It does not.**
`open_part_silent()` accepts a `timeout` parameter, documents that it raises on
stall, and then **never uses it** — the parameter is dead. `sw_timeout.py`
implements exactly the needed wrapper and is imported by nothing; a stale `.pyc`
shows it was wired in once and removed. `recover_from_stall()` is unreachable from
a real hang because it only runs from an `except` branch.

**Wrap every COM entry point in the existing `with_timeout()`.** This is close to
a one-line-per-call-site change and converts an indefinite hang into a failed
item — which is what v0.1 assumed was already true. With this in place, no
heartbeat is needed.

### 11.4 Performance — D3
Speed comes from these, in order, and never from lowering resolution:

1. **Producer/consumer split.** SolidWorks is strictly single-threaded (§15.5),
   but mesh normalization and voxel IoU touch no COM and account for a large share
   of the ~60 s. One serialized COM thread exports STLs; a worker pool does
   comparisons. Estimated to roughly halve wall time. **This is the primary
   lever.**
2. **Leaked-document sweep.** `diag_batch.py` swept for leaked open documents
   after each student; that sweep did not survive into `grade_assignment.py`.
   Restore it. Call `close_all_docs()` periodically.
3. **Process recycling.** Kill and reconnect SolidWorks every N files. Cheap once
   §11.1 checkpointing exists.

### 11.5 Degradation monitoring
Discovery measured per-file time roughly **tripling over ~90 minutes on identical
inputs** — 33 s per file in the first job, 97 s by the eighth. The SolidWorks
process persisted across all of them.

Instrument per-file duration, surface the trend in the progress UI, and trigger
recycling when the rolling average exceeds a multiple of the session baseline.

*Confidence note: the correlation is strong and monotonic across nine jobs, but
those runs also involved Firebase uploads. One clean 40-file local run should
confirm the cause before committing to recycling thresholds.*

---

## 12. Results View

### 12.1 Table
Frozen student-name column · one column per part · total column. Part column
headers expand to reveal sub-criteria columns inline (form, scale, volume,
material, sketch, plagiarism prompt). Expand All / Collapse All.

**Reuse the existing visual vocabulary.** `grade_midterm`'s xlsx Overview sheet is
a working prototype of exactly this grid, with a ✓ / ⚠ / ⚑ / — language already
proven in use.

### 12.2 Pivot
Same data viewable **by student** or **by problem**. Both support the same
actions.

### 12.3 Pass / flag / not-evaluated
- **Green check** — passed every enabled check. The instructor never opens it.
  This is the product's entire value and must be the most legible thing on screen.
- **Flagged** — failed a check, or low-confidence (§7.6), or duplicate-resolved.
- **Not evaluated** — visually distinct from both. Points withheld, review forced.

The existing `needs_review` flag already implements the core semantic.

### 12.4 Overrides
Every auto-generated value is editable — individual checks and part/total scores.
Store **`computed` and `override` as an explicit pair**; never mutate in place, so
the original is always retrievable. Overridden cells carry a persistent visual
marker plus a one-click **revert to auto-generated**. Totals recalculate live.

The existing schema is aspirational only: `grade_assignment.py`'s docstring
specifies `override`, `override_note` and `override_by`, the code emits them as
`None`, nothing reads or writes them, and the committed Quiz 3 output does not
contain them at all.

### 12.5 Notes
Per student per part, and per student overall. Both optional. A small icon that
expands to a text area and collapses when empty.

### 12.6 Inline SolidWorks actions
**Open student submission** and **Open solution**, from any row.

Implemented by storing the **absolute source path** in the result record and
opening on demand, with a graceful *"file moved"* message. No cached copies — that
multiplies the FERPA surface for no functional gain.

This is only safe once §15.3 lands: student files are currently opened
**read-write**.

### 12.7 Export
CSV of the full table including computed values, overrides, override markers and
notes. No xlsx — see §0.3 and §17.1.

---

## 13. App-Managed Storage

A single app-owned directory is the source of truth.

**Owned by the app:** solution files, drawings, reference images (copied on add —
the original location becomes irrelevant immediately) · criteria configs · rosters
· assignment definitions · run results and checkpoint state · rendered thumbnails.

**Never stored:** student submission files. Referenced by absolute path only
(§12.6).

**Never networked:** see §1.4.

Results are stored as structured data and rendered in-browser. Viewing results
must never require Excel or any other software.

---

## 14. Core Refactor

### 14.1 The MCP question is already resolved
No extraction work is needed. `tool_*.py` import nothing from `mcp` and nothing
from `server`; the dependency runs strictly server → tools. The desktop app can
`import tool_mass` today and delete nothing.

### 14.2 The refactor that *is* needed
Three things, none of which v0.1 anticipated:

1. **Collapse three duplicated batch-grading loops into one.**
   `grade_assignment.py`, `grade_midterm.py` and `diag_batch.py` are three copies
   with divergent constants.
2. **Lift rubric constants into the §7 criteria object.** This is where §7.1
   plugs in.
3. **Formalize the private per-document readers as the public API.** The graders
   correctly call `_read_mass_properties(doc)` rather than
   `get_mass_properties(filepath)`, to avoid reopening the file per check — that
   optimization is why a file takes ~60 s instead of ~4 minutes. Make them public:
   `read_mass(doc) -> dict`, with path-based wrappers layered on top.

### 14.3 Module status

| Module | State |
|---|---|
| `sw_connection.py` | Reuse. "Silent" is only true on the third open strategy; health check cannot detect not-running; stall recovery unreachable. All addressed in §15 |
| `tool_mass.py` | Reuse as-is. More is read than used — surface area, CoM, density are free additional checks if wanted |
| `tool_metadata.py` | Reuse; rename `author` → `last_saved_by` throughout |
| `tool_sketch.py` | Reuse; fails open — see §15.1 |
| `tool_export.py` | Reuse; fix the global preference mutation, §15.7 |
| `tool_compare.py` | Reuse core; requires §7.3, §7.6 and §15.1 changes |
| `popup_dismisser.py` | Reuse; load-bearing — 76 dismissals in one log. Requires §15.6 hardening |
| `sw_timeout.py` | **Wire it up.** Currently imported by nothing |
| `server.py`, `server_additions.py`, `grading_agent.py`, `canvas_*.py`, `diag_*.py` | Not part of the desktop app. Keep `diag_*.py` — they are the provenance of every magic constant and the tooling for §16 |

### 14.4 Move `CoInitialize` out of module scope
`grade_assignment.py` and `grade_midterm.py` call `pythoncom.CoInitialize()` at
**import time**. A web app importing them initializes COM on whatever thread did
the import — not the thread that will make COM calls. Move to an explicit init on
the dedicated COM thread (§15.5).

### 14.5 Reconcile duplicate mass-property implementations
`tool_mass._read_mass_properties` and `server.get_mass_props` use different APIs
and **return different units** — mm³ versus m³. Keep the `tool_mass` version;
delete the other.

---

## 15. Correctness Invariants

**This section outranks every feature in this document.** Discovery found three
paths that silently produce wrong grades and three that produce wrong
attribution. A batch grader that catches exceptions and returns defaults turns a
swallowed error into a number in a gradebook.

### 15.1 No swallowed exception may produce a score
- `_voxel_iou`'s `except Exception: return 0.0` must return **`None`**, not zero.
- Sketch status `UNKNOWN` counts as **`not_evaluated`**, never as passing.
  Currently `_get_sketch_status` catches everything and returns `UNKNOWN`, callers
  filter only for `UNDERDEFINED`, so `sketches_ok` comes back `True` and the
  student receives full marks. If DISPID 48 ever changes meaning, **every student
  silently passes the sketch check.**
- A failed mass read must set `not_evaluated`, not `volume_ok = False`. Today a
  read failure is indistinguishable from a genuinely wrong volume, and the student
  loses points for something they did not do.
- The `volume_ratio` fallback in `compare_shapes` puts a number with **entirely
  different semantics** into the `score` field while `method` changes to
  `volume_ratio_fallback`. Two parts of identical volume and completely different
  shape score 1.0. `grade_assignment.py` does not check `method`. Either check it
  everywhere or remove the fallback — removing it is cleaner.
- The §2.4 startup self-test is the backstop for all of the above.

### 15.2 Attribution must be unforgeable
- Hard keys only: student ID + part. Never a derived string.
- Fix the `grading_agent` collision bug — currently the file copy is skipped but
  the identity map is overwritten unconditionally.
- **Solution lookup is exact-match-or-fail.** `grade_midterm.find_solution_file`
  falls back to `re.search(rf'0*{n}$', stem)`, which for problem 1 matches
  `SE00002311` — problem 11. That silently grades an entire cohort against the
  wrong solution, and every student simply looks like they failed.
- Hash file contents to detect true duplicates.

### 15.3 Student files must be opened read-only
`open_part_silent` tries bare `OpenDoc(path, 1)` **first** — no flags, no
read-only — and the logs show it succeeding routinely. Only the third fallback
passes `swOpenDocOptions_Silent | swOpenDocOptions_ReadOnly`. Every file then gets
`ForceRebuild3` and a `SaveAs` during export.

The codebase clearly intends read-only — `close_doc` raises on `save=True` with
the comment *"student files must never be modified"* — the open path just does not
honour it. And the risk is not theoretical: a Quiz 3 submission carries a
last-saved date two weeks after every other and the instructor's own login.

Required:
1. Reorder so `OpenDoc6` with `Silent | ReadOnly` is tried **first**.
2. **Grade a scratch copy, never the original.** Copy each submission to a
   scratch directory, mark it read-only on the filesystem, grade the copy, delete
   it after.

### 15.4 Every check reports three states
See §7.2. There is currently no "did not execute" state anywhere in the schema —
every check is boolean, and failure collapses into `False` or, worse, `True`.

### 15.5 SolidWorks is strictly single-threaded
COM is an STA automation server with one global `ActiveDoc`. **`server.py`'s
`grading_batch` violates this today**: three threads call methods on the same
`doc` pointer, none calls `CoInitialize`, and the docstring asserts the calls are
"safe to parallelize." They are not — a raw dispatch pointer used from a foreign
thread without marshalling yields `RPC_E_WRONGTHREAD`. Worse, each thread's
`join(timeout=30)` returns on timeout and the code reads a **partially populated**
result dict, which is truthy and therefore reported as complete data.
`server_additions.py` contains the correct sequential version.

Required: all COM confined to **one dedicated thread** with an explicit
`CoInitialize`. Parallelize only downstream of the STL (§11.4).

### 15.6 Popup dismisser hardening
Required, and load-bearing — without it every file open blocks forever, and with
no timeouts (§11.3) forever means forever.

But its rule list includes a bare catch-all matching any `Button` labeled `Yes` or
`OK` in any window whose title contains "solidworks". **It will click Yes on a
dialog it was never meant to answer** — plausibly a "Save changes?" prompt on a
student file, which combined with §15.3 is a data-loss path.

Required:
1. Narrow rules to exact known dialog titles. Remove the `["Yes", "OK"]`
   catch-all. Log-and-skip anything unrecognized.
2. **Detect UIPI failure.** Windows blocks `SendMessage` across integrity levels.
   If the packaged `.exe` and SolidWorks run at different elevations the dismisser
   silently stops working — enumeration still succeeds, the click does nothing,
   and the first symptom is an unexplained hang. Assert integrity-level parity at
   startup; alert if a file open exceeds N seconds with zero dismissals, which is
   the failure signature.

### 15.7 Restore mutated SolidWorks preferences
`tool_export._set_stl_quality` writes `swSTLDeviation` and `swSTLAngleTolerance`
into the user's preferences and restores them in a `finally`. A crash between set
and restore **leaves the instructor's SolidWorks permanently configured at grading
tolerances**, affecting their own modelling work.

Required: persist the original values to disk before mutating, restore via
`atexit` as well as `finally`, and recover on next launch if a crash is detected.

---

## 16. Edition Validation — D2

Both Student Edition and Desktop / 3DExperience are targets. Only Student Edition
has evidence behind it: every logged connection reports `ApplicationType=1`, and
every magic constant in the codebase was derived there.

### 16.1 What is at risk per edition

| Constant | Risk | Why |
|---|---|---|
| `GetMassProperties` index order | **Low** | The `(CoM×3, volume, area, mass, inertia×6)` ordering is the documented one. `tool_mass.py`'s comment calling it a "non-standard Student Edition order" is wrong — the code is right for the wrong reason |
| `SummaryInfo` index 5 | **Not an edition issue** | It is a semantic error. Index 5 is `swSumInfoSavedBy`, not author. Fix regardless (§7.7) |
| **DISPID 7 → 48 sketch probe** | **High** | Raw DISPIDs are not a public contract. The probe exists only because named dispatch was locked out on Student Edition — **on Desktop the supported `ISketch::GetFullyDefinedStatus` may simply work**. And it fails *open* (§15.1) |
| Four-strategy open ladder | Medium | Which strategy wins varies by edition; §15.3 reorders it anyway |
| Popup dismisser necessity | Medium | The "educational use only" nag is Student-specific. On Desktop the dismisser may be optional — keep it either way, it also catches version-mismatch prompts |

### 16.2 The validation pass
The `diag_*.py` scripts are exactly the right tool and this is their remaining
purpose. On each target edition, run: `diag_props.py` (SummaryInfo indices),
`diag_sketch.py` (DISPID probe against its committed ground truth),
`diag_mass.py` (index order), `diag_export.py` (STL API). Roughly a day per
edition.

### 16.3 Edition dispatch
Each reader gets an edition-aware path where behaviour diverges. Where the
supported named API works — likely the sketch check on Desktop — **prefer it over
the DISPID probe**.

### 16.4 Validation status is a first-class app state
Settings displays which editions have passed validation on this machine. §3.3's
caveat reads from it. An unvalidated edition warns but does not block.

### 16.5 Confirm before building §3
Three live-COM confirmations, each a few minutes on the target machine, that
discovery could not perform:
1. Does `Dispatch("SldWorks.Application")` launch SolidWorks when it is not
   running? (Decides §3.2's detectors.)
2. Is `SummaryInfo(5)` last-saved-by or author? (Confirms §7.7.)
3. Does the DISPID 7→48 probe work on Desktop?

---

## 17. Remaining Open Questions

### 17.1 Canvas grade import format — blocks nothing, but decides a small feature
The existing integration enters grades by clicking SpeedGrader buttons, strongly
suggesting no working CSV import path was ever established. The format is
instance- and assignment-specific and cannot be derived from the repo. **One real
Canvas gradebook export settles it** — half an hour. Until then, ship generic CSV.

### 17.2 Sketch status values 1 and 0
`tool_sketch.py` labels `1 = OVERDEFINED` and `0 = NO_SOLUTION` as unconfirmed
hypotheses. Only 2 and 3 have ground truth. Build fixtures for both before
reporting either state to an instructor.

### 17.3 Whether the R-7 slowdown is SolidWorks or the machine
Monotonic across nine jobs on identical inputs, but those runs also uploaded to
Firebase. One clean 40-file local run settles it and sets the §11.4 recycling
threshold.

### 17.4 Additional free checks
Surface area, centre of mass, density, and `last_saved_date` are all read and
discarded today. `last_saved_date` in particular is the natural signal for a
late-submission or post-deadline-edit check. Worth considering once the core is
stable.

---

## 18. Build Order

Ordered by risk retired per unit of work, not by user-visible progress.

1. **§0.1 remediation.** Rotate the key. Not a build task; do it now.
2. **§15 correctness invariants** on the existing modules — three-state checks,
   read-only opens, timeouts wired, threading removed, dismisser narrowed,
   preferences restored. All small, all on code that already exists, all
   preventing wrong grades.
3. **§2.4 self-test + §2 packaging skeleton.** Prove the `.exe` works before
   building on top of it.
4. **§14 core refactor** — one grading loop, criteria object, public readers.
5. **§11.1 checkpointing.** Small, high payoff, unblocks resume and recycling.
6. **§9 ingestion and attribution.** The largest and highest-risk new subsystem.
7. **§16 edition validation.** Can run in parallel with 4–6 on the second machine.
8. **§7.3 / §7.6 rubric changes** — form/scale split, 24-permutation search.
9. **§8 rosters**, **§6 assignments**, **§13 storage** — the persistence layer.
10. **§12 results view**, **§10 wizard**, **§5 home**, **§3 status** — the UI.
11. **§11.4 performance work.** Last, because it is an optimization and everything
    above changes its shape.
