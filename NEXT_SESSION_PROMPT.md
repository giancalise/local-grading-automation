# Next Session — Milestone 4 Kickoff

**Updated:** 2026-09-01, at the end of the Milestone 3 session (results depth).
That session produced `MILESTONE_3_REPORT.md`, the per-student detail panel, the
§12.6 row actions, the `source_path` / `students_folder` prerequisite, the two
committed verification suites under `tests/`, and the §15.3 open-flag fix.

**Item 1 is done. Item 0 was found and fixed. The instructor has confirmed the
ordering: item 2 is next.**

**Status going in:** the frozen app was rebuilt and now carries everything from
this session — the Desktop shortcut runs current code. A full grading run was
completed on the rebuilt `.exe`. `output/` is git-ignored and the three
previously-committed grading files are untracked.

---

## The priority list — ordering confirmed 2026-09-01

Ordered, and **the ordering of 2–4 was confirmed by the instructor on
2026-09-01**: item 2 next, then 3, then 4. Item 1 is built (Milestone 3). The
item 0 that Milestone 3 turned up was authorised and fixed in the same session —
it is recorded below as closed, not as work.

### 1. Results depth — **BUILT, Milestone 3. See `MILESTONE_3_REPORT.md`.**

> Delivered in full: the `source_path` / `students_folder` prerequisite, the
> seven-card per-student detail panel (including the volume-coupled boost
> explanation and the underdefined sketch names), both chosen row actions, no
> "save a copy", and a `locate_sources` action so results graded before the
> change are not permanently inert. 36 API/§15.3 checks and 16 Milestone 2
> regression checks pass, and the frozen build was rebuilt and re-run, so the
> Desktop shortcut carries all of it.
>
> The original specification is kept below for reference.



The results table currently shows a verdict glyph per check and nothing behind
it. Everything below is *already in the result JSON* and simply unsurfaced, so
this is mostly display work over existing data.

**Per-student detail, expandable from the row:**

| Group | Show |
|---|---|
| Form | `shape_score` to 3 dp, the 0.95 threshold, and **whether the volume-coupled full-credit boost applied** (`compute_grade` gives full shape credit only when `shape_score >= threshold` AND volume is `PASS` — today that is invisible and confusing) |
| Volume | student `volume_mm3` vs solution, absolute and % delta, against the ±1 % tolerance |
| Material | student `material` vs the solution's, side by side |
| Sketches | the **actual names** in `underdefined_sketches` — currently thrown away in the UI, and they are the single most actionable thing on the screen |
| Mass | `mass_kg` |
| Provenance | `sw_author`, `last_saved_date` |
| Points | the `shape_points` / `volume_points` / `material_points` / `sketch_points` breakdown summing to `total` |
| Errors | the `error` string in full when present |

**Row actions — instructor chose BOTH, and deliberately not a third:**

- **Open in SOLIDWORKS, read-only** — §12.6's own answer. Note §12.6 said this
  "is only safe once §15.3 lands"; §15.3 **has** landed and was re-verified in
  Milestone 2 (student files byte-identical, mtime untouched), so this is now
  unblocked. Needs a graceful "file moved" path.
- **Reveal in File Explorer** — `explorer /select,"<path>"`. No COM, trivial.
- **"Save a copy" was considered and NOT chosen**, keeping §12.6's "no cached
  copies — that multiplies the FERPA surface" intact. Do not add it silently.

**Prerequisite, do this first:** the result record stores `filename` (basename
only) — there is no absolute path to open. Add **both** `students_folder` at the
result root and `source_path` per student record. Note the consequence: results
graded before this change (including the recovered `HW3-06-0194`) have neither,
so either offer a "locate the submissions folder" action for old results or
accept that row actions are disabled on them.

### 2. Live results table + §11.1 checkpointing — **NEXT. Confirmed 2026-09-01.**

> Start here. Milestone 3 produced a second, concrete argument for it: a
> `print()` of a ⚠ glyph destroyed a **completed** two-student run on the frozen
> build — all grading succeeded, PHASE 2 raised, PHASE 3 never wrote the JSON,
> every grade lost (`MILESTONE_3_REPORT.md` §3.3). That specific bug is fixed,
> but the shape of the failure is exactly what checkpointing exists to survive:
> anything that raises after the loop currently costs the whole run.


