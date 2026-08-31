# SolidGrade Desktop — Milestone 3 Report: Results Depth

Session date: 2026-08-31. Follows `MILESTONE_2_REPORT.md`. Builds item 1 of the
agreed priority list in `NEXT_SESSION_PROMPT.md` — per-student detail plus the
two §12.6 row actions the instructor chose — and nothing below it. Items 2–4
were not started; the ordering was to be confirmed first.

---

## 1. What was built

### 1.1 The prerequisite, first

The result record stored `filename` — a basename — and nothing else. There was no
absolute path anywhere in the JSON, so no row action was possible at all.
`grade_assignment.py` now writes, additively:

| Field | Where | Value |
|---|---|---|
| `students_folder` | result root | `os.path.abspath(students_folder)` |
| `source_path` | each student record | `str(student_path.resolve())` |

Both are documented in the module's schema docstring. Nothing else in the record
changed shape, and `compute_grade()` was not touched.

`source_path` is a **reference, never a copy** — SPEC §13 lists student
submissions under "Never stored", and §12.6 specifies the absolute path as the
mechanism precisely so no copy is needed.

### 1.2 Per-student detail (`ui/app.js`, `ui/styles.css`)

Every result row gets a chevron in the frozen student-name column that expands a
detail panel spanning the table. The toggle lives *inside* the sticky column
rather than in a column of its own, so neither the sticky offset nor the colspan
moves.

Seven cards, all of it data that was already in the result JSON and previously
discarded by the UI:

| Card | Shows |
|---|---|
| **Form** | `shape_score` to 3 dp, the threshold, the credit actually used, the voxel resolution, and **in words whether the volume-coupled full-credit boost applied** |
| **Volume & mass** | student vs solution volume, absolute delta, % delta to 3 dp, the ±1 % tolerance, and `mass_kg` |
| **Material** | student vs solution, side by side |
| **Sketches** | the **actual names** in `underdefined_sketches`, as chips |
| **Points** | `shape`/`volume`/`material`/`sketch` points, computed total, effective total, and the override note when there is one |
| **Provenance** | `sw_author`, `last_saved_date`, and the shared-author (plagiarism) prompt framed per §7.7 as a prompt to look, not a finding |
| **Submission** | the full `source_path` plus the row actions |
| **Error** | when `error` is set, a full-width red card carrying the string verbatim, above everything else |

**The boost explanation is the point of this card set.** `compute_grade()` grants
full shape credit only when `shape_score >= threshold` **and** volume is `PASS`.
Until now a student could show IoU 0.99 against a 0.95 threshold and still lose
shape points with nothing on screen saying why. The Form card now says which of
the three cases applies, and shows the arithmetic:

- boost applied → green: *"Full shape credit applied… credited at 1.000 rather
  than at the raw 0.987."*
- **boost withheld** → amber: *"Full-credit boost NOT applied. The score met the
  0.95 threshold, but full shape credit also requires the volume check to pass
  and it did not (volume is fail). Shape is therefore credited at the raw 0.987,
  not 1.000."*
- below threshold → neutral, credited at the raw score.

followed by `0.987 × 65 = 64.2 points.`

**§15.1's third state survives the trip.** A `null` renders as "Not evaluated" in
italic with a sentence saying points were withheld and review forced — never as
`0`, never as a fail. Each not-evaluated card carries its own explanation of what
"we could not tell" means for that check.

### 1.3 Row actions — the two chosen, and explicitly not the third

- **Open in SOLIDWORKS, read-only** (`POST /api/open_in_solidworks`)
- **Reveal in File Explorer** (`POST /api/reveal_file`)
- **Open solution** — §12.6 asks for both "Open student submission" and "Open
  solution", from any row, so both are in every panel.
