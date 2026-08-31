# SolidGrade Desktop — Milestone 1 Report: Walking Skeleton

**Machine:** Windows 11 Enterprise, SolidWorks 3DEXPERIENCE R2026x installed (product name "SOLIDWORKS Design Premium 2026 SP3.0"), enterprise-managed (CrowdStrike, Zscaler, Avecto, ForeScout, DeviceLock present).
**Session date:** 2026-08-28.
**Scope:** As defined in the session prompt — repo hygiene, live COM validation, correctness invariants (§15), packaging skeleton with startup self-test (§2, §2.4), SolidWorks detection (§3.2), minimal single-screen UI and one grading run. Assignments, rosters, ingestion/attribution, the results table, overrides, checkpointing, criteria config UI, thumbnails, export/import, the form/scale split, the 24-permutation search, and performance work are all explicitly out of scope and were not built.

---

## Step 1 — Live COM validation (§16.5)

All three questions were answered empirically on this machine, and one additional live investigation (the sketch DISPID probe, §16.1) was carried out since a working SolidWorks 3DEXPERIENCE/Desktop-flavored install was available.

### 1. Does `Dispatch("SldWorks.Application")` launch SolidWorks when not running?

**Yes, but the launch is unreliable on this machine's edition, and the failure mode matters.**

With `SLDWORKS.exe` confirmed absent from the process list, calling `win32com.client.dynamic.Dispatch("SldWorks.Application")` from the venv Python:

- **Does** spawn `sldworks.exe` (confirmed via `Get-Process`/`tasklist`; the spawned process command line includes `-Embedding`, the flag Windows COM activation adds — direct evidence the process came from `CoCreateInstance`, not a stray launch).
- **Does not** reliably produce a working automation object. Three separate attempts all raised `pywintypes.com_error: (-2146959355, 'Server execution failed', ...)` (`CO_E_SERVER_EXEC_FAILURE`) after 58s, 120s, and 120s respectively.
- **Root cause, found by direct investigation of the spawned process's windows:** a modal dialog appears — class `#32770`, title exactly `"SOLIDWORKS"` (not the historically-documented `"SOLIDWORKS Design"`), buttons `&Yes` / `&No`. With no dismisser armed before the `Dispatch()` call (the existing `sw_connection.py` only starts the dismisser inside `open_part_silent`, never in `connect()`), this dialog sits unanswered; SolidWorks' own internal activation timeout eventually fires (~60–130s) and the process exits, which is what the client sees as `SERVER_EXEC_FAILURE`.
- **Clicking either button killed the process** — both `&Yes` and `&No` were tried (on separate instances) and both led to process exit within seconds. This is not a benign "nag" dialog; it behaves like a fatal-condition prompt.
- **The actual root cause, found by comparing launch paths:** this machine's SolidWorks is a 3DEXPERIENCE-platform integration, not a plain Desktop install. The real Start Menu shortcut (`SOLIDWORKS Design.lnk`) does not launch `sldworks.exe` directly — it launches `CATSTART.exe -run "SWXDesktopLauncher.exe" -object "--AppName=... -tenant=R1132101102931 -monoapp -3DRegistryURL=https://us1-registry.3dexperience.3ds.com" -nowindow`. This bootstraps a platform/tenant authentication handshake before `sldworks.exe` ever starts. COM's registered `LocalServer32` for `SldWorks.Application` points straight at `sldworks.exe`, **skipping that bootstrap entirely**. A raw `Dispatch()` call (or a direct `sldworks.exe` launch) reaches SolidWorks in a state the platform-auth flow was supposed to precede, which is what the `#32770` dialog appears to be reacting to.
- **Confirmed fix:** launching via the real Start Menu shortcut (`os.startfile()` on the `.lnk`) worked reliably every time it was tried (3/3), reaching the real main window (`"SOLIDWORKS Design Premium 2026 SP3.0"`) in 15–20s with no dialog. This is what `sw_detect.launch_solidworks()` now does (falling back to the direct exe only if no shortcut can be found, with a caveat noted in its response).

`pythoncom.GetActiveObject("SldWorks.Application")` / `win32com.client.GetActiveObject(...)`:

