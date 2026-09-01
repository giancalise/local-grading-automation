# SolidGrade Desktop — Milestone 3 Report: Results Depth

Session dates: 2026-08-31 – 2026-09-01. Follows `MILESTONE_2_REPORT.md`.

Builds **item 1** of the agreed priority list in `NEXT_SESSION_PROMPT.md` —
per-student detail plus the two §12.6 row actions the instructor chose — and
none of items 2–4, whose ordering the instructor confirmed at the end of the
session (2, then 3, then 4).

Two defects found along the way were fixed **on the instructor's explicit
authorisation**, because both destroy or silently weaken real work:

- **§3.1** — SPEC §15.3 point 1 (open student files read-only) had never
  actually executed, in any milestone. Fixed and verified.
- **§3.3** — a `print()` of a `⚠` glyph threw away a **completed** grading run
  on the frozen build. Reproduced, fixed, and re-verified.

The frozen app was rebuilt so the Desktop shortcut carries all of it.

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

### 3.1 §15.3 point 1 had never actually run — found, and FIXED

**This is the most important thing in this report. It is not a regression — it
predates every milestone — and it is now fixed and verified.**

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

#### The fix, applied and verified

Authorised by the instructor during this session. Two changes in
`sw_connection.py`, both commented in place:

1. `SW_OPEN_SILENT = 1`, `SW_OPEN_READ_ONLY = 2`.
2. `Errors` and `Warnings` passed as real BYREF `VARIANT`s.

A third change makes the failure mode loud rather than silent: after any open,
`IsOpenedReadOnly` is read back, and a writable document logs a
`SPEC §15.3` warning naming the file. The read-write fallbacks (`OpenDoc2`,
bare `OpenDoc`) were **kept** — removing them would turn a difficult file into a
hard grading failure, and grading only ever hands SOLIDWORKS a read-only scratch
copy anyway. What changed is that reaching one can no longer go unnoticed, which
is precisely why this survived three milestones.

**The risk that had to be retired first** was whether a genuinely read-only
document still supports the `SaveAs`-based STL export. Measured directly against
a scratch copy prepared exactly the way `grade_assignment.py` prepares one
(copied, then `chmod` read-only):

| Check | Result |
|---|---|
| `OpenDoc6 (Silent\|ReadOnly)` succeeds — strategy 1, no fallback | **PASS** (`errors=0`) |
| `IsOpenedReadOnly` | **True** — §15.3 point 1 now genuinely in force |
| `ForceRebuild3` on the read-only document | **PASS** |
| **STL export on the read-only document** | **PASS** — 274,784 bytes |
| Scratch copy byte-identical | **PASS** |
| Original byte-identical | **PASS** |

Then a full grading run through `/api/run_grading`, followed by both suites:

| Check | Result |
|---|---|
| Grades unchanged by the fix | **PASS** — 85.0/100, same four check verdicts |
| STLs still produced | **PASS** — 3 × 274,784 bytes |
| Plagiarism pass still fires | **PASS** |
| Zero `SPEC §15.3` warnings, i.e. every open took strategy 1 | **PASS** |
| `tests/test_milestone3_row_actions.py` | **36 passed, 0 failed** |
| `tests/test_milestone2_regressions.py` | **16 passed, 0 failed** |

#### A timing change that is NOT established, and should not be quoted as one

`Silent` was never actually being set — the old constant put a 2 where a 1
belonged — so with it genuinely set, SOLIDWORKS should stop raising the dialogs
the popup dismisser was polling for and clicking away.

**What is solid:** the popup dismissals went to zero. Pre-fix logs show
`Auto-dismissed: title='SOLIDWORKS Design'` events; the post-fix run logged
none. That is directly attributable to the flag and is exactly what setting
`Silent` should do.

**What is not solid: the speed.** Measured, all on the same two-file fixture and
the same machine:

| Build | Per-file |
|---|---|
| From source, before the fix | 48.9 s, 51.1 s |
| From source, after the fix | 23.2 s, 23.2 s |
| **Frozen build, after the fix** | **110.3 s, 75.2 s** |

