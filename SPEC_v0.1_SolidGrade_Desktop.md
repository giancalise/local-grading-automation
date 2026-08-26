# SolidGrade Desktop — Tentative Spec v0.1

**Status:** Pre-discovery draft. Written before analysis of the existing code base.
Sections marked **[VERIFY]** must be confirmed or corrected by this discovery pass
before the spec is finalized.

**Purpose:** A local desktop application that lets an engineering instructor build
CAD assignments, ingest student submissions, run automated SolidWorks-based grading
checks, and review/override results — without ever touching a terminal.

**Explicit non-goal:** This tool does not replace grading. It is a *triage* tool.
Its job is to confirm the submissions that are unambiguously correct so the
instructor never has to open them, and to surface everything else for manual review.

---

## 1. Platform & Runtime

| Decision | Value |
|---|---|
| OS | Windows only |
| CAD target | SolidWorks 2026 (others detected but uncertified) |
| Architecture | Local Python web server (Flask or FastAPI) + HTML/CSS/JS front end |
| Client | User's default browser at `localhost:<port>` |
| Network | No internet required for core grading. Internet only for optional LLM-assisted structure detection. |
| Distribution | Single Windows `.exe` (PyInstaller or equivalent) |

### 1.1 Launch behavior
1. User double-clicks the `.exe` on their desktop.
2. The server starts **silently** — no console window, ever.
3. The default browser opens automatically to the app.
4. If the port is already in use, the app must detect this and either reuse the
   running instance or select an alternate port rather than crashing. **[VERIFY]**

### 1.2 Shutdown behavior
- A clearly labeled **Shut Down** control lives in the app header.
- On click: gracefully release SolidWorks COM references, close any documents the
  app opened, flush state to disk, terminate the server process.
- The page then displays a terminal-state message: *"SolidGrade has shut down. You
  can safely close this tab."*
- The app does **not** attempt to close the browser tab programmatically.
- Because there is no tray icon in v1, the Shut Down control must be visually
  prominent enough that users learn to use it.

### 1.3 Deferred to future versions
- System tray icon with quit option (low priority)
- Idle timeout auto-shutdown
- Assembly grading
- Drawing grading

---

## 2. Dependency Management (Zero-Terminal Requirement)

The target user is an instructor, not a developer. They will never open a command
prompt, and must never be asked to.

### 2.1 Two candidate strategies — **OPEN DECISION [VERIFY]**

**Strategy A — Bundled runtime (preferred if feasible).**
Ship a complete Python environment with all dependencies inside the `.exe`. Nothing
to install. Nothing to detect. The Python status check becomes trivially green.
*Risk:* `numpy`, `scipy`, and `trimesh` are C-extension-heavy; bundle size likely
several hundred MB and the build may be finicky.

**Strategy B — Detect and auto-install.**
On launch, detect system Python and each required package. If anything is missing,
show a guided setup screen with a single button that runs the installation as a
hidden background process (no visible terminal), then re-checks and flips green.
*Risk:* more failure modes, depends on the user's machine state, may need elevated
permissions.

**This discovery pass must report:** the complete, exact dependency list across all
existing scripts; whether that set bundles cleanly with PyInstaller; estimated
bundle size; and a recommendation between A and B.

### 2.2 Required regardless of strategy
- The dependency check runs on every launch, not just first run.
- If unsatisfied, the app must not allow a grading run to start.

---

## 3. System Status Indicator

A **single combined "System Ready" indicator** sits in the header. It is quiet and
unobtrusive when healthy — a small green pill. It is visually assertive when not.

Clicking it expands a detail panel containing two rows:

**Python row**
- Green: runtime and all required libraries present.
- Red: lists specifically what is missing, with a one-click remediation action
  (per Strategy A or B above).

**SolidWorks row**
- Displays the detected installed version, e.g. *"SolidWorks 2026 detected."*
- Displays running / not running state.
- If a version other than 2026 is detected: display a non-blocking caveat that
  grading accuracy has only been verified against 2026. Do **not** hard-block.
- If no SolidWorks installation is found: clear message that SolidWorks is required.
- If installed but not running: a **Launch SolidWorks** button sits inline on this
  row. Clicking it starts an instance, shows a spinner, and **auto-polls** until
  SolidWorks responds over COM, then flips the indicator green with no further
  user action.

---

## 4. Information Architecture