These are **one change, not two**, and that is the main reason to do them
together. `progress_callback` already fires immediately after
`all_results.append(record)` at [grade_assignment.py:604](grade_assignment.py:604)
with the full record in scope; passing it through is close to a one-line change.
Once records stream out of the loop:

- the results table can fill in row by row as grading proceeds (what the
  instructor asked for — today the Results tab shows only a spinner and
  "N of M" during a run), and
- persisting each record as it arrives **is** the checkpoint.

Today the results JSON is written exactly once, in PHASE 3 at
[grade_assignment.py:667](grade_assignment.py:667), after the entire loop and
the plagiarism pass. A crash at student 25 of 26 loses all 25. At the measured
**~205 s/student** (see `MILESTONE_2_REPORT.md` §6.1) a 26-student run is ~85
minutes with no resume. This is the largest remaining fragility in the product.

**Caveat to design around, not discover:** plagiarism flags are computed in
PHASE 2 *after* every student is graded. Live rows can show every check and the
grade, but the plagiarism column must render as explicitly pending until the run
completes — not as "clean".

### 3. Configurable criteria — **third**, confirmed 2026-09-01

Required by SPEC §10 step 4 ("effective criteria with live toggles and weights…
applies to this run only; the effective set is embedded in the result record")
and §7.5, which names the sketch check specifically: *"currently hardcoded
all-or-nothing; make configurable"*. **Milestone 2 built this card as read-only
display — it is a stub, and should be treated as unfinished work rather than a
new feature.**

Instructor's ask: a checkbox to turn each check on or off, and an editable
percentage weight per check.

Three things that make this bigger than it looks:

1. **`compute_grade()` reads module-level constants** (`WEIGHT_SHAPE`,
   `WEIGHT_VOLUME`, `WEIGHT_MATERIAL`, `WEIGHT_SKETCHES`, `SHAPE_THRESHOLD`).
   Thread a criteria dict through the same additive way `voxel_resolution` was
   done in Milestone 2 — do not mutate module globals from a request thread.
2. **"Off" is a fourth state, and must not be confused with the existing three.**
   SPEC §15.1's `NOT_EVALUATED` means "we tried and could not tell", forces
   `needs_review`, and must never render as 0. A *disabled* check means "the
   instructor decided this does not count" — it should not force review and
   should not appear as a failure. Four states: pass / fail / not-evaluated /
   disabled. Getting this wrong silently corrupts grades.
3. **Weights must renormalize.** Turning a check off has to redistribute its
   weight or the totals stop summing to 100. Decide explicitly — renormalize
   across remaining checks, or let the total shrink — and show the instructor
   which is happening.

Also from §7.5, while in here: the sketch check's "underdefined allowed"
threshold should become an integer (default 0), not a boolean.

### 4. Multi-part problems — **fourth**, confirmed 2026-09-01

Instructor's ask: a plus button on the run setup screen that adds another
solution file and another submissions folder, repeatable.

This is the largest of the four and the only one that **changes a contract
shared with the web app**, so it needs a decision before it needs code:

- `grade_assignment()` is single-solution / single-folder by signature.
- The results schema in `SOLIDGRADE_WEB_REFERENCE.md` §6.4 has **no parts
  array** — `students[]` carries one flat set of checks. The job document
  (§6.3) already has `assignmentType: 'single' | 'multi'` and a
  `solutionsStoragePath`, so the web app anticipates multi-part but the results
  shape does not model it.
- SPEC §12.1 wants "one column per part" with the frozen student-name column and
  expandable sub-criteria columns.

Two credible designs: N sequential single-part runs stitched into one result, or
a real `students[].parts[]` schema change. The second is correct and the first is
cheaper. **Do not pick by default — this one touches the web app.**

---

## Closed in Milestone 3 — recorded so it is not rediscovered

### 0. §15.3 point 1 had never run. Found, fixed, verified. ✅

`sw_connection.py` had `SW_OPEN_SILENT = 2` and `SW_OPEN_READ_ONLY = 32`; in
`swOpenDocOptions_e`, `Silent` is 1 and `ReadOnly` is 2 (32 is
`AutoMissingConfig`). Separately, `open_part_silent()` passed `OpenDoc6`'s two
`[out]` parameters as plain `0, 0`, which fails with "Type mismatch" under late
binding — so every grading open fell through to the bare read-write `OpenDoc`
with `IsOpenedReadOnly` **False**. §15.3 point 1 was written into the code and
had never once executed. Student files were safe throughout because §15.3
point 2 (the filesystem-read-only scratch copy) is what actually protects them.

**Fixed and verified in Milestone 3** on the instructor's authorisation:
constants corrected, BYREF `VARIANT`s for the out-params, and a `SPEC §15.3`
warning logged if any open ever produces a writable document. The read-write
fallbacks were kept deliberately — grading only ever hands over a scratch copy,
and a hard failure on a difficult file would be worse — but reaching one is no
longer silent.

Proven before shipping: `IsOpenedReadOnly` True, **the `SaveAs`-based STL export
still works on a read-only document** (274,784 bytes), grades and STLs unchanged
by the fix, zero §15.3 warnings across a full run, and both suites green
(36 + 16).

**One measurement to take next session, and one claim NOT to repeat.** Popup
dismissals fell to **zero** after the fix — solid, and exactly what setting
`Silent` should do. Per-file timing is *not* settled: from source it went
48.9/51.1 s → 23.2/23.2 s, but the frozen build right afterwards measured
**110.3 s and 75.2 s** — slower than anything else this session and slower than
Milestone 2's 55.5 s frozen figure. One run per condition, with SOLIDWORKS hours
into heavy use (R-7 degradation, `MILESTONE_2_REPORT.md` §6.1). **Do not plan
around a speedup.** Just read the per-file numbers off the next real 26-student
run — they are already in the progress display — and settle it there.

---

## Standing items, not displaced by the above

- **§11.3 `sw_timeout` stall recovery.** Still unbuilt, still the sharpest pure
  correctness risk: a genuine COM stall hangs the app forever with no recovery.
  Milestone 1 proved the thread-based implementation corrupts the STA
  connection, so it needs the redesign (COM marshaling, or a watchdog that only
  ever kills the SOLIDWORKS *process*) — verified live, not by static review.
  **This was offered as the first priority and the instructor chose Results
  depth instead.** Recorded so the trade-off is visible, not to relitigate it.
- **§9 ingestion and attribution** — still the largest unbuilt subsystem.
- **A dedicated COM worker thread** — `_com_lock` is adequate, not the right
  long-term architecture.
- **Regenerate the `HW3-06-0194` STLs** if the web app's 3-D viewer needs them
  (see `MILESTONE_2_REPORT.md` §5 — they were destroyed by a rebuild; every
  grade survives in the recovered JSON).
- **Packaging traps** — three stale `.spec` files lack the Milestone 2
  `datas`/`hiddenimports`, and `.gitignore` excludes `*.spec` entirely, so the
  packaging fix is untracked and a fresh clone cannot build a working app.
- **`pyinstaller` is not on PATH** — it lives only in `.venv312\Scripts\`, so a
  bare `pyinstaller` fails with "command not found". Rebuild with:

  ```bash
  .venv312/Scripts/pyinstaller.exe --noconfirm SolidGradeDesktop2.spec
  ```

  Close any running `SolidGradeDesktop2.exe` first — COLLECT deletes and
  recreates `dist/SolidGradeDesktop2/` and cannot while the exe is alive.
- **Student data is still in git history.** `output/` is now ignored and
  `Quiz3_grades.json`, `Quiz3_grades.csv` and `MT26_grades.xlsx` were untracked
  with `git rm --cached` (Milestone 3), so nothing new joins them and they are
  still on disk — but **the earlier commits still contain them**. Purging that
  needs a history rewrite (`git filter-repo`) and a force-push. Open decision.
- **FIXED in Milestone 3:** a `print()` of `⚠` destroyed a *completed* grading
  run on the frozen build — all students graded, PHASE 2 raised
  `UnicodeEncodeError`, PHASE 3 never wrote the JSON. `app.py` now sets
  `errors="replace"` on both streams. `MILESTONE_3_REPORT.md` §3.3. Kept here
  because the *shape* of that failure — anything raising after the grading loop
  costs the entire run — is the case for item 2.
- **Surface `popup_dismisser`'s `dismissal_count` / `check_integrity_parity()`**
  in the System Ready panel (Milestone 1 item 8, built but never wired up).
- **§7.2 ⑦** — the installer / SOLIDWORKS-path prompt / account login gap
  between the web app's Grading Automation page and what actually ships.
  Deliberately deferred; decide alongside §9.

---

## What must not regress

Re-verify anything a change could plausibly touch. These were verified live in
Milestone 2 against the frozen `.exe`, and re-verified in Milestone 3 against the
source tree (`MILESTONE_3_REPORT.md` §2).

**Two runnable suites cover most of this list** — `tests/test_milestone3_row_actions.py`
(36 checks: the §15.3 invariant across both a run and an open, path
authorization, the file-moved path, `locate_sources`) and
`tests/test_milestone2_regressions.py` (16 checks: overrides, CSV, the voxel
floor, the run gate, path validation). Both need a live dev server holding a
completed run plus SOLIDWORKS; their headers say how. Run them before and after
any change to `app.py`, `grade_assignment.py` or `sw_connection.py`.

- **§15.3** student files byte-identical across a run, mtime untouched
  (`test_underdefined.SLDPRT` = `899c98038d1ee227b2d12d7194f0e2cb7c86148d9baeb4453c1776b264ef995f`).
  **The results view now opens student files in SOLIDWORKS.** That open is
  read-only by construction, asks SOLIDWORKS to confirm it (`IsOpenedReadOnly`),
  refuses rather than falling back to a writable mode, and hashes the file either
  side of every open. Do not add a read-write fallback, and do not add a "save a
  copy" action (§12.6 / §13 forbid it).
- **The row-action endpoints must stay scoped to the loaded result's own files.**
  `/api/open_in_solidworks`, `/api/reveal_file` and `/api/locate_sources` refuse
  any path that is not a `source_path` in the loaded result or its solution.
  Widening that turns them into a general file-launching primitive.
- **§15.1** three-state checks return `null`, never `0`, on genuine failure, and
  never render as `0`.
- The status check must not launch SOLIDWORKS as a side effect —
  `sw_detect.is_running()` uses `GetActiveObject` only.
- Shut Down releases COM handles, stops the popup dismisser, restores STL
  preferences, and exits; **closing the window does the same** (window lifetime
  is app lifetime — this is what fixed the abandoned-tab / never-exiting-server
  problem, do not reintroduce a path that leaves the server running).
- A refresh restores picked paths, in-flight progress, and finished results.
- **Grading results must never be written inside `dist/`.** They go to
  `%LOCALAPPDATA%\SolidGrade\output` via `results_root()`. A PyInstaller rebuild
  deletes `dist/` wholesale and has already destroyed one real run's STL set.

---

## The prompt

> Claude Code Session — SolidGrade Desktop, Milestone 4: live results + checkpointing
>
> Read `MILESTONE_3_REPORT.md` first (what shipped, what was verified live, and
> §3.1 — the §15.3 fix and the timing change it produced), then this file.
>
> Build **item 2**: stream each student record out of the grading loop as it is
> produced, so the results table fills in row by row AND each record is
> persisted as it arrives. These are one change, not two —
> `progress_callback` already fires immediately after `all_results.append(record)`
> at [grade_assignment.py:604](grade_assignment.py:604) with the full record in
> scope. Today the results JSON is written exactly once, after the whole loop
> and the plagiarism pass, so a crash at student 25 of 26 loses all 25.
>
> **Design around this, do not discover it:** plagiarism flags are computed in
> PHASE 2 *after* every student is graded, so a live row must render its
> plagiarism column as explicitly **pending** until the run completes — never as
> "clean". The results view already has a three-state vocabulary and a
> not-evaluated style to build that from; do not invent a fourth look.
>
> Reuse the existing endpoints and the Milestone 3 detail panel — a row that
> arrives live should expand to the same seven cards. Style per
> `SOLIDGRADE_WEB_REFERENCE.md` using the tokens already in `ui/styles.css`, and
> keep the accessibility standard: real focus rings, focus that survives a
> re-render, real dialogs, no colour-only status.
>
> Do not regress what Milestones 2 and 3 verified live — the list is under
> "What must not regress" below. Run `tests/test_milestone3_row_actions.py` and
> `tests/test_milestone2_regressions.py` before and after; their headers say how.
>
> While you are in the grading loop, read the per-file timings off the next real
> run and tell me what per-file cost actually looks like now — Milestone 3's
> numbers contradict each other and settled nothing.

## Note for whoever writes the next one

The instructor has said there are further items to add to this list beyond the
four captured here. Ask before assuming this list is complete.
