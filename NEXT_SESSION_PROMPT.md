# Next Session — Kickoff

**Written:** 2026-08-31, at the end of the Milestone 1 session (walking skeleton
+ post-milestone bugfixes). See `MILESTONE_1_REPORT.md` for the full record of
what that session built, found, and verified.

This document has two parts: a recommendation on how to approach the
SolidGrade web app design discovery, and a ready-to-paste prompt for starting
that session in Claude Code.

---

## Recommendation: treat the web app discovery as its own session

Run this **before** any Milestone 2 UI-building work, and as its **own
Claude Code session** — don't fold it into a build session. Reasons:

1. **This repo already has exactly this pattern, and it worked.**
   `DISCOVERY_REPORT.md` was a dedicated static-analysis pass over the
   grading pipeline, done before `SPEC_v0.2_SolidGrade_Desktop.md` was
   written, done before any Milestone 1 code was touched. It kept each
   session focused and produced a document later sessions could just read
   instead of re-deriving. The same shape fits here: study the web app,
   write down what's there, *then* build against that writeup.
2. **It's a different kind of work from engineering.** Milestone 2's build
   work is "make live SolidWorks do the right thing, verified against a real
   COM connection." This is "look at an existing product and accurately
   describe its design system and feature set." Mixing them in one session
   means whichever one starts first gets more attention.
3. **The output is reusable.** A written design/feature reference gets read
   by every future UI-touching milestone (§5 home, §10 wizard, §12 results,
   §3 status all still need building). Worth getting it right once.

**What the output should be:** a new document — suggested name
`SOLIDGRADE_WEB_REFERENCE.md` — sitting next to `DISCOVERY_REPORT.md` and
`SPEC_v0.2_SolidGrade_Desktop.md`, containing:

- **Design tokens**: exact colors (hex values, not "blue"), typography
  (font family, sizes, weights), spacing scale, border radii, shadows —
  pulled from real CSS/theme files if source is available, not eyeballed
  from screenshots.
- **Component patterns**: what buttons, cards, tables, forms, nav bars, and
  status indicators look like and how they behave (hover states, disabled
  states, etc.).
- **Layout and navigation structure**: how screens relate to each other, what
  the persistent chrome is (header, sidebar, etc.), how the user moves
  between assignments/results/settings.
- **A full feature/capability inventory**: what the web app actually does,
  screen by screen — this matters as much as the visuals, so nothing built
  later accidentally omits something the instructor already relies on.

**On access — quality depends heavily on what's provided, in this order:**

1. **Best: the web app's actual source code** (a repo link, or a copy dropped
   next to this project). Exact CSS/component values, and the real feature
   set is readable directly rather than inferred.
2. **Good: a live URL** the agent can open in a browser, click through, and
   screenshot. Real interaction behavior, but colors/spacing have to be
   estimated from renders rather than read exactly.
3. **Weak: screenshots plus a description.** Usable, but expect drift from
   the real thing.

If both (1) and (2) are available, provide both — code for precision, the
live app for anything that only shows up in interaction (loading states,
transitions, empty states).

---

## The prompt

Paste the block below to start the next session. Fill in the bracketed
access details before sending.

```
Claude Code Session — SolidGrade Web App Design & Feature Discovery

This session is preparation for Milestone 2 of SolidGrade Desktop, not a
build session. Do not write any application code and do not modify
SPEC_v0.2_SolidGrade_Desktop.md. The goal is a single new reference document.

Context: SolidGrade Desktop (this repo) currently has a bare-bones,
deliberately unstyled single screen (see MILESTONE_1_REPORT.md — Step 5).
The instructor has an existing product, a web app called "SolidGrade," whose
look, feel, button style, color scheme, and navigation the desktop app's real
UI (built in Milestone 2+) needs to match. This session's job is to study
that web app and write down everything a future build session needs to
reproduce it faithfully — colors, typography, component patterns, layout,
navigation, and its full feature set — so nothing gets guessed or invented
later.

Access to the SolidGrade web app: [PASTE REPO LINK, OR NOTE THAT SOURCE HAS
BEEN COPIED INTO THIS REPO AT <path>, AND/OR PASTE A LIVE URL HERE]

Deliverable: SOLIDGRADE_WEB_REFERENCE.md at the repo root, covering:
1. Design tokens — exact color hex values, typography (family/sizes/weights),
   spacing scale, border radii, shadows. Pull these from real CSS/theme
   source if available; only estimate from screenshots as a last resort, and
   say clearly when you're estimating versus reading an exact value.
2. Component patterns — buttons (all states: default/hover/disabled/etc.),
   cards, tables, forms, navigation elements, status/badge indicators.
3. Layout and navigation structure — persistent chrome, how screens relate,
   how a user moves between them.
4. A full feature/capability inventory, screen by screen — what the web app
   actually does today. This matters as much as the visuals: Milestone 2
   should not accidentally drop something the instructor already relies on.

If you're given the web app's source code, read it directly rather than
inferring from rendered output — exact values over eyeballed ones. If you're
given a live URL, use the browser tool to click through every screen and
state you can reach, including edge cases like empty states and error states,
not just the happy path.

Do not attempt to build or modify anything in SolidGrade Desktop this
session. If you notice something in this repo that the design reference will
need to interact with, note it in the new document rather than changing code.
```

---

## Everything else on the list, for after this discovery session

This is the same priority order given to the instructor in chat, kept here
for reference. Full detail on each is in `MILESTONE_1_REPORT.md` under
"Post-milestone: first real-user testing" and "What Milestone 2 should be."

1. Diagnose and fix "refreshing the browser loses the app"; decide whether
   the app should become a real standalone window instead of a browser tab
   (the instructor raised this independently — worth taking seriously, since
   it would also structurally fix the refresh bug).
2. Build the real UI to match SolidGrade's existing look and feel — this is
   what the discovery session above unblocks.
3. Fix `sw_timeout.py` for real and wire up §11.3 timeout handling — right
   now a genuine SolidWorks stall during grading still hangs the app forever.
4. Run one real multi-student batch (not just one file at a time) to see how
   the app holds up over a longer, real-sized run.
5. Build §9 — submission ingestion and attribution. The largest remaining
   piece of unbuilt work, and the spec's own highest-risk subsystem.
6. Smaller reliability items: checkpointing (§11.1), a dedicated COM worker
   thread instead of the current lock-based mitigation, surfacing the popup
   dismisser's new diagnostics in the status UI, and the one remaining
   diagnostic script (`diag_export.py`) not yet re-run on this machine's
   SolidWorks edition.
