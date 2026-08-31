# SolidGrade Desktop — Milestone 2 Report: The Real UI

Session date: 2026-08-31. Follows `MILESTONE_1_REPORT.md`, builds against
`SOLIDGRADE_WEB_REFERENCE.md` (design authority) and `SPEC_v0.2_SolidGrade_Desktop.md`
(§3 status, §5 home, §10 wizard, §12 results).

---

## 1. "Refreshing the browser loses the app" — diagnosed, not guessed

`MILESTONE_1_REPORT.md` was explicit that the root cause was unknown and that the two
candidates — the server exiting, or the browser losing the port — must not be guessed
between. Measured instead.

**The server was never the problem.** At the start of this session a
`SolidGradeDesktop2.exe` (PID 46280) launched **2026-08-29 08:13** was still listening on
8731 — two days later — and answered `/healthz` in 106 ms, `GET /` in 25 ms, `/api/status`
in 31 ms. It was still holding a **complete 26-student grading run** in memory
(`/api/run_status` → `status: "complete"`, 26/26, 24.5 KB of JSON).

**The page threw its own state away.** In the Milestone 1 UI:

- `solutionPath` and `folderPath` lived only in JS variables (`app.py:424` as it stood).
- `/api/run_status` was called *only* from inside `pollRunStatus()`, which was started
  *only* by `runGrading()`. The sole startup code was `refreshStatus(); setInterval(refreshStatus, 8000);`

So on reload both pickers reverted to "(none selected)", Run went disabled, Progress read
"(not running)" **even during a live run**, and Results read "(no results yet)" **while the
server held a finished 26-student result**. Nothing was lost; nothing was asked for.

### The second half of the same bug: nothing owned the app's lifetime

The Milestone 1 log carried an unmistakable signature — exactly **five `/api/status`
requests arriving in the same second, once every 60 seconds**, stable for hours:

```
5 31/Aug/2026 11:51:50
5 31/Aug/2026 11:52:50
5 31/Aug/2026 11:53:50
```

The page polls every 8 s; browsers clamp background-tab timers to 60 s. Five simultaneous
pollers on the 60 s floor means **five abandoned tabs**, accumulated because every launch
called `webbrowser.open()` and nothing ever closed one — and because closing the last tab
left the server running forever, which is why a two-day-old process was still there at all.

---

## 2. Decisions taken (instructor, this session)

| # | Decision | Choice |
|---|---|---|
| — | **App shell** | **pywebview native window**, WebView2 backend, browser fallback if no webview can be created |
| §7.2 ③ | **voxelResolution 48 vs 64** | **Explicit in the UI**, defaulting to 64 and stamped into `thresholds.voxel_resolution` |
| §7.2 ④ | **`solutionStoragePath` two shapes** | **Accept both defensively** — file used directly, folder resolved to the single `.SLDPRT` inside |
| §7.2 ①②⑤⑥ | **Cosmetics** | Fix the off-brand hover, the missing `btn-secondary` border, and the dead animations; **keep the red dark-mode `<h1>`** |
| §7.2 ⑦ | **Installer / login / sync gap** | **Recorded, deferred** — see §7 below |

### One refinement I made to decision ③, rather than absorbing it silently

The instruction was "surface it, no silent default." SPEC §7.4 / **D3** sets a **hard floor
of 64** ("resolution is not a speed lever"), and §7.5 marks the form check *"valid only at
resolution ≥ 64"*, citing measured noise floors of ~0.8 % at 64 vs ~3 % at 24. The web app's
`grading_jobs` documents ask for **48**, which is below that floor.

So the field is surfaced and editable, defaults to 64, and is **refused below 64** on both
sides (UI and `/api/run_grading`) rather than letting an instructor pick a value the spec
says produces an invalid form score. `grade_assignment()`'s new parameter clamps rather than
rejects, and stamps the value actually used — the output can never claim a resolution it
did not run at.

---

## 3. What was built

### The window (`app.py`)

`main()` now starts Flask on a background thread, waits for `/healthz`, and opens a real
`webview` window (`gui="edgechromium"`, 1280×860, `min_size` 940×600, `confirm_close=True`).
**When the window closes, `main()` runs the same §1.2 cleanup the Shut Down control runs and
exits.** That is the structural fix: window lifetime *is* app lifetime, so the
abandoned-tab and never-exiting-server failure modes cannot recur.

`/api/focus` was added so a second launch **raises the existing window** instead of opening
a second UI onto the same server — otherwise §1.1.4's single-instance guard would have
reintroduced the multi-tab problem in window form.

If no webview can be created, the app falls back to `webbrowser.open()` and says so in the
log. A degraded UI beats no UI.

### The UI (`ui/index.html`, `ui/styles.css`, `ui/app.js`)