```

Home ├── System Ready indicator (header, all screens) ├── Create New Assignment [button] ├── Recent Grading Runs [cards] └── All Assignments [cards]
Assignment Editor ├── Metadata (title, course, due date, total points, class section) ├── Parts list (Part 1..N scaffold) │ └── Part Editor (solution, drawing, image, points, criteria override) └── Grading criteria (assignment-level override)
Run Grading Wizard ├── 1. Solution file verification ├── 2. Select student submissions folder ├── 3. Ingestion + roster matching review ├── 4. Criteria confirmation ├── 5. SolidWorks live check └── 6. Run + progress
Results View └── Grading table (pivot: by student / by problem)
Class Sections ├── Section list └── Section editor (roster)
Settings ├── Default grading criteria (export / import) ├── App storage location └── Optional LLM API key

```

### 4.1 Scope tabs
The UI surfaces three document types: **Parts**, **Assemblies**, **Drawings**.
Only **Parts** is functional. Assemblies and Drawings are visible but disabled,
labeled **Coming Soon**.

---

## 5. Home Screen

### 5.1 Recent Grading Runs
Card contents:
- Assignment name
- Thumbnail (see §6.4)
- Date of run
- Number of students graded
- Average score
- Link to open results

If a linked results file has been moved or renamed, show a simple error:
*"Results file not found — it may have been renamed or removed."* No relink
browse-flow in v1.

### 5.2 All Assignments
Card contents:
- Assignment name
- Thumbnail
- Number of parts
- Last graded date
- **Run Grading** button (jumps directly into the Run Grading wizard)
- Card body click → Assignment Editor

---

## 6. Assignments

### 6.1 Creation flow
Required at creation:
- Assignment title
- Number of parts
- Total point value
- Class section (association) **[VERIFY — confirm this is required, not optional]**

Optional metadata:
- Course name
- Due date

On submit, the app **scaffolds** Part 1 … Part N as empty, clearly-marked
*unconfigured* rows. The instructor fills them in in any order. The assignment
overview shows at a glance which parts are complete and which are still empty.

### 6.2 Point value defaults
Each part defaults to `total_points / number_of_parts`. Individual parts are
overridable. If the sum of part values diverges from the assignment total, the UI
flags the discrepancy (warn, do not block).

### 6.3 Part editor
| Field | Required | Notes |
|---|---|---|
| Solution file (`.SLDPRT`) | **Yes** | Copied into app-managed storage on add |
| Point value | **Yes** | Pre-filled by even split |
| Grading criteria | Inherits | Defaults to assignment-level, which defaults to global |
| Drawing file (`.SLDDRW`) | No | Recommended — this is what students model from |
| Reference image | No | Recommended alternative/supplement to the drawing |
| Part name / label | No | Defaults to "Part N" |

### 6.4 Thumbnails
- Each part's thumbnail is extracted from its solution `.SLDPRT` file.
- An assignment's thumbnail is the thumbnail of its **first** part.
- **[VERIFY]** Determine whether the embedded SolidWorks preview bitmap can be
  extracted without opening the file (e.g. via Document Manager SDK or the OLE
  compound-document preview stream), and what the fallback is if not — likely a
  headless STL render or a generic placeholder.

### 6.5 Assignment export / import
- Export produces a single portable package (zip) containing:
  - Assignment metadata (title, course, due date, point values, part structure)
  - The effective grading criteria config
  - All solution files, drawing files, and reference images
- Export **never** includes student submissions, results, or roster data.
- Import unpacks into the recipient's app-managed storage and recreates the
  assignment, ready to point at their own students' folder.

---

## 7. Grading Criteria

### 7.1 Three-tier inheritance
1. **Global default** — set in Settings. The baseline.
2. **Assignment-level override** — optional. This is where most customization
   will happen in practice, since criteria are usually uniform across the parts
   of one assignment.
3. **Part-level override** — optional, expected to be rare.

Every level displays clearly whether it is inheriting or overriding, with a
one-click revert to inherited values.

### 7.2 Checks
Each check has: an **enabled** toggle, a **weight** (percentage of the part's
points), and a **threshold** where applicable.

| Check | Threshold parameter | Likely source |
|---|---|---|
| Shape comparison | Minimum similarity score to pass | PCA-normalized voxel IoU |
| Mass properties | Tolerance (± percentage or absolute) | mass/volume/material read |
| Sketch definition | Underdefined sketch count allowed | sketch constraint status |
| Metadata / plagiarism | Match rules against roster identity | file author/custom props |

**[VERIFY]** Enumerate every check the existing scripts actually perform, including
any not listed above, and report the real units and sensible default thresholds
for each.

### 7.3 Criteria config file
- Any criteria set — global or assignment-level — serializes to a portable JSON
  config file.
- Settings exposes **Export Criteria** and **Import Criteria** so instructors can
  hand each other their rubric as a single file.

---

## 8. Class Sections

### 8.1 Model
Class Sections are **persistent, first-class entities**, independent of any
assignment. One section is built once and reused across every assignment for that
class, across semesters.