- **No "save a copy."** §12.6 ("no cached copies — that multiplies the FERPA
  surface") and §13 ("Never stored") both forbid it. The panel says so on screen:
  *"Opens are read-only and the file is never copied — the app only ever holds
  this path, not the submission."* An instructor who expected that button sees
  why there isn't one instead of assuming it was forgotten.

### 1.4 The `locate_sources` action for old results

The kickoff offered a choice: a "locate the submissions folder" action for
results graded before this change, or accept that row actions are dead on them.
The action was built (`POST /api/locate_sources`).

A result with no `source_path` shows the explanation and a single **Locate
submissions folder** button rather than a dead Open button. Picking a folder
matches each student by **exact basename, case-insensitively** — no fuzzy
matching, no stem-prefix guessing, because §15.2 is explicit that attribution
must not be inferred and pointing "Open" at the wrong student's file is exactly
that failure. Unmatched rows are left unlinked and reported. The result JSON on
disk is rewritten atomically (`os.replace`), the same way `/api/override` does.

This matters immediately: the instructor's own 26-student run from today
(`%LOCALAPPDATA%\SolidGrade\output\SolidGrade_Run`, graded 19:29Z) has neither
field, and this is how its rows come alive.

### 1.5 Endpoints

Three added; **no existing endpoint changed request or response shape.**

| Endpoint | Notes |
|---|---|
| `POST /api/open_in_solidworks` | Read-only, verified; refuses while a run owns SOLIDWORKS (409) |
| `POST /api/reveal_file` | `explorer /select,"<path>"` — no COM |
| `POST /api/locate_sources` | Re-point a loaded result at a moved submissions folder |

All three refuse any path that is not a `source_path` in the loaded result or the
result's solution file (403). Even on a loopback-only server, an endpoint that
opens or reveals whatever path the caller names is a general file-launching
primitive; one restricted to the loaded result's own files is the feature that
was asked for.

---

## 2. §15.3 — the invariant this session put at risk, and what was proven

Opening real student files in SOLIDWORKS is the specific new risk. It was
verified live, per click, and by independent hashing outside the app.

### 2.1 The open is read-only by construction

`_open_readonly_in_solidworks()` in `app.py`:

1. **Its own COM attach on the calling thread.** It never touches
   `sw_connection`'s shared singleton — that object belongs to whichever thread
   first created it (normally the grading thread), and reaching into a raw
   dispatch pointer from a Flask request thread is the STA hazard §15.5
   describes and Milestone 1 proved corrupts the connection. A fresh
   `CoInitialize` + `GetActiveObject` gets a properly marshaled proxy, the same
   pattern `sw_detect.is_running()` already uses safely from request threads.
2. **`GetActiveObject`, never `Dispatch`** — clicking "open this file" must not
   become a way to launch SOLIDWORKS.
3. **`swOpenDocOptions_ReadOnly` and no read-write fallback.** There is
   deliberately no second strategy. A file that will not open read-only is not
   opened.
4. **It asks SOLIDWORKS what it actually did.** `IsOpenedReadOnly` is read back;
   if it says the document is writable, the document is closed again and the
   call fails. A writable student file left on screen is one Ctrl+S from a
   violation.
5. The endpoint **sha256-hashes the file before and after every open** and
   returns the answer, so the page reports it rather than asserting it.

### 2.2 Measured

`test_underdefined.SLDPRT` baseline
`899c98038d1ee227b2d12d7194f0e2cb7c86148d9baeb4453c1776b264ef995f` — the same
hash Milestone 1 and Milestone 2 recorded.

| Check | Result |
|---|---|
| Student files byte-identical after a full grading run | **PASS** — both, `899c98038d1ee227…` |
| Solution byte-identical after the run | **PASS** |
| SOLIDWORKS confirms `IsOpenedReadOnly` on the opened student file | **PASS** — `read_only: true` |
| Server's own before/after sha256 across the open | **PASS** — `unchanged: true` |
| Independent sha256 (outside the app) after the open | **PASS** — unchanged |
| **mtime untouched by the open** | **PASS** — `1788208007929560200` either side |
| Size unchanged | **PASS** |
| Bystander submission untouched by opening its neighbour | **PASS** |
| Solution untouched by opening a student file | **PASS** |

### 2.3 Suites

Both are committed under `tests/`, parameterised by `SG_BASE` / `SG_SUBS` /
`SG_SOLUTION`, and re-run from those committed copies against a fresh grading
run before this report was finalised. They need a live dev server holding a
completed run, and SOLIDWORKS running; the file headers say how.


- **`test_m3.py` — 36 checks, 36 passed.** Prerequisite fields; §15.3 across a
  run and across an open; path authorization (a path outside the run refused
  403, an empty path 400); the §12.6 file-moved path (404 with
  `reason: file_moved` on both endpoints, after actually renaming the folder out
  from under a loaded result); `locate_sources` re-linking, persisting to disk,
  re-authorizing the new paths and de-authorizing the old; and that the results
  JSON still parses and holds real grades afterwards.
- **`test_regress.py` — 16 checks, 16 passed.** Milestone 2 behaviours that could
  plausibly have been disturbed: §12.4 override leaves `total` unmutated while
  writing the three override fields, out-of-range and unknown-student refused,
  one-click revert clears all three and restores the computed value; §12.7 CSV
  still carries the computed/override/effective triple, one row per student; the
  §7.4 voxel floor still refuses 48; the empty-submissions-folder gate still
  refuses; `validate_paths` still flags a moved solution and counts parts.

### 2.4 UI verified in a real browser against the real server

Both themes. Confirmed on screen: the seven cards; the withheld-boost amber note;
a fully not-evaluated student rendering `—` in every column and "Not evaluated"
in every card with the error card above; a clean pass with an override showing
**Effective (overridden) 92.5** in cyan beside the preserved computed 100.0; and
a `source_path`-less row showing the explanation plus **Locate submissions
folder** instead of a dead button.

Accessibility, checked live: `aria-expanded` flips on the toggle, `aria-controls`
matches the detail row's id, **keyboard focus stays on the toggle across the
re-render** (`document.activeElement.id === 'sk-alpha-toggle'` after the click —
without this, expanding a row throws focus to the top of the document), every
icon-only and ambiguous control carries an `aria-label` naming the student, the
error dialog is a real `role="dialog" aria-modal="true"` that traps focus and
closes on Escape, and no status is encoded by colour alone.

Clicking **Open in SOLIDWORKS** in the page: button shows "Opening…", server
returns `read_only: true, unchanged: true`, button restores, file hash unchanged.
Clicking **Reveal in File Explorer**: `POST /api/reveal_file` → 200.

---

## 3. Findings

### 3.1 `sw_connection.py`'s open flags are wrong, and §15.3 point 1 has never been in force

**This is the most important thing in this report, and it is not a regression —
it predates this session.**

`sw_connection.py` lines 49–50:

```python
SW_OPEN_SILENT = 2       # swOpenDocOptions_Silent   — no UI prompts
SW_OPEN_READ_ONLY = 32   # swOpenDocOptions_ReadOnly — no save-back risk
```

Both constants are mislabelled. In `swOpenDocOptions_e`, **`Silent` is 1 and
`ReadOnly` is 2**; 32 is `AutoMissingConfig`. Verified live this session: opening
with 32 leaves `IsOpenedReadOnly` **False**, opening with 2 leaves it **True**.

That alone would be harmless — `2 | 32` still happens to contain the real
ReadOnly bit. The real problem is one layer down. `open_part_silent()`'s
strategy 1 is:

```python
doc = app.OpenDoc6(str(path), SW_DOC_PART, options, "", 0, 0)
```

`Errors` and `Warnings` are `[out]` parameters. Under late binding pywin32 has no
type info for the dynamic dispatch, sends them as `[in]` longs, and SOLIDWORKS
rejects the call. Measured directly:

```
OpenDoc6 failed ((-2147352571, 'Type mismatch.', None, 5)), trying OpenDoc2.
OpenDoc2 failed ((-2147352561, 'Parameter not optional.', None, None)), trying bare OpenDoc.
OpenDoc  (read-write fallback) succeeded
  IsOpenedReadOnly = False
```

So **every open in the grading path falls through all three strategies to the
bare read-write `OpenDoc`.** SPEC §15.3 point 1 — "reorder so `OpenDoc6` with
`Silent | ReadOnly` is tried first" — is written into the code and has never
actually executed. The reordering is real; the call it reorders to has always
failed.

**Student files are nevertheless safe, and demonstrably so.** What protects them
is §15.3 **point 2**: `grade_assignment.py` copies each submission to a scratch
directory, `chmod`s the copy read-only on the filesystem, grades the copy, and
deletes it. The original is never handed to SOLIDWORKS at all. That is why every
hash and mtime check has passed — twice in Milestone 2 and again here. The
defence in depth §15.3 asks for is missing; the load-bearing defence is intact.

The fix is small and now precisely understood — `SW_OPEN_SILENT = 1`,
`SW_OPEN_READ_ONLY = 2`, and BYREF `VARIANT`s for the two out-parameters, which
is exactly what the new endpoint does and what was verified working. **It was not
applied.** It changes the live-verified grading path (options would go from
`ReadOnly|AutoMissingConfig` to `Silent|ReadOnly`, and a genuinely read-only open
must be re-proven not to break the `SaveAs`-based STL export), it is not on the
agreed priority list, and proving it takes a full grading run. It should be the
first thing next session, or authorised now.

### 3.2 `output/` was not git-ignored

Grading output from a run-from-source lands in the repo's `output/`, which was
tracked. Those files carry student names, grades, and — as of this session —
absolute paths to every submission on disk. That is the same sensitivity `*.log`
is already excluded for. `output/` has been added to `.gitignore`.

Three files were **already committed** there before this session
(`Quiz3_grades.json`, `Quiz3_grades.csv`, `MT26_grades.xlsx`) and remain tracked —
adding an ignore rule does not untrack them. Whether to remove them from the
working tree or from history is the instructor's call, not a change to make
unasked.

### 3.3 A `print()` of `⚠` kills an entire grading run when stdout is not UTF-8

Hit accidentally. Running from source with stdout redirected to a file, Python
uses the locale encoding (cp1252 here), and `grade_assignment.py`'s `print("  ⚠
…")` raises `UnicodeEncodeError`. That exception escapes to
`_run_grading_thread`'s outer `except`, and the whole run is reported as failed
with the message `'charmap' codec can't encode character '⚠'`.

**The shipped app is not affected** — `app.py` opens its log file with
`encoding="utf-8"` when frozen and console-less. It bites anyone running from
source without `PYTHONIOENCODING=utf-8`. Reported, not fixed: it is unrelated to
this session's scope and the fix (a UTF-8 reconfigure at startup, or ASCII
markers) is a judgement call about the console output the instructor sees.