Replaces the inline `INDEX_HTML` string. No build step — §8's token set expressed as CSS
custom properties, exactly as `SOLIDGRADE_WEB_REFERENCE.md` §7.1 intends.

- **Shell (§4.1)** — 288 px sidebar (`hidden lg:flex`), 64/80 px sticky header, `max-w-7xl`
  content, mobile drawer. Logo per §4.3 (lucide `layers` mark, `SOLID`/`GRADE` wordmark).
- **System Ready (§3)** — the combined header pill, quiet when healthy, expanding to the
  three rows (runtime / SOLIDWORKS / edition) with the inline Launch button shown exactly
  when installed-but-not-running, and the §3.3 edition caveat framed around edition, not year.
- **Run wizard (§5/§10)** — the two native path pickers, criteria confirmation with the
  voxel field, the §10 step-5 live SOLIDWORKS gate with an inline Launch so the user never
  backs out of the wizard, and §10 step-6 live progress with a per-file duration trend and a
  remaining-time estimate computed from the observed mean.
- **Results (§12)** — frozen student-name column, per-check columns, ✓/✗/— three states,
  §3.5 flag tiles, search, the §3.1 solid-fill filter segmented control, sortable columns,
  §12.4 overrides as a computed/override **pair**, and §12.7 CSV export.

The **path picker** is the §3.3 dropzone's visual language — 2 px dashed border,
`rounded-2xl`, idle/hover/chosen, green when populated, clear button at top-right, icon
turning green — driving the native `tkinter` dialog. Deliberately **no dragover state**,
because nothing can be dropped on it (SPEC §13: student files are referenced, never copied).

### The rehydration fix (`ui/app.js` `boot()`)

Picked paths persist to `localStorage` and are **re-validated server-side** on load (a
restored path that has since moved shows amber "choose again", not a green lie), and
`/api/run_status` is read on **every** page load. A refresh now restores the picked paths,
an in-flight run's progress (with the trend back-filled), and a finished run's full results.

### Additive endpoints

Every pre-existing endpoint kept its exact request and response shape. Three were added
because the styled UI needs capabilities Milestone 1's screen had no use for:

| Endpoint | Why |
|---|---|
| `POST /api/validate_paths` | Re-check localStorage-restored paths so a moved file is caught on load, not after committing to a run |
| `POST /api/override` | §12.4 override/revert, persisted atomically (`os.replace`) to the results JSON |
| `POST /api/export_csv` | §12.7 CSV *including overrides and markers* — `grade_assignment`'s own CSV predates overrides and has no column for them |

### Accessibility — the §7.3 gaps fixed, not reproduced

The web app has no focus indicator anywhere, uses `window.prompt()` for grade overrides, and
contains `aria-label` exactly once. This build instead has: a global 2 px brand-red
`:focus-visible` ring at 2 px offset (cyan on red surfaces), a real `role="dialog"` modal
with focus trapping, Escape, and focus restoration, inline validation instead of
`alert`/`prompt`, `aria-label` on every icon-only control, a skip link, table `<caption>` and
`scope`, `aria-sort` on sortable headers, and **no colour-only status encoding** — every
✓/✗/— carries a screen-reader text label.

---

## 4. Verification

### 4.1 API and correctness suite — 27/27 passed, against the frozen `.exe`

Voxel floor refused at 48 / 63 / 0 / −1 / `"abc"`; empty submissions folder refused;
`solutionStoragePath` accepted as file **and** as single-part folder, ambiguous folder
refused rather than guessed, non-`.SLDPRT` refused; override kept `total` unmutated while
writing `override`/`override_note`/`override_by`, persisted to disk, no stray `.tmp`,
validation refused 150 / −5 / `"eighty"` / unknown student; CSV carried computed **and**
override **and** effective totals for 26 rows; one-click revert cleared all three and
restored the computed value on disk.

### 4.2 Live end-to-end runs on the frozen build — all passed

Two real grading runs through `/api/run_grading` on `dist\SolidGradeDesktop2\SolidGradeDesktop2.exe`:

| Check | Result |
|---|---|
| **§15.3** student file byte-identical after run (res 64) | **PASS** — `899c98038d1ee227…`, matching the Milestone 1 baseline exactly |
| **§15.3** student file byte-identical after run (res 96) | **PASS** — same hash |
| **§15.3** solution file byte-identical, both runs | **PASS** |
| **§15.3** student file **mtime unchanged** — never even opened read-write | **PASS** |
| **§7.4** result stamps the resolution actually used | **PASS** — 64 and 96 both stamped correctly |
| **§7.4** a non-default resolution is honoured, not ignored | **PASS** |
| **§15.1** `shape_score` a real number, not a swallowed 0 | **PASS** — `1.0` |
| Three-state statuses present as strings | **PASS** — `pass`/`pass`/`pass`/`fail` |
| §2.4 self-test on the frozen build | **PASS** — form score exactly 1.0, `ready: true` |
| Progress + per-file duration reported | **PASS** |