### 8.2 Roster fields
| Field | Required |
|---|---|
| First name | **Yes** |
| Last name | **Yes** |
| Email | **Yes** |
| Student ID number | No — but strongly improves matching |
| Additional identifiers (username, login, alias) | No — arbitrary extras allowed |

### 8.3 Bulk import
Roster import accepts a CSV (e.g. a Canvas export) with a column-mapping step so
arbitrary source formats can be mapped onto the fields above.

### 8.4 Student status
Each roster entry carries a status: **Active**, **Dropped**, or **Excluded /
Do Not Grade**. Non-active students are skipped by new grading runs but retain all
historical results.

---

## 9. Submission Ingestion & Roster Matching

This is the highest-risk subsystem. Nothing may reach SolidWorks until every file
is confidently attributed to a student and a part.

### 9.1 Structure auto-detection
The tool inspects the selected folder and classifies it as one of:
- **Flat** — all files in a single directory (e.g. 20 students × 4 parts = 80 files)
- **By problem** — one subfolder per part, each containing all students' files
- **By student** — one subfolder per student, each containing that student's parts
- **Mixed / inconsistent** — most files follow a pattern, some do not

### 9.2 Filtering
- Retain only recognized SolidWorks extensions.
- Non-CAD files (PDFs, screenshots, write-ups) are ignored, and the ignored set is
  displayed so the instructor can confirm nothing important was dropped.

### 9.3 Duplicate resolution
When multiple submissions map to the same student + part (Canvas `-2` suffixes,
timestamped copies), **default to the most recent**. Surface the resolution in the
review screen so it can be inspected, but do not block on it.

### 9.4 Matching signals
Ranked, combined into a confidence score per file:
1. Filename tokens matched against roster names / IDs / emails
2. Parent folder name matched against roster
3. **File metadata author field** — often the university login, which frequently
   equals the student ID. Unreliable when students work on personal machines.
4. Fuzzy / nearest-match on any of the above

### 9.5 Pre-flight review screen
- High-confidence matches are auto-assigned and shown as resolved.
- Anything ambiguous or unmatched lands in a **Needs Attribution** list showing the
  filename, its extracted metadata, and ranked best-guess suggestions.
- The instructor confirms a suggestion or assigns manually (dropdown and/or
  drag-and-drop onto a roster entry).
- **The Start Grading action remains disabled until every retained file is
  attributed to a student and a part, and every active roster student is either
  matched or explicitly marked as missing/no-submission.**

### 9.6 Optional LLM-assisted detection (stretch)
If the user supplies an API key in Settings, an LLM may be used to inspect the
folder listing and propose a structure interpretation and rename plan. This is
strictly optional, never required, and its output is always presented as a
suggestion for human confirmation.

### 9.7 Normalization
After attribution, ingestion produces one canonical internal representation
regardless of the input pattern. All downstream logic and UI reads from this
canonical form only.

---

## 10. Run Grading Wizard

1. **Solution verification** — confirm every part's solution file is present in
   app-managed storage. If missing, prompt to relocate.
2. **Select submissions folder** — prompted fresh on every run, since this changes
   between semesters and assignments.
3. **Ingestion & attribution** — §9. Blocking.
4. **Criteria confirmation** — display the effective criteria for this run with
   live toggles and weight adjustments. Changes here apply to this run.
   **[VERIFY]** Confirm whether run-time criteria changes should also persist back
   to the assignment, or apply to the run only.
5. **SolidWorks live check** — verify COM accessibility immediately before start.
   If unavailable, block with a clear message and an inline **Launch SolidWorks**
   button plus recheck, so the user never has to back out of the wizard.
6. **Run** — with live progress: current student, current part, N of M complete.

---

## 11. Run Resilience & Resume

### 11.1 Checkpointing
Every grading run writes progress to a persistent state file as it goes, recording
per student per part: pending / complete / failed, plus the failure reason and
timestamp for failures.

### 11.2 Interruption recovery
If a run is interrupted — SolidWorks crash, app closed, machine sleep — the next
time the instructor opens that assignment, the app detects the incomplete run and
presents a summary:

> *X complete · Y failed · Z remaining*

with three explicit choices:
- **Resume** — process only what is still pending
- **Retry failures** — reprocess only the failed items
- **Start fresh** — discard prior results and re-run everything (destructive;
  requires confirmation)

The app never auto-resumes without asking.

### 11.3 Continuous health monitoring
**[VERIFY]** Continuous SolidWorks polling during a run is *not* required if
checkpointing is robust — a crash simply produces a failed item and the run halts
cleanly. Assess whether the existing COM layer fails fast and cleanly enough for
this to hold, or whether an active heartbeat is needed to avoid indefinite hangs.