### 3.4 `IsOpenedReadOnly` and friends are properties, not methods, under dynamic dispatch

`doc.IsOpenedReadOnly()` raises `'bool' object is not callable`;
`doc.IsOpenedReadOnly` returns the bool. Same for `GetPathName` and `GetTitle`.
The new code reads the attribute and only calls it if it turns out callable, so
it works either way. Worth knowing before writing more `IModelDoc2` code.

---

## 4. What was NOT done, and why

- **The frozen build was not rebuilt.** A `SolidGradeDesktop2.exe` (PID 40692) is
  running and **holding a completed 26-student run in memory**. PyInstaller's
  COLLECT step deletes and recreates `dist/SolidGradeDesktop2/`, which cannot
  happen while that exe is running, and killing the instructor's app to make it
  possible is not a call to make unasked. **The Desktop shortcut therefore still
  launches Milestone 2 code.** The run's grades, CSV, reviewed CSV and STLs are
  safely on disk at `%LOCALAPPDATA%\SolidGrade\output\SolidGrade_Run`
  (verified: 26 students, `gradedAt` 2026-08-31T19:29:56Z). To pick up this
  session's work, close the app and run:

  ```bash
  pyinstaller --noconfirm SolidGradeDesktop2.spec
  ```

  No spec change was needed — no files were added under `ui/`, and every new
  import (`win32com.client.VARIANT`, `win32com.client.dynamic`, `pythoncom`) is
  already reachable from modules the existing build collects.

- **The webview window was not re-exercised.** `run_window()` and `main()` are
  untouched, and the single-instance guard would have focused the running frozen
  app rather than opening a second window. The UI was verified in a real browser
  against the same Flask server serving the same `ui/` files.

- **Items 2–4 were not started.** The kickoff asks for the ordering to be
  confirmed first.

---

## 5. Files changed

| File | Change |
|---|---|
| `grade_assignment.py` | `+17` — `students_folder`, `source_path`, schema docstring |
| `app.py` | `+~330` — three endpoints, the read-only open, path authorization, fingerprinting |
| `ui/app.js` | `+~490` — detail panel, row actions, expand state, focus restoration |
| `ui/styles.css` | `+127` — detail panel, using existing tokens only |
| `ui/index.html` | `+1` — one icon (`external-link`) |
| `.gitignore` | `+8` — `output/` |
| `tests/test_milestone3_row_actions.py` | new — the 36-check suite |
| `tests/test_milestone2_regressions.py` | new — the 16-check suite |

No new CSS custom properties, no new component vocabulary — the panel is built
from the tokens and card/banner language `SOLIDGRADE_WEB_REFERENCE.md` §7.1
already established in Milestone 2.