- **Confirmed to never launch anything.** With SW closed, both raise `com_error (-2147221021, 'Operation unavailable')` (`MK_E_UNAVAILABLE`) instantly, and no process appears.
- **Confirmed to attach instantly and correctly** when SW is genuinely running (0.01–0.02s), returning `RevisionNumber='34.3.0'`, `ApplicationType=1`.

**Decision this drives:** §3.2's "running" detector uses `GetActiveObject` only, never `Dispatch`, exactly as the spec's "critical correction to v0.1" already concluded from static analysis — now confirmed live. The "Launch" action does **not** use `Dispatch()` to launch; it shells out to the real Start Menu shortcut. See `sw_detect.py`.

### 2. Is `SummaryInfo(5)` last-saved-by or author?

**Last-saved-by**, confirmed two ways:

- Running `diag_props.py` (adapted to point at the bundled `test_underdefined.SLDPRT` — its original hardcoded path, `C:\Users\gce4\Box\ES-19\...`, does not exist on this machine) against the live file: indices 0–4 are **all empty**, index 5 = `'GCE4'` (this machine's own Windows account), index 6/8 = created date `5/27/2022`, index 7/9 = saved date `3/14/2026`. There is no separate populated field anywhere in 0–20 that could be a distinct "creator" — only one identity slot exists, and it tracks the **later** (saved) date, not the **earlier** (created) one.
- The saved date recovered here — **2026-03-14** — is the exact same date Discovery flagged for the contaminated `Kondo.Rachel-Quiz3-1.SLDPRT` (`sw_author: GCE4`, saved one day before that grading run). That is not a coincidence: it means whatever the instructor did on 2026-03-14 (almost certainly running diagnostics, similar to this session) touched both a real student submission and this fixture, overwriting the "saved by" stamp on both. This is now first-hand confirmation of the exact mechanism Discovery inferred from indirect evidence.

An independent cross-check via Windows Explorer's shell property system (`Shell.Application` COM, `GetDetailsOf`) found no "Authors" property exposed for `.SLDPRT` at all — Windows has no property handler registered for this file type, so this avenue added no information either way, but confirms `doc.SummaryInfo(i)` is the only usable channel.

### 3. What edition is this machine running?

`ApplicationType = 1`, `RevisionNumber = '34.3.0'`. Per the existing constants in `sw_connection.py`, `ApplicationType=1` is Student Edition — **confirmed even though this install is branded "SOLIDWORKS 3DEXPERIENCE R2026x"** and its main window says "SOLIDWORKS Design Premium 2026 SP3.0". This matches every historical log in Discovery's dataset. Build 34 corresponds to "SOLIDWORKS 2026" per this machine's own registry key name and window title — used as the anchor point for the build-number-to-year table in `sw_detect.py`.

### Bonus: DISPID 7→48 sketch probe vs. the named API (§16.1)

Since a live SolidWorks instance was available, both were tested directly against `test_underdefined.SLDPRT`'s two `ProfileFeature`s:

- **Raw DISPID 7→48 probe: works.** Returns `raw=2` for both sketches, consistent with `UNDERDEFINED` (matches the file's name/intent).
- **Named `ISketch::GetFullyDefinedStatus`: does not work**, tried two ways (via `feat.GetSpecificFeature2()` and directly on the DISPID-7-obtained `ISketch` object) — both fail with `com_error: Member not found` / `AttributeError`.

This **contradicts §16.1's speculation** ("on Desktop the supported API may simply work"). On this specific 3DEXPERIENCE-integrated install — which still reports `ApplicationType=1` — the named API remains unavailable and the fragile DISPID probe remains necessary. The edition-dispatch logic in §16.3 should not assume Desktop/3DExperience installs get the named API; it should test for it live in each edition (this data point covers exactly one) and fall back correctly, which is what `tool_sketch.py` already does (no code change was needed here — the module's design already prefers-if-available-else-DISPID pattern was already correct, the finding is just that this branch was never actually exercised because the named call fails on this edition too).

### A genuine, previously-unknown bug found in the process

`popup_dismisser.py`'s button-matching did an **exact string comparison** (`txt in button_texts`) against literal Windows button captions. Windows returns mnemonic-accelerator captions verbatim — `"&Yes"`, not `"Yes"` — for the dialogs actually encountered live today. The dismisser's rules would therefore **silently never match** on this dialog, even though its title/class rule matched. This was invisible in the historical log (the documented "SOLIDWORKS Design" / "instructional use" dialog apparently used a control whose caption didn't carry an ampersand, or a different button style) but is real and reproducible on the dialog encountered today. Fixed by stripping `&` before comparing (see §15.6 below).

---

## What was changed, per spec section

### Step 0 — Repo hygiene
- Added `.gitignore` (`__pycache__/`, `*.pyc`, `*.log`, `dist/`, `build/`, `*.spec`, credential patterns, venvs, `.claude/`).
- Untracked `grading_agent.log` and `solidworks_mcp.log` (kept on disk — forensically useful, per instruction).
- Removed the committed `__pycache__/` directory.
- Deleted the two junk files (`python`, `python test_firebase.py`).
- Did **not** touch git history / the leaked service-account key — out of scope per instruction, being rotated separately.
- Committed separately (`578dfaa`).

### Step 2 — Correctness invariants (§15), all verified against live SolidWorks

- **§15.1** (`tool_compare.py`): `_voxel_iou` returns `None` on any failure path (exception, degenerate pitch, empty union) — never `0.0`. The `volume_ratio` fallback in `compare_shapes` is **removed entirely**, not gated behind a `method` check. `_normalized_pca_iou` / `compare_meshes_normalized` propagate `None` correctly through the 8-flip search (only real, non-`None` results compete for "best"; if all 8 fail, the result is `None`, not the loop's old `0.0` initializer).
- **§15.1 / §15.4** (`grade_assignment.py`): introduced `check_result.CheckStatus` (`pass`/`fail`/`not_evaluated`) and threaded it through all four checks:
  - **Sketches**: any `UNKNOWN` status, or a prior open/read error, forces `not_evaluated` — never silently counted as passing (this was the exact silent-full-marks bug Discovery flagged).
  - **Volume**: a failed mass read (`mass["error"]` set) or a missing solution volume forces `not_evaluated`, distinct from a genuinely-wrong volume.
  - **Material**: same pattern.
  - **Shape**: a `None` score (IoU computation failed) forces `not_evaluated`; the old `shape_score = ... or 0.0` coercion — which would have silently turned a `None` into a passing-looking `0.0` even after the `tool_compare.py` fix — was found and removed.
  - `compute_grade()` takes statuses, not booleans; `not_evaluated` withholds points (same numeric effect as a fail for this milestone — redistributing weights is a rubric-design decision out of scope) and is recorded distinctly; `needs_review` is forced whenever any check is `not_evaluated`, on top of the existing fail/low-grade triggers.
  - Volume-aware shape credit coupling (unchanged, out of scope — see spec §7.2 Q6) now requires `volume_status == PASS` specifically to grant the boost, not merely "not fail".
- **§15.3** (`sw_connection.py`, `grade_assignment.py`): `open_part_silent` reordered so `OpenDoc6` with `Silent|ReadOnly` is tried **first**; the previously-first bare `OpenDoc` (no flags) is now the last-resort fallback. `grade_assignment.py` additionally copies each student submission to a scratch file in the run's temp directory, marks it filesystem-read-only, opens **only the scratch copy**, and deletes it in a `finally` — the original is never handed to SolidWorks. **Verified live, repeatedly**, by hashing the source file before and after grading runs (including one run that hit a mid-run COM failure) — hash unchanged every time.
- **§15.5**: deleted the threaded `grading_batch` in `server.py`, replaced with the sequential version (previously only in `server_additions.py`), with an explanatory docstring. `server_additions.py` left as-is (not part of the desktop app; redundant now but not asked to be deleted).
- **§15.6** (`popup_dismisser.py`): `DISMISS_RULES` narrowed to **exact** title matches (`==`, not substring); the bare `("solidworks", "#32770", ["Yes","OK"])` catch-all is gone. Any `#32770` dialog in a SolidWorks-titled window that matches no known rule is logged (rate-limited) and left alone — never clicked blind. Fixed the ampersand-mnemonic matching bug (found live, see above). Added `check_integrity_parity()` (UIPI detection via `TokenIntegrityLevel` comparison) and a `dismissal_count` counter, both wired for future use by the status indicator but not yet surfaced in the Step 5 UI — see "What Milestone 2 should be" item 6.
- **§15.7** (`tool_export.py`): original STL preferences are persisted to `.stl_prefs_backup.json` on disk **before** mutation, restored via `atexit` in addition to the existing `finally`, and `recover_stl_preferences_if_needed()` restores from that file on next launch if a crash left it behind. **Verified live**: no backup file lingers after a normal run.
- **§14.4** (`grade_assignment.py`): the module-level `pythoncom.CoInitialize()` (called at import time, on whatever thread imports the module) is removed; an explicit `pythoncom.CoInitialize()` now runs at the top of `grade_assignment()` itself, on the thread that will actually make the COM calls. `grade_midterm.py` has the identical defect and was **deliberately not touched** — it is not on the walking skeleton's call path (Step 5's UI only calls `grade_assignment`), and the instruction against opportunistic changes applies.
- **§14.5** (`server.py`): `get_mass_props()` (the `CreateMassProperty`/`GetMassProperties2`-based duplicate, returning m³/m² — different units than `tool_mass`) is deleted. Its two callers (`get_properties`, `compare_models`) are rewired onto `tool_mass._read_mass_properties`, with their output units and labels corrected to match (mm³/mm²).

### What was found live but deliberately NOT wired in — §11.3

**`sw_timeout.with_timeout()`'s existing thread-based implementation is unsafe for SolidWorks' COM calls, and this was caught by live verification, not by review.**

The obvious-looking fix — wrap `conn.open_part_silent(...)` and `export_file(...)` in `with_timeout()`, per the spec's own description of this as "close to a one-line-per-call-site change" — was implemented, then run against live SolidWorks, and it **broke the connection**. `with_timeout()` runs the wrapped call on a new `threading.Thread`; SolidWorks' automation object is a single-threaded-apartment (STA) COM server, and invoking it from a thread other than the one that established the connection, without marshaling, corrupts the client-side connection state. Observed directly: SolidWorks itself kept running throughout (`Get-Process` showed it healthy and responding), but the Python side logged `"SW connection lost — resetting and reconnecting"` and had to fully reconnect. This is the exact class of hazard §15.5 describes for `server.py`'s old threaded `grading_batch` — reached via a different code path.

This was reverted. `grade_assignment.py` still contains the explanatory comment and imports are clean; `sw_timeout.py` and `SWTimeoutError` are untouched (still dead code, as Discovery found them) pending a real fix. **§11.3 timeouts are not implemented in this milestone.** See "What Milestone 2 should be."

A second, related concurrency hazard was found and fixed once the web app existed (Step 5): with Flask's `threaded=True` (needed so the UI doesn't freeze during a ~40s self-test), two concurrent requests could race on the self-test's `if _state["self_test"] is None` check and both start comparing simultaneously, or a self-test could overlap a grading run — both scenarios drive two threads into `sw_connection`'s shared connection singleton at once, the same STA hazard again. Fixed with a single `threading.Lock()` (`_com_lock` in `app.py`) serializing every code path that can touch the SolidWorks connection. `sw_detect.is_running()` deliberately does **not** need this lock — it does its own fresh `CoInitialize` + `GetActiveObject` per call, which is safe to call concurrently (proper ROT marshaling, not a shared raw pointer).

### Step 3 — Packaging skeleton (§2, §2.4)

- `requirements.txt` — pinned lockfile (11 packages, versions as installed: numpy 2.5.2, scipy 1.18.1, trimesh 5.0.0, pywin32 312, Flask 3.1.3 + deps). None of this existed before.
- Target interpreter: **Python 3.12.10**, installed via `winget` specifically for this build (the machine's system Python was 3.14). A dedicated venv (`.venv312/`, gitignored) was used for all dependency installs and the PyInstaller build.
- `self_test.py` — implements §2.4: compares the bundled `test_underdefined.SLDPRT` against itself via `tool_compare.compare_shapes`, asserts `score == 1.0` exactly, refuses (`passed: False`) with a specific, actionable error otherwise. Requires SolidWorks to already be running (see the bug found and fixed below) and never triggers a launch itself.
- **The critical verification — deliberately building once without the scipy fix, per instruction:**
  - First built **without** any hidden-import flag at all. Contrary to Discovery's finding (which predates this PyInstaller version), the self-test **passed** — `scipy.ndimage` was bundled anyway. Investigation showed `pyinstaller-hooks-contrib` 2026.7 now ships a dedicated `hook-trimesh.py` alongside PyInstaller's own `hook-scipy.py`, and `scipy/ndimage` was physically present in `_internal/` without any explicit hint from this project. **The historical scipy.ndimage packaging landmine that Discovery identified as "the single most dangerous line in the codebase" does not reproduce on current PyInstaller (6.22.2) + hooks-contrib (2026.7).** This is a real, verified change in the toolchain since Discovery's assessment, not a mistake in this session's build command.
  - Because that build didn't actually exercise the self-test's failure path, a second build was made with `--exclude-module scipy` (forcing a **genuine** absence, since the point of the exercise is verifying the self-test's *catching* behavior, not the historical bundling gap specifically). Running that build's `/api/self_test`: `{"passed": false, "score": null, "error": "IoU computation could not be evaluated (voxelization failed).", "detail": "...missing scipy.ndimage: trimesh needs it for VoxelGrid.fill()..."}`. **Confirmed: `score` is `null`, never `0`, and the app correctly refuses to report itself ready.** This is the verification the milestone calls "the single most important" — done, and it required going one level deeper than the literal instruction because the literal reproduction case no longer reproduces.
  - Final build: `--onedir --noconsole --hidden-import scipy.ndimage --add-data "test_underdefined.SLDPRT;."`, named `SolidGradeDesktop`. Kept the explicit hidden-import despite it now being redundant — free insurance against a future hooks-contrib regression, and it's what the spec asks for.
  - **Onedir size: ~133 MB** — smaller than Discovery's 250–400 MB estimate (likely a combination of a leaner numpy/scipy build and more efficient exclusion by modern hooks; not independently investigated further, not load-bearing for this milestone).
- **A bug found only by testing the frozen exe live, not by code review**: the self-test's own comparison pipeline goes through `sw_connection.get_connection()`, whose default `launch_if_not_running=True` meant that running the self-test while SolidWorks was closed silently triggered the exact same unreliable `Dispatch()`-based auto-launch documented in Step 1 — directly violating §3's requirement that checking status must never launch SolidWorks as a side effect. Reproduced live (SolidWorks visibly launched and stalled on its splash screen in response to an `/api/status` call), then fixed: `self_test.py` now checks `sw_detect.is_running()` (which never launches anything) first, and returns a distinct, honest `"SolidWorks is not running"` result without attempting the comparison if it's not. `app.py`'s self-test result cache was also fixed to not permanently cache that particular outcome (it's a precondition failure, not a verdict on the bundle — caching it would show a stale failure forever even after SolidWorks is launched).

### Step 4 — SolidWorks detection (§3.2)

New module `sw_detect.py`:
- `is_installed()` — registry probe via `SldWorks.Application\CLSID` → `CLSID\{...}\LocalServer32`, not a hardcoded version-specific subkey name (edition-agnostic).
- `is_running()` — `GetActiveObject` only, as established in Step 1. Distinguishes "not running" (`MK_E_UNAVAILABLE`) from a genuine unexpected COM error rather than collapsing both to `False`.
- Build-number → year table, anchored on this session's confirmed data point (build 34 = 2026); adjacent years extrapolated from SolidWorks' known one-major-version-per-year numbering and flagged as unconfirmed beyond the anchor.
- `launch_solidworks()` — finds and launches the real Start Menu shortcut first (reproducing the platform-auth bootstrap), falls back to the bare registered exe (with a caveat in the response) only if no shortcut is found.
- **Verified live, full cycle**: SW closed → `is_installed()` correct → `is_running()` correctly reports `False` without launching anything (confirmed via `tasklist` immediately after) → `launch_solidworks()` found and used the real shortcut → polling `is_running()` every 5s reported ready in **15.6s**, with correct `ApplicationType`/`RevisionNumber`/`release_year`.

### Step 5 — Minimal UI and one grading run

`app.py` (Flask, single file) + inline HTML/JS (deliberately unstyled, per instruction):
- System Ready pill, expandable to runtime/SolidWorks detail, with a Launch button shown exactly when installed-but-not-running.
- Native folder/file pickers (`tkinter.filedialog`, run server-side) — a browser `<input type=file>` cannot return a real filesystem path, and there is no upload step in this app (§13: student files are referenced, never copied).
- Run button, disabled until ready + both paths chosen.
- Live progress: `grade_assignment()` gained an additive, optional `progress_callback` parameter (does not change any existing caller), invoked after each student with current/total/filename/elapsed/per-file-seconds; the UI polls `/api/run_status` every second.
- On completion: the full result JSON is dumped raw into a `<pre>` block — no table, no formatting, as instructed.
- Shut Down control: releases SW doc handles, resets the connection, stops the popup dismisser, restores any mutated STL preferences, then exits the process; returns the exact message text specified in §1.2.
- Port-collision handling per §1.1.4: binds 8731; on failure, probes `/healthz` for this app's signature before falling back to incrementing, up to 10 ports.
- `--noconsole` PyInstaller gotcha (`sys.stdout`/`stderr` can be `None`) handled by redirecting to a log file when frozen and streams are `None`.

**Verified live, end-to-end, through the actual HTTP API** (both the dev server and the frozen exe — see Verification below): pick-equivalent → run → progress advances (`current`/`total`/`filename`/`file_seconds` populate correctly) → completion → full JSON matches the CLI dry-run's output exactly (`shape_score: 1.0`, `volume_status`/`material_status`: `pass`, `sketches_status`: `fail` — genuinely underdefined sketches in the fixture — `grade.total: 85.0`, `needs_review: true`) → Shut Down returns the correct message and the process exits (confirmed: `/healthz` times out afterward).

---

## Verification results

Run from the frozen `.exe` (`dist\SolidGradeDesktop\SolidGradeDesktop.exe`) unless noted.

| # | Check | Result |
|---|---|---|
| 1 | Double-clicking the `.exe` opens with no console window | **PASS** — confirmed via `EnumWindows` against the process PID: zero visible top-level windows belonging to it exist (the UI is browser-based; the process itself has no window of its own) |
| 2 | Startup self-test passes; fails correctly when scipy is missing | **PASS** — see Step 3 above. `score: null` (never `0`) on genuine failure, `score: 1.0` on success, both confirmed via `/api/self_test` on frozen builds |
| 3 | With SolidWorks closed, indicator says not running, does not launch it as a side effect | **PASS** (after the fix described above — this genuinely failed on the first pass and was corrected) |
| 4 | Launch button starts SolidWorks and indicator flips green unattended | **PASS** — verified twice via `sw_detect.launch_solidworks()` + polling `is_running()`; ready in 15.6s and 77.1s on two separate runs (both against the fully-verified path via the real Start Menu shortcut). The variance itself is a real, consistent-with-Discovery data point — see "SolidWorks degrades under repeated cycling" below |
| 5 | A real folder of student parts grades end to end and produces plausible results | **PASS**, with the caveat that only a single-file "folder" (the bundled fixture graded against itself) was available on this machine — no real student dataset exists here. Final frozen-exe result: `shape_score=1.0 (pass), volume_status=pass, material_status=pass, sketches_status=fail (genuinely underdefined: Sketch6, Sketch6<3>), grade.total=85.0, needs_review=true`. Internally consistent and plausible; a true multi-student run was not exercised this session |
| 6 | Every student file is byte-identical before and after the run (hashed) | **PASS** — SHA-256 of the source file (and a separate copy used as the "student" file) checked before and after every run this session (five separate grading runs total, including two on the frozen exe, one of which hit a mid-run COM disconnect/reconnect), always `899c98038d1ee227b2d12d7194f0e2cb7c86148d9baeb4453c1776b264ef995f`. Verifies §15.3 |
| 7 | Shut Down terminates the process cleanly and restores STL preferences | **PASS** — correct message returned, `/healthz` unreachable afterward (process actually exited, confirmed via process list too), no `.stl_prefs_backup.json` left on disk. Verified on the frozen exe |

All seven checks were re-run against the final frozen `.exe` specifically (not just the dev-server / earlier test builds) as the last step of this session, after the self-test auto-launch bug (below) was found and fixed and the package rebuilt. Every check above reflects that final run.

### SolidWorks degrades under repeated cycling — reproduced

Across this session's ~10 launch/kill cycles of SolidWorks (necessary for testing detection, launch, and crash-recovery paths), startup time and per-file grading time both grew noticeably less predictable — the same instance took 15.6s to become ready once and 77s another time; grading the identical fixture took 41.6–51s across different runs with no other variable changed. This is qualitatively consistent with Discovery's R-7 finding (33s → 97s per file over a 90-minute session of repeated use) even though this session never ran a true sustained multi-file batch. Worth treating as corroboration, not independent proof — a clean single long run (Milestone 2, per Discovery's own recommendation) is still the real test.

---

## Measured per-file grading time

**41.6–44.9 seconds** for the grading step itself across four separate runs of the one available fixture file (42.2s, 44.9s, 41.6s measured directly; total wall time including solution-STL preparation ranged 51–62.4s), at `VOXEL_RES=64`. This sits squarely inside Discovery's measured 33–97s/file range from real historical runs. No multi-file run was possible this session (no real student dataset on this machine), so the R-7 degradation-under-sustained-use question is only corroborated, not resolved, by this session — see "SolidWorks degrades under repeated cycling" above and Milestone 2.

---

## Things that contradict the spec, and what reality requires instead

1. **§16.1's "on Desktop the supported named sketch API may simply work" does not hold** on this 3DEXPERIENCE-integrated install, which still reports `ApplicationType=1`. The DISPID 7→48 probe remains necessary; `tool_sketch.py`'s existing prefer-named-fallback-to-DISPID structure was already correctly shaped for this, no code change was needed, just confirmation.
2. **§11.3's premise — "wrap every COM entry point in `with_timeout()`, close to a one-line change" — is not safe to execute as written.** The existing `sw_timeout.py` implementation runs the wrapped call on a separate thread, which corrupts SolidWorks' STA connection when the wrapped call touches the shared connection object. This was caught by live testing, exactly as the milestone brief demanded ("a change that passes static review and breaks COM is worse than no change"). It needs a redesign (COM marshaling across the thread boundary, or restructuring the timeout as a watchdog that only ever kills the SolidWorks *process* on timeout rather than trying to return control from inside a live call) before it can be wired in. Not done this milestone; recommended as a Milestone 2 priority.
3. **§2's packaging risk premise (scipy.ndimage as an invisible, silently-dropped dependency) is out of date for the current toolchain.** `pyinstaller-hooks-contrib` now ships a `trimesh` hook that pulls in what's needed. The `--hidden-import scipy.ndimage` flag was kept anyway (cheap insurance, and it's what the spec asks for), but instructors rebuilding this project with a recent PyInstaller should not assume the historical failure mode is what they'll hit if something goes wrong — the self-test remains the actual backstop, not the hidden-import flag.
4. **Discovery's size estimate (250–400 MB onedir) did not hold** — this build is ~133 MB. Not investigated further; doesn't change any decision.

---

## Post-milestone: first real-user testing (2026-08-28 to 2026-08-31)

The instructor tried running the packaged app on their own, without a Claude Code
session driving it. Three things came out of that, documented here because they
change what Milestone 2 should prioritize.

1. **No double-click launcher existed.** The milestone deliverable was a built
   `.exe` sitting in `dist/SolidGradeDesktop/`, reachable only by knowing that
   path. Fixed by creating Windows shortcuts (one on the Desktop, one in the
   repo root, both named "SolidGrade Desktop") pointing at the frozen exe. Not
   a code change — a packaging/delivery gap. Milestone 2 should build a real
   installer or at least ship the shortcut as part of the deliverable rather
   than relying on a human to create one after the fact.
2. **A real, live bug: the native file/folder pickers hung.** Root cause:
   `_native_dialog()` created a `tkinter.Tk()` window directly inside a Flask
   request-handling thread. Tkinter expects to own the thread it runs on;
   Flask's `threaded=True` hands each request to a fresh worker thread, and a
   Tk window created there is unreliable on Windows — it can open off-screen,
   open behind other windows, or simply never respond, which is exactly what
   the instructor saw ("very laggy... unable to finish the process").
   **Fixed and verified live** (commit `a57befd`): each dialog now runs in a
   completely separate child process (the app re-invoking itself with a
   hidden flag) that does nothing but show one dialog and exit, handing the
   chosen path back via a temp file. Confirmed working on both the dev server
   and a rebuilt frozen exe — the dialog opens as a real, responsive window
   and the API returns promptly whether the user picks a path or cancels.
3. **Not yet fixed — flagged as a new top priority: refreshing the browser
   page loses the running app**, and the instructor independently proposed
   the app should be its own real window rather than a browser tab. Root
   cause not yet diagnosed — candidates include the background server
   actually exiting, or the browser simply losing track of which port it's
   on. This needs investigation, not a guessed fix. See item 1 below.
4. **A new requirement surfaced: the desktop app's real screens (Milestone 2+)
   should match the look, feel, and navigation of an existing SolidGrade web
   app the instructor already has**, not invent a new design. This needs the
   web app's actual source (or at minimum a live URL) to do properly — see
   item 2 below and `NEXT_SESSION_PROMPT.md`.

---

## What Milestone 2 should be

Ordered by what most directly follows from what this session found. Items 1–2
are new, from the post-milestone testing above; items 3–9 were the original
list written at the end of the milestone build itself.

1. **Diagnose and fix "refreshing the browser loses the app," and decide:
   browser tab vs. a real standalone application window.** Find out first
   whether the background server is actually crashing/exiting or whether this
   is purely a browser/tab-tracking problem — don't guess. Given the
   instructor independently asked for "its own window, not in a browser,"
   seriously evaluate switching the UI layer to a real native window (e.g. a
   webview-based shell) instead of "open localhost in the default browser."
   That would both solve this bug structurally (no browser tab to lose) and
   move the app closer to feeling like installed software, which is also
   what item 4 above and `NEXT_SESSION_PROMPT.md` are asking for.
2. **Build the real UI, styled to match the existing SolidGrade web app** —
   once a design/feature reference for that web app exists (see
   `NEXT_SESSION_PROMPT.md` for the recommended discovery pass that should
   happen first). This is where §5 home, §10 wizard, §12 results view, and
   §3 status actually get built with real design, replacing the
   deliberately-plain Step 5 screen from this milestone.
3. **Fix `sw_timeout.py` for real, then wire up §11.3.** This is the single highest-value piece of unfinished correctness work — a genuine COM stall (not the self-inflicted kind found this session) still hangs the app forever with no recovery. Two credible designs: (a) proper COM marshaling of the connection object across the timeout-watcher thread boundary, or (b) restructure the "timeout" as a watchdog thread that never touches the COM object itself, only kills the SolidWorks *process* if a call exceeds its budget, and lets `recover_from_stall`/`get_connection()`'s existing dead-connection detection handle the rest. Verify (a) or (b) against live SolidWorks before considering it done — do not trust static review here, per this session's own experience.
4. **A real multi-student, multi-minute run against actual (or realistic synthetic) student files**, to (a) exercise the R-7 degradation question with real data on real hardware, since this session only ever graded one file at a time, and (b) shake out anything that only shows up under sustained load (leaked documents, the SolidWorks-slowdown pattern Discovery measured).
5. **§9 ingestion and attribution** — still entirely unbuilt, and the spec calls it "the largest and highest-risk new subsystem." Nothing in this milestone touched it (by design).
6. **§11.1 checkpointing** — small, and unblocks safely testing longer runs (item 4 above) without losing everything to a crash mid-run.
7. **A dedicated COM worker thread/queue for the whole app**, rather than letting Flask's request threads and the grading background thread each independently touch SolidWorks (mitigated this session with a single global lock, which works but serializes everything through lock contention rather than through an actual owned-thread design). The `_com_lock` fix in `app.py` is adequate for a single-run walking skeleton; it is not the right long-term architecture once checkpointing/resume or concurrent status-while-grading UX matters more.
8. **Surface `popup_dismisser`'s new `dismissal_count` and `check_integrity_parity()` in the System Ready indicator** (§15.6 point 2's "alert if a file open exceeds N seconds with zero dismissals" signature) — both were built this session but not wired into the Step 5 UI, since Step 5 was scoped to the minimum viable screen.
9. **Re-run the §16.2 validation pass's remaining pieces** (`diag_export.py`) on this edition — `diag_props.py`, `diag_mass.py`, and the sketch probe were all exercised this session; STL export API specifics were exercised indirectly (via `tool_export.py`, which worked throughout) but not via the dedicated diagnostic script.