---

## 12. Results View

### 12.1 Table structure
- **Frozen left column:** student names
- **One column per part:** that part's score
- **Rightmost column:** total score
- Each part column header is **expandable**, revealing its sub-criteria columns
  inline (shape score, mass properties, sketch status, metadata flags)
- **Expand All** / **Collapse All** controls

### 12.2 Pivot views
The same data can be viewed **by student** (row per student, columns per part) or
**by problem** (all students' responses to a single part). Both views support the
same actions.

### 12.3 Pass / flag semantics
A part shows a **green check** when it passed every enabled check's threshold and
raised no plagiarism flags — meaning the instructor never needs to open it.
Anything else is **flagged for manual review**. This distinction is the core value
of the product and should be the most visually legible thing on the screen.

### 12.4 Overrides
- Every auto-generated value is editable — both individual check results and the
  part/total score.
- Overridden cells carry a persistent visual marker distinguishing human-entered
  from machine-generated values.
- Every override has a **revert to auto-generated** action; the original computed
  value is always retained and viewable.
- Totals recalculate live from overrides.

### 12.5 Notes
- **Per student per part** note, and **per student overall** note.
- Both optional. Rendered as a small unobtrusive icon that expands into a text area
  on click and collapses when empty.

### 12.6 Inline SolidWorks actions
From any row in the results table:
- **Open student submission in SolidWorks**
- **Open solution in SolidWorks**

so the instructor can put both on screen side by side without hunting for files.
**[VERIFY]** This requires the student's original file to remain accessible after
the run completes, which is in tension with §13's rule that student submissions
are never permanently stored. Resolve this — likely either a path reference to the
original folder (with a graceful "file moved" failure) or a deliberate, explicit
exception allowing cached student files, and if so, for how long.

### 12.7 Export
- **CSV export** of the full table including scores, override markers, and notes.
- **[VERIFY]** Determine whether Excel (`.xlsx`) export is still needed for LMS
  upload workflows now that results render natively in-app, and what column format
  Canvas grade import actually requires.

---

## 13. App-Managed Storage

A single app-owned directory is the source of truth. Nothing the app depends on
lives at a user-chosen path that could later move.

**Copied in and owned by the app:**
- Solution files, drawing files, reference images (copied on add — the original
  source location becomes irrelevant immediately)
- Grading criteria configs (global + per assignment)
- Class section rosters
- Assignment definitions
- Grading run results (JSON and/or CSV) and checkpoint state files
- Extracted thumbnails

**Never permanently stored:** student submission files — see the **[VERIFY]** in
§12.6 for the tension this creates.

**Results rendering:** results are stored as structured data and rendered directly
in the browser. Viewing results must never require Excel or any other software to
be installed.

---

## 14. Reuse From Existing Code Base

The following modules are expected to exist in this repo and be reused largely
as-is behind the new front end. Confirm current state of each during discovery.

- COM connect / silent open / close / health check / stall recovery
- Author / dates / custom properties reader
- Mass, volume, surface area, center of mass, density, material reader
- STL export + shape comparison (PCA-normalized voxel IoU)
- Sketch constraint status reader
- STL / STEP / IGES export
- Popup dismisser for SolidWorks modal dialogs
- Timeout wrapper for stalling COM calls
- Current MCP server exposing the above as tools

### 14.1 Key architectural question
The current system exposes grading capability as **MCP tools** consumed by Claude
Desktop. The desktop app does not need MCP — it can call these functions directly
as a Python library. Determine how tightly the tool modules are coupled to the MCP
layer and what the cleanest separation is.

---

## 15. Open Questions for Discovery

1. Bundled Python runtime vs. detect-and-install — feasibility, size, recommendation
2. Complete and exact dependency list across all scripts
3. Whether the SolidWorks embedded thumbnail can be extracted, and the fallback
4. What files handle actual grading orchestration for a full batch, and whether
   they exist in this repo or are missing
5. Whether any existing Canvas-scraping logic belongs in this desktop app or is
   superseded by the folder-ingestion flow described in §9
6. What of any existing web/cloud front end is reusable, and whether the desktop
   version should be fully decoupled from it
7. How to cleanly extract the grading tools from the MCP server layer
8. Reliability of any DISPID-based COM probes and non-standard property index
   orders across different SolidWorks editions (Desktop vs. Student vs. Connected)
9. Whether the popup dismisser is still required, and whether it interferes with a
   packaged/headless context
10. Whether any grading step can safely run in parallel, or whether SolidWorks
    forces strict serialization
11. Existing config file formats and whether they can be adopted directly
12. Realistic per-file grading time, to size progress UI and timeout values