### 4.3 Window and lifetime

| Check | Result |
|---|---|
| A real top-level window exists | **PASS** — `title='SolidGrade' 1280x860`, the exact inverse of Milestone 1's check #1 ("zero visible top-level windows") |
| UI loads and boots inside WebView2 | **PASS** — `GET /` → `ui/styles.css` → `ui/app.js` → `/api/run_status` (the rehydration call) |
| Exactly one poller, at 10 s | **PASS** — not five at the 60 s background floor |
| **Closing the window runs §1.2 cleanup and exits** | **PASS** — WM_CLOSE → cleanup called *and* finished → process exited, port released |
| Shut Down control still exits cleanly | **PASS** — correct message, process exited, port released, no `.stl_prefs_backup.json` left |
| Second launch raises the existing window | **PASS** — `POST /api/focus` 200, returned in 0.02 s, no second server or window |
| `ui/` and the self-test fixture bundled in the frozen build | **PASS** |

### 4.4 Not re-verified live this session, and why

**"The status check must not launch SolidWorks as a side effect."** SOLIDWORKS was running
throughout, and closing the instructor's live session to re-test was not worth the
disruption. What I can state precisely: `sw_detect.py`, `self_test.py`, `sw_connection.py`,
`tool_export.py`, `popup_dismisser.py`, `check_result.py` and `tool_compare.py` are
**byte-identical to the versions Milestone 1 verified live** (`git diff --stat` over all
seven is empty), and `sw_detect.is_running()` still uses `GetActiveObject` only — every
occurrence of `Dispatch` in that file is in a comment explaining why it is not used. The
invariant is structurally preserved; it was not independently re-exercised.

---

## 5. A destructive mistake I made, and what it cost

**I destroyed the STL set from the instructor's real 26-student HW3 run.**

Rebuilding the frozen app with `pyinstaller --noconfirm` runs a COLLECT step that
**deletes and recreates `dist/SolidGradeDesktop2/`**. Milestone 1 wrote grading output to
`dirname(sys.executable)/output`, which for a frozen build is *inside that directory*. The
rebuild therefore removed `dist/SolidGradeDesktop2/output/HW3-06-0194/` in full. I had told
the instructor those results were "safely on disk" before doing it; I was wrong about where
"on disk" was.

