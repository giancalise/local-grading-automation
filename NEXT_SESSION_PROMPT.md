# Next Session — Milestone 3 Kickoff

**Written:** 2026-08-31, at the end of the Milestone 2 session (the real UI).
That session produced `MILESTONE_2_REPORT.md`, the `ui/` folder, the webview
shell, and a rebuilt `dist/SolidGradeDesktop2`.

**Previous contents of this file** (the Milestone 2 kickoff) are superseded —
that session is done.

**Status going in:** the instructor has run a full grading job from the Desktop
shortcut, through the new app shell, start to finish, successfully. That closes
the last thing Milestone 1 left unverified.

---

## The priority list, as agreed 2026-08-31

Ordered. Items 1 and the open/reveal decision inside it were chosen by the
instructor this session; the ordering of 2–4 is **proposed, not yet agreed** —
confirm before starting anything below item 1.

### 1. Results depth — **AGREED as the first thing to build**

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

### 2. Live results table + §11.1 checkpointing — *proposed second*

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

### 3. Configurable criteria — *proposed third*

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

### 4. Multi-part problems — *proposed fourth*

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
- **Surface `popup_dismisser`'s `dismissal_count` / `check_integrity_parity()`**
  in the System Ready panel (Milestone 1 item 8, built but never wired up).
- **§7.2 ⑦** — the installer / SOLIDWORKS-path prompt / account login gap
  between the web app's Grading Automation page and what actually ships.
  Deliberately deferred; decide alongside §9.

---

## What must not regress

Re-verify anything a change could plausibly touch. All of these were verified
live in Milestone 2 against the frozen `.exe`:

- **§15.3** student files byte-identical across a run, mtime untouched
  (`test_underdefined.SLDPRT` = `899c98038d1ee227b2d12d7194f0e2cb7c86148d9baeb4453c1776b264ef995f`).
  **Item 1 opens student files in SOLIDWORKS — this is exactly the invariant it
  could break. Opens must stay read-only and must be hash-checked after.**
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

> Claude Code Session — SolidGrade Desktop, Milestone 3: results depth
>
> Read `MILESTONE_2_REPORT.md` first (what exists, what was verified live, and
> the §5 data-loss postmortem), then `NEXT_SESSION_PROMPT.md` for the agreed
> priority list, then the relevant parts of `SOLIDGRADE_WEB_REFERENCE.md` (§3
> component patterns, §3.6 modals, §12 in the SPEC) and
> `SPEC_v0.2_SolidGrade_Desktop.md` §12.
>
> Build item 1 — results depth — as specified in `NEXT_SESSION_PROMPT.md`:
> the per-student detail view over data already in the result JSON, plus the two
> row actions the instructor chose (Open in SOLIDWORKS read-only, Reveal in File
> Explorer) and explicitly *not* a third (no "save a copy" — §12.6 FERPA).
> Do the `source_path` / `students_folder` prerequisite first.
>
> Style everything per `SOLIDGRADE_WEB_REFERENCE.md`, reusing the tokens and
> component classes already in `ui/styles.css` rather than inventing new ones,
> and keep the accessibility standard Milestone 2 set (real focus rings, real
> dialogs with focus trapping and Escape, no colour-only status encoding,
> aria-labels on icon-only controls).
>
> Reuse the existing Flask endpoints. Adding an endpoint for opening/revealing a
> file is expected; redesigning the existing surface is not.
>
> Do not regress what Milestone 2 verified live — the list is in
> `NEXT_SESSION_PROMPT.md` under "What must not regress". **Opening student
> files in SOLIDWORKS is the specific risk this session introduces to §15.3:
> hash every student file before and after, and prove opens stay read-only.**
>
> Confirm the ordering of items 2–4 with me before starting any of them.

---

## Note for whoever writes the next one

The instructor has said there are further items to add to this list beyond the
four captured here. Ask before assuming this list is complete.
