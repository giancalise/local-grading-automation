# Next Session — Kickoff

**Written:** 2026-08-31, at the end of the SolidGrade web app design & feature
discovery session. That session produced `SOLIDGRADE_WEB_REFERENCE.md` and
changed nothing else.

**Previous contents of this file** (the prompt for the discovery session) are
superseded — that session is done. Its output is the reference document.

This document has two parts: notes on how to approach the next session, and a
ready-to-paste prompt.

---

## Recommendation: settle the shell question before styling anything

The discovery pass is complete, so "build the real UI" is now unblocked. But
there is a dependency the next session should not skip past:

**`MILESTONE_1_REPORT.md` item 1 — browser tab vs. real application window —
has to be decided before the UI shell gets built, not after.** The reference
document's §4.1 describes a persistent app shell: a 288px sidebar, a sticky
64/80px header, a centered 1280px content column. Whether that shell lives in
a browser tab or a webview window changes how it's built (window chrome, menu
bar, close/minimize behavior, what "refresh" even means). Building the styled
UI first and then changing the shell means doing the layout work twice.

The instructor independently asked for "its own window, not in a browser," and
the still-undiagnosed "refreshing the browser loses the app" bug would be
structurally solved by a real window. That makes this the natural first move of
the next session — but the report is explicit that the root cause was never
diagnosed, and warns against a guessed fix. **Diagnose first, then decide.**

## Open decisions that need the instructor, not a default

`SOLIDGRADE_WEB_REFERENCE.md` §7.2 lists seven places where the web app and the
desktop app disagree, or where the web app does something that looks
unintentional. **These need answers, not assumptions.** The two that carry real
engineering consequence:

- **`voxelResolution`: the web app requests 48, Milestone 1 ran at 64.** This
  changes grading output. Someone has to say which is authoritative.
- **`solutionStoragePath` is written in two different shapes** depending on
  which "Auto Grade" button the instructor pressed in the web app. Any desktop
  client consuming `grading_jobs` has to handle both, or the web app has to be
  fixed — and fixing the web app is out of this repo's scope.

The other five (primary-button hover hue, missing secondary-button borders,
animations that never run, dark-mode red `<h1>`, and whether the desktop app
should match the Grading Automation page's description of itself) are design
and product calls. The next session should surface them early rather than
silently picking one.

## What must not regress

Milestone 1 verified seven correctness properties live, on the frozen `.exe`
(see `MILESTONE_1_REPORT.md` → "Verification results"). A UI-building session
is exactly the kind of session that breaks them by accident. The
non-negotiables:

- **Student files stay byte-identical** across a run (§15.3) — hashed and
  verified across five runs.
- **Read-only opens; three-state checks that return `null`, never `0`, on
  genuine failure.**
- **The status indicator must not launch SolidWorks as a side effect of
  checking whether it's running** — this genuinely regressed once already and
  had to be fixed.
- **Shut Down still releases COM handles, stops the popup dismisser, and
  restores mutated STL preferences before exiting.**

---

## The prompt

Paste the block below to start the next session.

```
Claude Code Session — SolidGrade Desktop, Milestone 2: the real UI

This is a build session. Read these three documents before writing code:
SOLIDGRADE_WEB_REFERENCE.md (the design and feature authority for how this app
should look and what it must not omit), MILESTONE_1_REPORT.md (what exists,
what was verified live, and what's still broken), and the relevant sections of
SPEC_v0.2_SolidGrade_Desktop.md (§3 status, §5 home, §10 wizard, §12 results).

Where SOLIDGRADE_WEB_REFERENCE.md gives an exact value, use it. It labels every
value [EXACT], [TW-DEFAULT], or [DERIVED] — treat those labels as load-bearing
and don't silently upgrade a [DERIVED] inference into a fact. §8 has the whole
token set already resolved as CSS custom properties; there is no build step in
this app, so that's the intended path rather than a Tailwind toolchain.

Start here, in this order:

1. Diagnose "refreshing the browser loses the app." Find out whether the
   background server is actually exiting or whether the browser is just losing
   the port. Do not guess — MILESTONE_1_REPORT.md is explicit about this.

2. Then decide, with me, browser tab vs. a real standalone window (webview
   shell). I've asked for "its own window, not in a browser." This decision
   determines how the app shell in SOLIDGRADE_WEB_REFERENCE.md §4.1 gets built,
   so settle it before building the shell, not after.

3. Ask me about the open decisions in SOLIDGRADE_WEB_REFERENCE.md §7.2 before
   assuming defaults. The voxelResolution disagreement (web app says 48,
   Milestone 1 ran at 64) and the two different solutionStoragePath shapes both
   affect grading behavior, not just appearance.

4. Then build the real UI, replacing the deliberately-unstyled Step 5 screen:
   the persistent shell (§4.1), the System Ready status surface (§3), the
   pick-and-run flow (§5/§10), and the results view (§12) — styled per the
   reference. Reuse the existing Flask endpoints in app.py (/healthz,
   /api/self_test, /api/status, /api/launch_sw, /api/pick_folder,
   /api/pick_file, /api/run_grading, /api/run_status, /api/shutdown) rather
   than redesigning the API alongside the UI.

Two things the reference calls out specifically for this app:

- File selection uses native tkinter pickers, not browser file inputs, because
  student files are referenced and never copied (SPEC §13). The web app's
  drag-and-drop dropzone pattern should become a *path picker* wearing the same
  visual clothes — dashed 2px border, rounded-2xl, idle/hover/chosen states,
  green when populated — not a literal drop target.
- The web app has real accessibility gaps (no focus indicators anywhere,
  window.prompt() for grade overrides, aria-label used exactly once in the
  entire app). Reference §7.3 lists them. Match the web app's *look*, but don't
  reproduce those — fix them here.

Do not regress what Milestone 1 verified live: student files stay byte-identical
across a run (§15.3), opens stay read-only, three-state checks return null and
never 0 on genuine failure, the status check must not launch SolidWorks as a
side effect, and Shut Down still releases COM handles, stops the popup
dismisser, and restores STL preferences before exiting. Re-verify the ones your
changes could plausibly touch before calling the session done.

Ask me before starting if anything above conflicts with what you find in the
repo.
```

---

## Everything else on the list, for after the UI work

Unchanged in substance from `MILESTONE_1_REPORT.md` → "What Milestone 2 should
be," with the two completed items removed. Full detail on each is in that
document.

1. **Fix `sw_timeout.py` for real, then wire up §11.3.** Still the single
   highest-value piece of unfinished correctness work — a genuine COM stall
   hangs the app forever with no recovery. Two credible designs are described
   in the report; both must be verified against live SolidWorks, not by static
   review.
2. **One real multi-student, multi-minute batch run.** This session's grading
   was always one file at a time, so the R-7 degradation question is
   corroborated but not resolved.
3. **§9 ingestion and attribution** — entirely unbuilt, and the spec's own
   highest-risk subsystem.
4. **§11.1 checkpointing** — small, and unblocks safely testing longer runs.
5. **A dedicated COM worker thread/queue**, replacing the current global-lock
   mitigation in `app.py`.
6. **Surface `popup_dismisser`'s `dismissal_count` and `check_integrity_parity()`
   in the System Ready indicator** (§15.6) — both built, neither wired up. The
   new status UI is the natural place for them.
7. **Re-run `diag_export.py`** on this machine's SolidWorks edition — the last
   §16.2 validation piece not yet exercised directly.