**Recovered:** `HW3-06-0194_grades.json` (42,290 bytes) — restored from a sandbox copy I had
made for override testing, verified byte-for-byte identical to the pre-loss file and free of
any test overrides (26 students, `gradedAt` 2026-08-29T13:55:30Z, totals 16.1–33.0,
26 `needs_review`, 4 plagiarism). It now lives at
`%LOCALAPPDATA%\SolidGrade\output\HW3-06-0194\`.

**Not recovered:** the 27 STL files (26 students + solution, ~6.2 MB) and the original
`HW3-06-0194_grades.csv`. No Recycle Bin entry, no shadow copies, no restore points. They
are regenerable only by re-running the assignment (~85 minutes, see §6) against the original
student files, which are untouched wherever the instructor keeps them. The STLs feed the web
app's 3-D viewer; every grade, check, flag and score survives in the JSON.

**Fixed so it cannot recur.** `app.py` gained `results_root()`: frozen builds now write to
`%LOCALAPPDATA%\SolidGrade\output`, which no rebuild or installer touches; running from
source keeps the repo-relative `output/`. Verified: the two live runs above landed in the
durable location and **nothing** was written inside `dist/`. Grading results are not build
artifacts and must not live where a build step owns the directory.

---

## 6. New findings

### 6.1 The 41–51 s/file benchmark was measured on an unrepresentative fixture

Milestone 1 could only ever grade one file — the bundled fixture compared **against itself**
— and measured 41.6–51 s. The 26-student HW3 run's own timestamps tell a different story:

| Metric | Value |
|---|---|
| Span | 08:30:03 → 09:55:30 = **85.5 min** for 26 students |
| Mean per file | **205 s** |
| Median | 199 s |
| Fastest / slowest | 98 s / 346 s (student names omitted — `.gitignore` treats them as sensitive) |
| First-half vs second-half mean | 195.5 s → 213.9 s (**+9 %**) |

Two things follow, and they point in different directions from R-7's framing:

1. **Real per-file cost is ~4× the published benchmark.** 205 s vs 41–51 s. The fixture
   self-comparison is not a throughput benchmark — a real student part is a distinct model
   requiring a full open, rebuild and STL export. **Budget ~3.5 min/student**: a 26-student
   assignment is an 85-minute run. The figure in `MILESTONE_1_REPORT.md` should be read as a
   floor, not an estimate.
2. **Within-run degradation is mild here — +9 %, not Discovery's 33 s → 97 s.** The high cost
   is a *flat higher baseline*, not runaway drift. R-7's "degrades under sustained use" is
   only weakly supported by this run; the far larger effect is that the benchmark was wrong.

For reference, this session's frozen-exe single-fixture runs measured 55.5 s at resolution 64
and ~130 s at 96 — so resolution is a genuine cost multiplier, which is exactly why §7.4
forbids using it as a speed lever downward.

### 6.2 The HW3 results look like a wrong solution file, not 26 bad students

Reported, not acted on. In `HW3-06-0194`, **26 of 26** students fail volume *and* material,
all 26 are flagged `needs_review`, and totals span 16.1–33.0 with a 29.6 mean. Student
volumes cluster near 311,467 mm³ against a solution volume of 127,729 mm³ (~2.4×), and
students report "Plain Carbon Steel" against a solution material of "2024-O". A whole-cohort
failure with that shape is more consistent with the wrong file being picked as the solution
(`C:/Users/gce4/Box/ES-19/CADFiles/Listed/0194.SLDPRT`), or a units/scale mismatch, than with
26 independently wrong submissions. Worth an instructor's eye before those grades go anywhere.

### 6.3 A gap found and closed while testing

A submissions folder containing **zero** `.SLDPRT` files passed the run gate and started a
run that graded nobody and reported success. Found by driving the real UI; fixed in both the
UI gate (amber "no .SLDPRT files in this folder") and `/api/run_grading` (400). I hit this by
accidentally starting such a run against stale server code — which is also how I know the
old behaviour silently produced an empty, successful-looking result.

---

## 7. Still open

> **Superseded as a priority list.** After this report was written, the instructor
> ran a full grading job from the Desktop shortcut successfully, added four items,
> and set the ordering. The agreed, ordered list now lives in
> `NEXT_SESSION_PROMPT.md`; the items below remain accurate as a catalogue of what
> is unbuilt, but read that file for what to do next.

1. **§7.2 ⑦ — the installer / SOLIDWORKS-path prompt / account login gap.** Recorded, not
   decided. The web app's Grading Automation page (§5.16) describes a `SolidGrade_Setup.exe`
   that prompts for the SOLIDWORKS path and signs in with instructor credentials to sync
   assignments; what ships is a PyInstaller folder-bundle with no login and no sync, launched
   from a hand-made shortcut. Login/sync is entangled with §9 ingestion, which is unbuilt, so
   this should be decided with that context rather than snap-judged.
2. **Regenerate the HW3 STLs** if the web app's 3-D viewer needs them — see §5.
3. **`sw_timeout.py` (§11.3)** — unchanged and still the highest-value correctness work
   outstanding. Milestone 1's finding stands: the thread-based implementation corrupts the
   STA COM connection, and a genuine stall still hangs the app forever.
4. **§9 ingestion and attribution** — untouched, still the largest unbuilt subsystem.
5. **§11.1 checkpointing** — now more valuable than Milestone 1 judged, given §6.1: an
   85-minute run with no resume is a lot to lose, and `confirm_close=True` on the window is
   only a guard against the accidental close, not against a crash.
6. **§12.6 inline "Open in SOLIDWORKS"** — not built; needs an endpoint that does not exist,
   and the brief was to reuse the existing API rather than grow it alongside the UI.
7. **Multi-part assignments** — §12.1's "one column per part" is stubbed as the single-part
   case, matching what `grade_assignment.py` actually produces today.
8. **A stale-build trap worth knowing about.** `SolidGradeDesktop.spec`,
   `SolidGradeDesktop_BROKEN.spec` and `SolidGradeDesktop_NOSCIPY.spec` are all still in the
   repo and none has the Milestone 2 `datas`/`hiddenimports` entries. Building from one of
   them produces an app that starts and shows an empty window. Only
   `SolidGradeDesktop2.spec` — the one the shortcuts point at — was updated.
9. **`.gitignore` excludes `*.spec`, so the packaging fix is untracked.** The two entries
   that make a Milestone 2 build work at all — `('ui', 'ui')` in `datas` and
   `webview.platforms.edgechromium` in `hiddenimports` — therefore live only on this machine.
   A fresh clone has no spec file, and a spec reconstructed from scratch will silently omit
   both, producing an app that starts and shows an empty window. Either track
   `SolidGradeDesktop2.spec` (`git add -f`, or narrow the ignore rule) or move the build
   definition somewhere tracked. Left as-is rather than changing the ignore rules unasked.