The from-source A/B looks like a 2× win. The frozen run immediately afterwards
was **slower than anything measured this session**, and slower than Milestone 2's
55.5 s frozen figure for the same fixture. So whatever the flag does, it is
swamped by something larger — frozen-vs-source overhead, and most likely the R-7
degradation that `MILESTONE_2_REPORT.md` §6.1 documents, since SOLIDWORKS had by
then been open and heavily exercised for hours of testing.

**Conclusion: one run per condition proves nothing about throughput.** The
popup-dismissal count is a real, mechanistic improvement. The per-file timing is
noise at this sample size and the 2× reading is not supported. Do not plan around
it. The per-file numbers are already in the progress display; read them off the
next real 26-student run, which is the only sample that would settle it.

### 3.2 `output/` was not git-ignored

Grading output from a run-from-source lands in the repo's `output/`, which was
tracked. Those files carry student names, grades, and — as of this session —
absolute paths to every submission on disk. That is the same sensitivity `*.log`
is already excluded for. `output/` has been added to `.gitignore`.

Three files were **already committed** there before this session
(`Quiz3_grades.json`, `Quiz3_grades.csv`, `MT26_grades.xlsx`); adding an ignore
rule does not untrack an already-tracked file. On the instructor's instruction
they were removed from the index with `git rm --cached`, so they are no longer
tracked and the `output/` rule now covers them. **They are still in git
history** — purging that would need a rewrite (`git filter-repo` or equivalent)
and a force-push, which is a separate decision and was not done.

**A trap that fired, and is worth knowing.** "`git rm --cached` keeps the file on
disk" is true only until the branch is merged. Merging into `main` — where the
files were still tracked — replayed the deletion against a working tree that
*did* have them, and git removed all three from disk. Nothing was lost (they are
in every commit up to `5290e20`) and they were restored with:

```bash
git checkout 5290e20 -- output/
```

followed by `git rm --cached -r output/` again to leave them untracked. Verified
byte-identical afterwards by comparing `git hash-object` against
`git rev-parse 5290e20:<path>` for each. The general lesson: untracking a file on
a branch means the *merge* deletes the working copy, so back up anything that
exists only on disk before merging such a change.

### 3.3 A `print()` of `⚠` destroys a completed grading run — found, and FIXED

Hit by accident, then reproduced deliberately on the **frozen build**, which is
what makes it serious.

`grade_assignment.py` prints `"  ⚠ PLAGIARISM: ..."` in PHASE 2 and
`"  ⚠ Recovered from SW stall"` in PHASE 1. If `sys.stdout` cannot encode
U+26A0 — any Windows console or inherited pipe on a cp1252 locale — `print()`
raises `UnicodeEncodeError`. Nothing catches it near where it is raised: it
propagates out of PHASE 2, past `_run_grading_thread`'s outer handler, and the
run is reported as `"error"`. **PHASE 3 never runs, so the results JSON is never
written and every grade is lost**, even though all the grading itself succeeded.

Reproduced live on `dist\SolidGradeDesktop2\SolidGradeDesktop2.exe` after this
session's rebuild: both students graded correctly, both were flagged for a shared
author, the plagiarism print fired, and the run died with
`'charmap' codec can't encode character '⚠' in position 2`. Two students'
completed work, discarded.

**An earlier draft of this report said the shipped app was unaffected. That was
wrong.** `app.py` redirects to a UTF-8 log only when `sys.stdout is None`, which
is the `--noconsole` shortcut case. Launch the same exe from a terminal and it
inherits an encodable-only-in-cp1252 stdout, and the bug is live. What matters is
whether stdout can encode, not whether the app is frozen.

**Fixed** in `app.py`, immediately after the existing redirect: both streams get
`reconfigure(errors="replace")`, so the glyph degrades to `?` on a console that
cannot render it. `errors="replace"` rather than forcing an encoding, because the
goal is that no printable character can ever again cost a run.

Verified two ways:

| Check | Result |
|---|---|
| Reproduce the failure: cp1252 stdout, `errors="strict"`, the exact PHASE 2 plagiarism line | **raises `UnicodeEncodeError`** |
| After `app.py` loads, same stream | `errors` is `replace`; the line prints as `  ? PLAGIARISM: alpha ? bravo (author=GCE4)` and **does not raise** |
| Rebuild, then re-run the identical two-student job on the frozen `.exe` from a terminal — the exact condition that destroyed it | **complete**, both students 85.0, both plagiarism-flagged, `source_path` and `students_folder` recorded |

**Worth noting for item 2**: checkpointing would have made this survivable
independently — records persisted as they arrive cannot be lost by a crash in
PHASE 2. This is a concrete argument for the next milestone.

### 3.4 `IsOpenedReadOnly` and friends are properties, not methods, under dynamic dispatch

`doc.IsOpenedReadOnly()` raises `'bool' object is not callable`;
`doc.IsOpenedReadOnly` returns the bool. Same for `GetPathName` and `GetTitle`.
The new code reads the attribute and only calls it if it turns out callable, so
it works either way. Worth knowing before writing more `IModelDoc2` code.

---

## 4. Rebuilt, and what was still not done

- **The frozen build WAS rebuilt** — twice, and the second one is what ships.
  The first rebuild happened once the instructor closed the
  `SolidGradeDesktop2.exe` that had been holding a completed 26-student run in
  memory (PyInstaller's COLLECT step deletes and recreates
  `dist/SolidGradeDesktop2/`, so it could not run while that exe was alive). The
  §15.3 fix in §3.1 landed after that, so it was rebuilt again. Verified before
  touching `dist/`: no `output/` directory or any `.json`/`.csv`/`.stl` inside
  it, and the 26-student run intact at
  `%LOCALAPPDATA%\SolidGrade\output\SolidGrade_Run` (26 students, `gradedAt`
  2026-08-31T19:29:56Z, STLs present).

  No spec change was needed — no files were added under `ui/`, and every new
  import (`win32com.client.VARIANT`, `win32com.client.dynamic`, `pythoncom`) is
  already reachable from modules the existing build collects.

  **A trap worth recording**: `pyinstaller` is installed only inside
  `.venv312\Scripts\` and is not on PATH, so a bare `pyinstaller` in a terminal
  fails with "command not found". The command that works from the repo root is:

  ```bash
  .venv312/Scripts/pyinstaller.exe --noconfirm SolidGradeDesktop2.spec
  ```

  **The shipped build was verified, not just produced.** A full grading job was
  run through the rebuilt `.exe`: complete, both students 85.0 with the same four
  check verdicts, both plagiarism-flagged, `source_path` and `students_folder`
  recorded, student files and solution still `899c98038d1ee227…`. Both suites
  were then run against the frozen server — **36 + 16, all green** — including
  the check that results land in `%LOCALAPPDATA%\SolidGrade\output` and not
  inside `dist/`. Shut Down exited cleanly with no stray `.stl_prefs_backup.json`.

- **The webview window itself was not re-exercised.** The rebuilt `.exe` was
  driven through its HTTP surface, and the UI was verified in a real browser
  against the same `ui/` files the build bundles, but `run_window()` — untouched
  this session — was not opened and closed by hand again.

- **Items 2–4 were not started.** The instructor confirmed the ordering at the
  end of the session: **item 2 (live results table + §11.1 checkpointing) is
  next.** It was not begun here.

---

## 5. Files changed

| File | Change |
|---|---|
| `grade_assignment.py` | `+17` — `students_folder`, `source_path`, schema docstring |
| `app.py` | `+~355` — three endpoints, the read-only open, path authorization, fingerprinting, and the §3.3 stdout hardening |
| `ui/app.js` | `+~490` — detail panel, row actions, expand state, focus restoration |
| `ui/styles.css` | `+127` — detail panel, using existing tokens only |
| `ui/index.html` | `+1` — one icon (`external-link`) |
| `sw_connection.py` | `+~40` — the §15.3 flag and BYREF fix, plus a warning when an open is writable |
| `.gitignore` | `+8` — `output/` |
| `tests/test_milestone3_row_actions.py` | new — the 36-check suite |
| `tests/test_milestone2_regressions.py` | new — the 16-check suite |

No new CSS custom properties, no new component vocabulary — the panel is built
from the tokens and card/banner language `SOLIDGRADE_WEB_REFERENCE.md` §7.1
already established in Milestone 2.
