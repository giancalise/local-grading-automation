# SolidGrade Web App — Design & Feature Reference

**Purpose.** SolidGrade Desktop's real UI (Milestone 2+) must look and behave like the
instructor's existing SolidGrade web app, and must not silently drop capabilities that
app already provides. This document records everything a future build session needs to
reproduce it faithfully — exact design tokens, component recipes, layout, navigation, and
a screen-by-screen feature inventory.

**This document changes nothing.** No application code was written and
`SPEC_v0.2_SolidGrade_Desktop.md` was not modified during the session that produced it.
Where this reference notes something Milestone 2 will need to interact with, it is
recorded here rather than acted on.

---

## 0. Provenance and confidence

### What was read

The web app's **source code** was read directly — nothing in this document is eyeballed
from a screenshot, and no live instance was visited.

| Source | Detail |
|---|---|
| Repository | `https://github.com/giancalise/Solidgrade` |
| Commit read | `99a68a5` — *"feat: Add gradebook view and navigation"*, 2026-04-02 (repo HEAD) |
| Files read | All 19 `.tsx`/`.ts` files under `src/`, plus `index.html`, `index.css`, `package.json`, `vite.config.ts`, `server.ts`, `firebase.json`, `firestore.rules`, `metadata.json`, `README.md` |
| Token source | `tailwindcss@4.1.14` `theme.css`, fetched from unpkg and converted OKLCH → sRGB locally |

### Confidence labels used throughout

Every value in this document carries one of three labels. **Treat them as load-bearing** —
the difference between an exact value and a derived one determines whether it is safe to
copy verbatim.

- **[EXACT]** — literally present in the SolidGrade source. Copy verbatim.
- **[TW-DEFAULT]** — not in SolidGrade's source; it is Tailwind CSS v4.1.14's default value
  for a utility class SolidGrade uses. Exact for the pinned version, and correct as long as
  Tailwind's own defaults are the reference. Hex values were computed from Tailwind's OKLCH
  definitions with a standard OKLab→sRGB conversion, so the final digit may differ by ±1
  from another converter.
- **[DERIVED]** — an inference, a summary, or a judgement call made while reading the code.
  Verify before relying on it.

**Nothing in this document is estimated from a screenshot.** No live URL was used, so a
handful of things a build session might want are genuinely unavailable — see
§9 "What this reference cannot tell you".

---

## 1. Stack, and how the design system is expressed

**[EXACT]** From `package.json` and `vite.config.ts`:

| Concern | Choice |
|---|---|
| Framework | React 19 + TypeScript 5.8, Vite 6 |
| Styling | **Tailwind CSS v4.1.14** via `@tailwindcss/vite` — CSS-first config, no `tailwind.config.js` |
| Routing | `react-router-dom` v7 (`BrowserRouter`) |
| Icons | `lucide-react` v0.546 — **the only icon set used** |
| Animation | `framer-motion` / `motion` v12 |
| 3D | `three` v0.183 + `three-stdlib` (`STLLoader`, `OrbitControls`) |
| PDF | `pdfjs-dist` v5.5 (client-side thumbnail generation) |
| Backend | Firebase (Auth, Firestore, Storage) — `firebase` v12.10 |
| Server | Express 5-style `express` v4 (`server.ts`) — health check, one email API, static/Vite serving |
| Email | `resend` v6.9 |
| Dates | `date-fns` v4 |

### The critical structural fact for Milestone 2

**[EXACT]** The *entire* custom theme is eight lines. This is all of `src/index.css`'s
`@theme` block:

```css
@theme {
  --color-sw-red: #E31E24;
  --color-sw-cyan: #00AEEF;
}
```

**[DERIVED]** Everything else — every gray, every radius, every shadow, the whole type
scale — is **stock Tailwind v4 defaults**. There is no custom font, no custom spacing
scale, no custom shadow. The visual identity is carried almost entirely by four things:

1. The two brand colors (`sw-red` dominant, `sw-cyan` secondary).
2. **Very heavy font weights** — `font-black` (900) and `font-bold` (700) are the norm for
   headings, labels, buttons, and even body-adjacent text. Regular weight is rare.
3. **Large border radii** — `rounded-xl` (12px) is the *minimum* for interactive elements;
   cards are `rounded-3xl` (24px); modals and hero panels reach 32–40px.
4. **Tiny all-caps micro-labels** — `text-[10px] font-black uppercase tracking-widest
   text-gray-400` appears on virtually every screen as the label style for stat tiles,
   table headers, and section headings.

**[DERIVED] Consequence for SolidGrade Desktop.** Per `MILESTONE_1_REPORT.md` Step 5, the
desktop app is Flask serving inline HTML/JS to a browser — so this design system is
directly reproducible as CSS. But the desktop app has **no build step**, so a Tailwind
toolchain is not the realistic path. The realistic path is a hand-written stylesheet of
CSS custom properties mirroring §2 plus component classes mirroring §3. That is exactly why
this document lists resolved values, not utility class names alone.

---

## 2. Design tokens

### 2.1 Brand colors

| Token | Value | Confidence | Notes |
|---|---|---|---|
| `--color-sw-red` | `#E31E24` | **[EXACT]** | Primary brand. Buttons, active nav, logo mark, focus accents. |
| `--color-sw-cyan` | `#00AEEF` | **[EXACT]** | Secondary. Grades/scores, "student" affordances, informational accents. |

**[DERIVED]** These are the SOLIDWORKS brand red and cyan, which is clearly deliberate.

**[EXACT]** Both are used at fractional opacity constantly, via Tailwind's slash syntax.
The recurring ones, resolved:

| Usage | Resolved value |
|---|---|
| `bg-sw-red/5` | `rgb(227 30 36 / 0.05)` |
| `bg-sw-red/10` | `rgb(227 30 36 / 0.10)` |
| `border-sw-red/20` | `rgb(227 30 36 / 0.20)` |
| `shadow-sw-red/20` | `rgb(227 30 36 / 0.20)` — colored glow, see §2.6 |
| `bg-sw-cyan/5` | `rgb(0 174 239 / 0.05)` |
| `bg-sw-cyan/10` | `rgb(0 174 239 / 0.10)` |
| `border-sw-cyan/20` | `rgb(0 174 239 / 0.20)` |
| `shadow-sw-cyan/20` | `rgb(0 174 239 / 0.20)` |

### 2.2 Neutral scale (gray)

**[TW-DEFAULT]** Tailwind v4's default `gray`. This is the app's entire neutral system —
backgrounds, borders, text, disabled states.

| Step | Hex | OKLCH | Where SolidGrade uses it |
|---|---|---|---|
| `gray-50` | `#f9fafb` | `oklch(98.5% 0.002 247.839)` | App background (light); input fills; hover fills; table header |
| `gray-100` | `#f3f4f6` | `oklch(96.7% 0.003 264.542)` | **Default border color (light)**; secondary button fill; tag chips |
| `gray-200` | `#e5e7eb` | `oklch(92.8% 0.006 264.531)` | Secondary button hover; avatar placeholder; some input borders |
| `gray-300` | `#d1d5dc` | `oklch(87.2% 0.01 258.338)` | Empty-state icons; toggle "off" track; disabled chevrons |
| `gray-400` | `#99a1af` | `oklch(70.7% 0.022 261.325)` | **Micro-label text**; icon default; placeholder text |
| `gray-500` | `#6a7282` | `oklch(55.1% 0.027 264.364)` | Secondary body text; inactive nav label |
| `gray-600` | `#4a5565` | `oklch(44.6% 0.03 256.802)` | Body text; secondary button text |
| `gray-700` | `#364153` | `oklch(37.3% 0.034 259.733)` | Form label text; dark-mode borders |
| `gray-800` | `#1e2939` | `oklch(27.8% 0.033 256.848)` | **Dark-mode surface-2**; dark borders |
| `gray-900` | `#101828` | `oklch(21% 0.034 264.665)` | **Primary text (light)**; **dark-mode card surface**; dark CTA panels |
| `gray-950` | `#030712` | `oklch(13% 0.028 261.692)` | **Dark-mode page background** |

### 2.3 Semantic status colors

**[TW-DEFAULT]** hex values; **[EXACT]** the role assignments (traced from the code).

| Role | Utility | Hex | Used for |
|---|---|---|---|
| Success fill | `green-50` | `#f0fdf4` | Passed checks, published state, "Results" button |
| Success mid | `green-500` | `#00c950` | ✓ marks, easy-difficulty badge, graded status dot |
| Success text | `green-600` | `#00a63e` | Grade ≥ 90, "Grades Published", submitted-file confirmation |
| Success border | `green-100/200` | `#dcfce7` / `#b9f8cf` | Dropzone success border, alert borders |
| Warning fill | `amber-50` | `#fffbeb` | Plagiarism-flag tile, timeout banner, override note |
| Warning mid | `amber-500` | `#fe9a00` | Active "Plagiarism" filter button |
| Warning text | `amber-600` | `#e17100` | Plagiarism count, "Overridden" label |
| Attention | `orange-500` | `#ff6900` | Pending-submission icon, weight-mismatch warning |
| Attention fill | `orange-50` | `#fff7ed` | Weight-sum warning banner, discrepancy panel |
| Info fill | `blue-50` | `#eff6ff` | "Grading in progress" banner, "Pending Grade" chip |
| Info text | `blue-600` | `#155dfc` | Running-job status text |
| Error fill | `red-50` | `#fef2f2` | Auth errors, danger zone, error banners |
| Error text | `red-600` | `#e7000b` | Error messages, delete affordances |
| Primary hover | `red-600` | `#e7000b` | **`btn-primary:hover`** — see the note below |
| Difficulty: medium | `yellow-100 / 600` | `#fef9c2` / `#d08700` | Medium badge on `ProblemDetail` |
| Theme toggle (dark) | `yellow-400` | `#fdc700` | Sun icon in dark mode |

> **[DERIVED] Note the primary-button hover mismatch.** `btn-primary` is
> `bg-sw-red` (`#E31E24`) but hovers to `hover:bg-red-600` (`#e7000b`) — Tailwind's red,
> not the brand red. The hover state is therefore a *slightly different hue*, not a shade
> of the brand color. This is almost certainly unintentional, but it is what the app does
> today. Milestone 2 should decide deliberately: reproduce it, or use a proper darkened
> `#E31E24`. Recommendation: use a darkened brand red (roughly `#c4181d`) and note the
> divergence, rather than importing an off-brand hover.

### 2.4 Difficulty badge colors

**[EXACT]** Two *different* mappings exist in the app for the same concept:

| Difficulty | On `ProblemList` cards | On `ProblemDetail` header |
|---|---|---|
| easy | `bg-green-500 text-white` | `bg-green-100 text-green-600` |
| medium | `bg-sw-cyan text-white` | `bg-yellow-100 text-yellow-600` |
| hard | `bg-sw-red text-white` | `bg-red-100 text-red-600` |

**[DERIVED]** These are inconsistent. If Milestone 2 needs difficulty badges, pick one —
the `ProblemList` solid-fill version is the more prominent and more brand-consistent of the
two.

### 2.5 Typography

**Font family — [TW-DEFAULT].** SolidGrade **never sets a font-family anywhere**. It
inherits Tailwind v4's `--font-sans`, applied by preflight via `--default-font-family`:

```css
font-family: ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji",
             "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji";
```

**[DERIVED]** On the Windows machines SolidGrade Desktop targets, this resolves to
**Segoe UI**. There is no webfont to match, no Google Font, nothing to download — a desktop
build that uses the same stack will render identically to the web app on the same machine.

`--font-mono` **[TW-DEFAULT]** is used in exactly one place (the file-path `<code>` snippets
on the Grading Automation page):

```css
font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
             "Liberation Mono", "Courier New", monospace;
```

**Type scale — [TW-DEFAULT] values, [EXACT] usage column.**

| Class | Size | Line height | Used for |
|---|---|---|---|
| `text-[8px]` | 8px | — | **[EXACT]** Sub-micro labels in dense gradebook tiles |
| `text-[9px]` | 9px | — | **[EXACT]** STL viewer hints |
| `text-[10px]` | 10px | — | **[EXACT]** *The* micro-label size — table headers, stat labels, status pills |
| `text-xs` | 0.75rem / 12px | `1.3333` | Metadata rows, small buttons, helper text |
| `text-sm` | 0.875rem / 14px | `1.4286` | Form labels, secondary body, list item subtitles |
| `text-base` | 1rem / 16px | `1.5` | Body default |
| `text-lg` | 1.125rem / 18px | `1.5556` | Card titles, emphasized numbers |
| `text-xl` | 1.25rem / 20px | `1.4` | Section headings (`h2`) |
| `text-2xl` | 1.5rem / 24px | `1.3333` | Page titles (mobile), modal titles, stat values |
| `text-3xl` | 1.875rem / 30px | `1.2` | **Page titles (desktop `h1`)** |
| `text-4xl` | 2.25rem / 36px | `1.1111` | Landing section headings |
| `text-5xl` | 3rem / 48px | `1` | Landing hero (sm), student final grade |
| `text-7xl` | 4.5rem / 72px | `1` | Landing hero (desktop) |

**Font weights — [TW-DEFAULT] values, [EXACT] usage.**

| Class | Weight | Where |
|---|---|---|
| `font-medium` | 500 | Rare — a few paragraphs only |
| `font-bold` | 700 | **Default for almost all UI text**: buttons, labels, nav items, list titles, metadata |
| `font-black` | 900 | Page titles, section headings, stat values, grades, micro-labels, logo |

**[DERIVED]** There is essentially no `font-normal` (400) text in the authenticated app.
This is the single most distinctive typographic trait, and the easiest thing to get wrong
by defaulting to normal-weight body copy.

**Letter spacing — [TW-DEFAULT] values, [EXACT] usage.**

| Class | Value | Where |
|---|---|---|
| `tracking-tighter` | `-0.05em` | Logo wordmark; theme-toggle label |
| `tracking-tight` | `-0.025em` | Landing hero `h1` |
| `tracking-wider` | `0.05em` | Dashboard stat labels |
| `tracking-widest` | `0.1em` | **The micro-label idiom** — nearly always paired with `uppercase` + `text-[10px]` + `font-black` |

### 2.6 Spacing

**[TW-DEFAULT]** Base unit `--spacing: 0.25rem` (4px). Every `p-N`/`gap-N`/`m-N` is `N × 4px`.

**[EXACT]** The values SolidGrade actually reaches for:

| Class | px | Typical use |
|---|---|---|
| `gap-1` / `p-1` | 4 | Tag rows; segmented-control padding |
| `gap-2` / `p-2` | 8 | Icon-button padding; tight groups |
| `gap-3` / `p-3` | 12 | List row padding; small cards |
| `gap-4` / `p-4` | 16 | **Default gap**; card padding (mobile) |
| `p-5` | 20 | Compact card padding |
| `gap-6` / `p-6` | 24 | **`.card` padding**; grid gutters; table cells |
| `gap-8` / `p-8` | 32 | **Page section spacing** (`space-y-8`); sidebar logo block; main content padding (desktop) |
| `space-y-12` | 48 | Student assignment list sections |
| `py-20` | 80 | Empty-state vertical padding |

### 2.7 Border radii

**[TW-DEFAULT]** values, **[EXACT]** usage. This is a high-radius design; getting these
right matters more than almost anything else for the "feel".

| Class | Value | Used for |
|---|---|---|
| `rounded` | 4px `[TW-DEFAULT]` | Tiny tag chips only |
| `rounded-md` | 6px | Segmented-control inner buttons; small badges |
| `rounded-lg` | 8px | Icon buttons; logo mark; small status tiles; inline chips |
| `rounded-xl` | **12px** | **Buttons, inputs, nav items, most interactive surfaces** |
| `rounded-2xl` | **16px** | Feature icon tiles; dropzones; inner panels; banners |
| `rounded-3xl` | **24px** | **`.card`**; modals; auth panel; settings avatar |
| `rounded-[2rem]` | 32px | Landing CTA panel; grading modal (desktop); role-select cards (mobile) |
| `rounded-[2.5rem]` | 40px | Role-select cards (desktop) |
| `rounded-full` | 9999px | Avatars; status pills; toggle switches; notification dot |

### 2.8 Shadows

**[TW-DEFAULT]** values, **[EXACT]** usage.

| Class | Value |
|---|---|
| `shadow-sm` | `0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)` |
| `shadow-md` | `0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)` |
| `shadow-lg` | `0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)` |
| `shadow-xl` | `0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)` |
| `shadow-2xl` | `0 25px 50px -12px rgb(0 0 0 / 0.25)` |

**The colored-glow idiom — [EXACT], and this is a signature move.** Anything filled with a
brand color gets a *tinted* drop shadow, not a neutral one. `shadow-lg shadow-sw-red/20`
means "the `shadow-lg` geometry, but colored `rgb(227 30 36 / 0.2)`":

```css
box-shadow: 0 10px 15px -3px rgb(227 30 36 / 0.2),
            0 4px 6px -4px rgb(227 30 36 / 0.2);
```

**[EXACT]** It appears on: `btn-primary`, the logo mark, every `bg-sw-red` icon tile,
class-card icons, student avatars in grading lists, the submit button, and the cyan
equivalent (`shadow-sw-cyan/20`) on cyan surfaces.

**[EXACT]** Also note `shadow-xl shadow-gray-200/50` on the auth panel and role-select
cards — a soft neutral-tinted lift, explicitly nulled in dark mode via `dark:shadow-none`.

### 2.9 Motion

**[EXACT]** usage; **[TW-DEFAULT]** underlying values.

| Pattern | Definition |
|---|---|
| Default transition | `transition-all` → `150ms cubic-bezier(0.4, 0, 0.2, 1)` |
| Theme / surface transition | `transition-colors duration-300` — on `body`, app shell, page roots |
| Button press | `active:scale-95` — **[EXACT]** on `btn-primary`, `btn-secondary`, `ThemeToggle` |
| Icon tile hover | `group-hover:scale-110` — on card/feature icon tiles |
| Spinner | `animate-spin` → `spin 1s linear infinite` |
| Pulsing text/timer | `animate-pulse` → `pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite` |
| Mobile drawer | `framer-motion` spring — `{ type: 'spring', damping: 25, stiffness: 200 }`, `x: '-100%'` → `0` **[EXACT]** |
| Modal entrance | `animate-in fade-in duration-200`, `animate-in zoom-in-95 duration-200` **[EXACT]** |
| Banner entrance | `animate-in slide-in-from-top duration-300` **[EXACT]** |

> **[DERIVED] Caveat on `animate-in` / `fade-in` / `zoom-in-95` / `slide-in-from-top`:**
> these are `tailwindcss-animate` utilities, and **that plugin is not in `package.json`**.
> They therefore compile to nothing — those animations do not actually run in the shipped
> app. If Milestone 2 wants them, it must implement them; if it wants parity, it should
> omit them. Either is defensible; just don't assume they currently work.

### 2.10 Breakpoints and container widths

**[TW-DEFAULT]** values, **[EXACT]** usage.

| Breakpoint | Min width | Role in SolidGrade |
|---|---|---|
| `sm` | 40rem / 640px | **Primary mobile→desktop switch** for typography, padding, button layout |
| `md` | 48rem / 768px | Grid column changes (2-col) |
| `lg` | 64rem / 1024px | **Sidebar appears**; 3-column dashboard layouts |
| `xl` | 80rem / 1280px | Rarely used |
| `2xl` | 96rem / 1536px | Not used |

**[EXACT]** Content container caps:

| Screen | Cap |
|---|---|
| App shell content | `max-w-7xl` = 80rem / 1280px |
| Landing / footer | `max-w-7xl` = 1280px |
| Settings | `max-w-5xl` = 64rem / 1024px |
| Grading Automation, Problem/Assignment forms | `max-w-4xl` = 56rem / 896px |
| Student assignment, Problem detail | `max-w-5xl` = 1024px |
| Auth card | `max-w-md` = 28rem / 448px |
| Grading modal | `max-w-4xl` = 896px |
| STL viewer modal | `max-w-6xl` = 72rem / 1152px |

### 2.11 Dark mode

**[EXACT]** Class-based, not media-query-based:

```css
@custom-variant dark (&:where(.dark, .dark *));
```

**[EXACT]** `ThemeContext.tsx` behavior:

1. Reads `localStorage.getItem('theme')`; accepts only `'dark'` or `'light'`.
2. **If unset, defaults by time of day** — dark when the local hour is `>= 18` or `< 6`,
   light otherwise. It does *not* consult `prefers-color-scheme`.
3. On change, adds the theme class to **both** `<html>` and `<body>`, sets
   `data-theme="light|dark"` on both, writes `localStorage`, and sets
   `document.documentElement.style.colorScheme`.
4. Toggle is a simple light↔dark flip. There is no "system" option.

**[EXACT]** Surface mapping:

| Role | Light | Dark |
|---|---|---|
| Page background | `white` / `gray-50` | `gray-950` `#030712` |
| Card / panel surface | `white` | `gray-900` `#101828` |
| Recessed surface (inputs, chips) | `gray-50` `#f9fafb` | `gray-800` `#1e2939` |
| Border | `gray-100` `#f3f4f6` | `gray-800` `#1e2939` |
| Input border | `gray-100` | `gray-700` `#364153` |
| Primary text | `gray-900` | `white` |
| Secondary text | `gray-500` | `gray-400` `#99a1af` |
| Brand tint background | `red-50` `#fef2f2` | `sw-red/10` |

**[EXACT] The global base-layer overrides in `index.css`.** These are unusual and easy to
miss — they are broad element selectors, not utilities:

```css
@layer base {
  body { @apply transition-colors duration-300 bg-white text-gray-900
                dark:bg-gray-950 dark:text-gray-100; }

  h1 { @apply dark:!text-sw-red; }                  /* ← every h1 turns brand red in dark */
  h2, h3, h4, h5, h6 { @apply dark:text-white; }
  p, span, label, div { @apply dark:text-gray-300; }

  .text-gray-900 { @apply dark:text-white; }
  .text-gray-800, .text-gray-700 { @apply dark:text-gray-100; }
  .text-gray-600, .text-gray-500 { @apply dark:text-gray-400; }
}
```

**[DERIVED]** Two things worth flagging to a future build session:

- **In dark mode, every `<h1>` on every page becomes `#E31E24`**, forced with `!important`.
  This is a genuine, visible identity trait of the dark theme — page titles are red. It is
  not a bug to "fix" without asking.
- The `p, span, label, div { dark:text-gray-300 }` rule is extremely broad and fights with
  utility classes; the `.text-gray-*` override block below it exists specifically to win
  those fights back. **[DERIVED]** A from-scratch CSS implementation should express this as
  a proper token system rather than replicating the specificity war.

**[DERIVED] Dark-mode coverage is incomplete.** Several screens were written before dark
mode landed and still hardcode light-only classes — `ProblemList`, `ProblemForm`,
`ProblemDetail`, `Gradebook`, `AutomatedGradebook`, and `GradingAutomation` are largely
light-only, saved from looking broken only by the global base-layer overrides above. The
shell, Dashboard, Assignments, Classes, Settings, and Auth are properly dual-themed.
Milestone 2 should implement dark mode *completely* rather than reproducing this gap.

---

## 3. Component patterns

All class strings in this section are **[EXACT]** — copied from source. The resolved CSS
under each is **[DERIVED]** (a faithful expansion of those utilities using §2's values).

### 3.1 Buttons

#### Primary button — `.btn-primary`

**[EXACT]** definition from `index.css`:

```css
.btn-primary {
  @apply bg-sw-red text-white px-6 py-2 rounded-xl font-bold
         hover:bg-red-600 transition-all shadow-lg shadow-sw-red/20
         active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed;
}
```

**[DERIVED]** resolved:

```css
.btn-primary {
  background: #E31E24;
  color: #fff;
  padding: 0.5rem 1.5rem;          /* 8px 24px */
  border-radius: 0.75rem;          /* 12px */
  font-weight: 700;
  box-shadow: 0 10px 15px -3px rgb(227 30 36 / 0.2),
              0 4px 6px -4px rgb(227 30 36 / 0.2);
  transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
}
.btn-primary:hover    { background: #e7000b; }   /* see §2.3 hover-mismatch note */
.btn-primary:active   { transform: scale(0.95); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
```

**[EXACT]** States: default / hover / active / disabled. **There is no defined `:focus` or
`:focus-visible` style** — see §3.11.

**[EXACT]** Common size overrides at call sites: `py-3`, `py-4 text-lg`, `py-2 px-4 text-sm`,
`px-12 py-4`. The base class is routinely overridden rather than varianted.

#### Secondary button — `.btn-secondary`

**[EXACT]**:

```css
.btn-secondary {
  @apply bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300
         px-6 py-2 rounded-xl font-bold
         hover:bg-gray-200 dark:hover:bg-gray-700 transition-all
         active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed;
}
```

**[DERIVED]** resolved (light): `background #f3f4f6`, `color #4a5565`, same padding/radius/
weight as primary, `hover background #e5e7eb`, no shadow.

> **[DERIVED] Known defect worth knowing about.** `.btn-secondary` sets **no border-width**,
> yet many call sites add border *colors* — e.g. `border-green-200`, `border-sw-cyan/20`,
> `border-gray-200` on the Automated Gradebook publish toggle and the Assignment Detail
> action buttons. Without a `border` width utility those colors render nothing. The buttons
> appear borderless today. Milestone 2 should decide intentionally whether these buttons
> have outlines; the source's *intent* was clearly that they do.

#### Tinted action buttons

**[EXACT]** A recurring pattern for secondary actions — a faint brand-tinted pill that
inverts to solid on hover:

```html
<!-- red variant -->
class="px-3 py-2 bg-sw-red/10 text-sw-red rounded-lg text-xs font-bold
       hover:bg-sw-red hover:text-white transition-all
       flex items-center justify-center gap-1.5"

<!-- cyan variant -->
class="px-3 py-2 bg-sw-cyan/10 text-sw-cyan rounded-lg text-xs font-bold
       hover:bg-sw-cyan hover:text-white transition-all ..."

<!-- green variant -->
class="px-3 py-2 bg-green-50 dark:bg-green-900/20 text-green-600 rounded-lg
       text-xs font-bold hover:bg-green-600 hover:text-white transition-all ..."

<!-- neutral variant -->
class="px-3 py-2 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400
       rounded-lg text-xs font-bold hover:bg-gray-200 dark:hover:bg-gray-700 ..."
```

**[EXACT]** This is the row-action set on `AssignmentList` (Results / Test / Edit / Grade).

#### Icon button

**[EXACT]**:

```html
class="p-2 text-gray-400 hover:text-sw-red transition-colors"
class="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
```

**[DERIVED]** Two variants: color-only (list-row actions) and background-on-hover (back
buttons, modal close). Icons are lucide, `size={16|18|20|24}`.

#### Segmented control / tab group

**[EXACT]** — used for the My/Community tab switch and the gradebook filters:

```html
<!-- container -->
class="flex gap-1 bg-gray-100 dark:bg-gray-800 p-1 rounded-xl w-full sm:w-fit"

<!-- active segment -->
class="flex-1 sm:flex-none px-4 py-2 rounded-lg text-sm font-bold transition-all
       bg-white dark:bg-gray-700 text-sw-red shadow-sm"

<!-- inactive segment -->
class="... text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
```

**[EXACT]** The gradebook filter variant uses solid fills for active state instead:
`bg-gray-900 text-white` (All), `bg-sw-red text-white` (Review), `bg-amber-500 text-white`
(Plagiarism).

#### Selection cards (radio-as-button)

**[EXACT]** — visibility pickers, difficulty pickers, invite-role pickers:

```html
<!-- selected -->
class="w-full flex items-center gap-3 p-3 rounded-xl border-2 transition-all
       border-sw-red bg-red-50 text-sw-red"
<!-- unselected -->
class="... border-gray-100 text-gray-500 hover:border-gray-200"
```

#### Toggle switch

**[EXACT]** — hand-rolled, on `AssignmentForm`:

```html
<button class="w-12 h-6 rounded-full transition-colors relative
               [on: bg-sw-red] [off: bg-gray-300]">
  <div class="absolute top-1 w-4 h-4 bg-white rounded-full transition-all
              [on: left-7] [off: left-1]"></div>
</button>
```

**[DERIVED]** 48×24px track, 16px knob, 4px inset. Note it is a `<button>` with no
`role="switch"` and no `aria-checked`.

### 3.2 Cards — `.card`

**[EXACT]**:

```css
.card {
  @apply bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800
         rounded-3xl p-6 shadow-sm transition-all duration-300;
}
```

**[DERIVED]** resolved (light):

```css
.card {
  background: #fff;
  border: 1px solid #f3f4f6;
  border-radius: 1.5rem;   /* 24px */
  padding: 1.5rem;         /* 24px */
  box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1);
  transition: all 300ms cubic-bezier(0.4, 0, 0.2, 1);
}
```

**[EXACT]** Standard modifiers seen at call sites:

| Modifier | Effect |
|---|---|
| `hover:border-sw-red/20` | The universal "this card is clickable" hover |
| `group` + `group-hover:text-sw-red` | Title turns brand red on card hover |
| `p-0 overflow-hidden` | For cards containing a full-bleed image or table |
| `p-4 sm:p-6` | Responsive padding |
| `bg-gray-50/50 border-dashed border-2` | **The empty-state card** |

### 3.3 Forms

#### Input — `.input-field`

**[EXACT]**:

```css
.input-field {
  @apply w-full px-4 py-2 bg-gray-50 dark:bg-gray-800
         border border-gray-100 dark:border-gray-700 rounded-xl outline-none
         focus:border-sw-red/50 dark:focus:border-sw-red/50 transition-all
         dark:text-white dark:placeholder-gray-500;
}
```

**[DERIVED]** resolved (light):

```css
.input-field {
  width: 100%;
  padding: 0.5rem 1rem;            /* 8px 16px */
  background: #f9fafb;
  border: 1px solid #f3f4f6;
  border-radius: 0.75rem;          /* 12px */
  outline: none;
  transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
}
.input-field:focus { border-color: rgb(227 30 36 / 0.5); }
```

**[EXACT]** Common overrides: `py-3 px-4` (forms), `pl-10`/`pl-12` (leading icon),
`min-h-[80px]`/`min-h-[120px]`/`min-h-[150px] py-3` (textarea),
`bg-gray-100 cursor-not-allowed` (disabled).

**[EXACT]** An *alternate* input treatment coexists on `AssignmentList` / `ProblemList` /
`ProblemForm` — ring-based focus rather than border-based:

```html
class="w-full pl-10 pr-4 py-2.5 bg-gray-50 dark:bg-gray-800
       border border-gray-200 dark:border-gray-700 rounded-xl outline-none
       focus:ring-2 focus:ring-sw-red/20 focus:border-sw-red transition-all"
```

**[DERIVED]** Two focus idioms exist (`border-sw-red/50` vs `ring-2 ring-sw-red/20 +
border-sw-red`). The ring version is more visible and more accessible; recommend
standardizing on it.

#### Label

**[EXACT]**: `class="block text-sm font-bold text-gray-700 dark:text-gray-300 mb-2"`

**[EXACT]** Micro-label variant (used for dense/technical fields):
`class="block text-[10px] font-black text-gray-400 uppercase tracking-widest mb-2"`

#### Leading-icon input

**[EXACT]** — icon absolutely positioned, input padded to clear it:

```html
<div class="relative">
  <Search class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
  <input class="input-field pl-10" />
</div>
```

`left-3` + `pl-10` for 18px icons; `left-4` + `pl-12` for the Settings form.

#### File dropzone

**[EXACT]** — hidden `<input type="file">` + `<label>` styled as the drop target, with three
states:

```html
<!-- idle -->
class="flex flex-col items-center justify-center p-6 sm:p-8 border-2 border-dashed
       rounded-2xl cursor-pointer transition-all relative
       border-gray-200 hover:border-sw-red/20 hover:bg-red-50"
<!-- drag active -->
class="... border-sw-red bg-red-50"
<!-- populated -->
class="... border-green-200 bg-green-50"
```

**[EXACT]** Populated state also renders a small absolute clear button at `top-2 right-2`,
and swaps the upload icon to `text-green-500`.

**[DERIVED]** Milestone 2 note: SolidGrade Desktop deliberately does **not** upload files
(`MILESTONE_1_REPORT.md` Step 5 / SPEC §13 — student files are referenced, never copied),
and uses native `tkinter.filedialog` pickers instead. So this dropzone pattern should be
adapted into a **path picker** with the same visual language — dashed 2px border,
`rounded-2xl`, idle/hover/chosen states, green when populated — rather than reproduced as a
literal drop target.

### 3.4 Tables

**[EXACT]** — the pattern is identical in `Gradebook` and `AutomatedGradebook`:

```html
<div class="card p-0 overflow-hidden">
  <!-- toolbar -->
  <div class="p-6 border-b border-gray-100 flex flex-col md:flex-row md:items-center
              justify-between gap-4 bg-gray-50/50"> … </div>

  <div class="overflow-x-auto">
    <table class="w-full text-left border-collapse">
      <thead>
        <tr class="bg-gray-50 border-b border-gray-100">
          <th class="p-6 text-[10px] font-black uppercase tracking-widest
                     text-gray-400 min-w-[200px]">Student</th>
          <th class="p-6 text-[10px] font-black uppercase tracking-widest
                     text-gray-400 text-center">Total</th>
        </tr>
      </thead>
      <tbody>
        <tr class="border-b border-gray-50 hover:bg-gray-50/50 transition-colors group">
          <td class="p-6"> … </td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
```

**[EXACT]** Distinctive details:

- Cell padding is `p-6` (24px) — **generous**, not a dense data grid.
- Header text is the 10px black uppercase micro-label.
- Header background `gray-50`; header bottom border `gray-100`; row borders `gray-50`.
- Row hover `bg-gray-50/50`.
- `Gradebook` pins the first column: `sticky left-0 bg-gray-50 z-10` on the header cell and
  `sticky left-0 bg-white group-hover:bg-gray-50/50 z-10` on body cells.
- `AutomatedGradebook` tints flagged rows: `bg-sw-red/5` when `flags.needs_review`.
- Empty state is a full-width `<td colSpan>` with `p-20 text-center` and a large gray icon.

**[EXACT]** Grade-value color thresholds in the gradebook table:

| Score | Color |
|---|---|
| ≥ 90 | `text-green-600` `#00a63e` |
| ≥ 70 | `text-sw-cyan` `#00AEEF` |
| < 70 | `text-sw-red` `#E31E24` |

**[EXACT]** Boolean checks render as `✓` in `text-green-500` / `✗` in `text-sw-red`.

### 3.5 Status badges and pills

**[EXACT]** The base pill:

```html
class="px-2.5 py-0.5 rounded-full text-[10px] sm:text-xs font-bold
       uppercase tracking-wider"
```

**[EXACT]** And the "micro-chip" variant:

```html
class="px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-widest"
```

**[EXACT] The complete status→style mapping**, gathered across screens. This is the table
Milestone 2 most needs, because these statuses are shared with the desktop grading pipeline:

**Grading job status** (`grading_jobs.status`) — used on Dashboard, Assignment Detail:

| Status | Background | Foreground | Icon (lucide) | Banner copy |
|---|---|---|---|---|
| `pending` | `gray-100` | `gray-600` / `gray-400` | `Clock` | "Waiting for grading machine…" |
| `running` | `blue-50` | `blue-600` | `Loader2` + `animate-spin` | "Grading in progress… (N students)" |
| `complete` | `green-50` | `green-600` | `CheckCircle2` | "Grading complete" |
| `timeout` | `amber-50` | `amber-600` | `AlertCircle` | "Grading timed out. Please check the desktop client." |
| `error` | `red-50` | `red-600` | `AlertCircle` | "Grading error: {error}" |

**Student attempt status** (`attempts.status`):

| Status | Instructor view (GradingPage) | Student list view |
|---|---|---|
| `started` | `bg-gray-100 text-gray-500` + `Clock` | `bg-sw-red text-white` — "In Progress" |
| `submitted` | `bg-orange-50 text-orange-600` + `AlertCircle` | `bg-sw-cyan text-white` — "Submitted" |
| `graded` | `bg-green-50 text-green-600` + `CheckCircle2` | `bg-green-500 text-white` — "Graded: N%" |
| *(none, past due)* | — | `bg-red-100 text-red-600` — "Missing" |
| *(none)* | — | `bg-gray-100 text-gray-500` — "Not Started" |

**Assignment status / visibility:**

| Value | Style | Icon |
|---|---|---|
| `published` | `bg-green-50 dark:bg-green-900/20 text-green-600` | — |
| `draft` | `bg-gray-100 dark:bg-gray-800 text-gray-500` | — |
| `private` | `bg-gray-100 dark:bg-gray-800 text-gray-500` | `Lock` |
| `public_instructors` | `bg-sw-red/10 text-sw-red` | `Shield` |
| `public_general` | `bg-sw-cyan/10 text-sw-cyan` | `Globe` |

**Result flags** (Automated Gradebook, rendered as small bordered icon tiles):

| Flag | Style | Icon |
|---|---|---|
| `plagiarism` | `text-amber-500 bg-amber-50 border-amber-100 p-1.5 rounded-lg` | `ShieldAlert` |
| `needs_review` | `text-sw-red bg-sw-red/5 border-sw-red/10 p-1.5 rounded-lg` | `AlertCircle` |
| *(clean)* | `text-green-500 bg-green-50 border-green-100 p-1.5 rounded-lg` | `ShieldCheck` |

### 3.6 Modals

**[EXACT]** Two shapes are used.

**Simple modal** (Create Class, Invite, confirmation dialogs):

```html
<div class="fixed inset-0 z-50 flex items-center justify-center p-4">
  <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={close}></div>
  <div class="relative bg-white dark:bg-gray-900 rounded-3xl w-full max-w-md
              p-6 sm:p-8 shadow-2xl">
    …
  </div>
</div>
```

**Scrolling modal with header/footer** (Grade Detail, Create Problem, STL viewer):

```html
<div class="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4
            bg-gray-900/60 backdrop-blur-sm">
  <div class="bg-white dark:bg-gray-950 w-full max-w-4xl max-h-[95vh] sm:max-h-[90vh]
              rounded-2xl sm:rounded-[2rem] shadow-2xl overflow-hidden flex flex-col">
    <header class="p-4 sm:p-8 border-b border-gray-100 dark:border-gray-800
                   bg-gray-50/50 dark:bg-gray-900/50 shrink-0"> … </header>
    <div class="flex-1 overflow-y-auto p-4 sm:p-8 space-y-6 sm:space-y-8"> … </div>
    <footer class="p-4 sm:p-8 border-t border-gray-100 dark:border-gray-800
                   bg-gray-50/50 dark:bg-gray-900/50 shrink-0"> … </footer>
  </div>
</div>
```

**[EXACT]** Consistent traits: `z-50` (`z-[60]` for nested — ProblemModal and STL
fullscreen), scrim `black/50` or `gray-900/60` **always with `backdrop-blur-sm`** (8px),
`shadow-2xl`, close button is a lucide `X size={24}` at top-right, backdrop click closes.

**[DERIVED]** No focus trap, no `Escape` handler, no `role="dialog"` anywhere.

### 3.7 Empty states

**[EXACT]** — one consistent pattern:

```html
<div class="py-20 text-center card bg-gray-50/50 border-dashed border-2">
  <Icon class="mx-auto text-gray-300 mb-4" size={48} />
  <h3 class="text-xl font-bold text-gray-400">No {things} found</h3>
  <p class="text-gray-400 mt-2">{Call to action.}</p>
</div>
```

**[EXACT]** Compact variant: `py-12`, `size={32}`, no `<h3>`.
**[EXACT]** Copy seen: "No assignments found" / "Create your first assignment to get
started." · "No problems found" / "Start building your problem bank today." · "No classes
found" / "Create your first class to start teaching." (instructor) or "You haven't been
invited to any classes yet." (student) · "No submissions yet" / "Student submissions will
appear here once they start the assignment." · "No active assignments." · "No past
assignments." · "No invitations sent yet."

### 3.8 Loading states

**[EXACT]** Ring spinner, always the same construction:

```html
<div class="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-sw-red"></div>
```

**[EXACT]** `h-12 w-12` for full-page, `h-8 w-8` for in-page, `h-5 w-5` for inline-in-button
(with `border-white`). Always followed by `<p class="text-gray-500 font-bold">Loading …</p>`.

**[EXACT]** Full-app boot state (`App.tsx`) — worth copying almost verbatim for the desktop
startup screen:

> "Initializing SolidGrade..." (`font-bold animate-pulse`), with, 32px below,
> "If this takes more than 10 seconds, please check your connection."
> (`text-xs text-gray-400`).

**[EXACT]** Inline button spinner: lucide `Loader2` + `animate-spin`, `size={16|18|20}`.

### 3.9 Alert / feedback banners

**[EXACT]**:

```html
<!-- error -->
class="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 p-4 rounded-xl
       text-sm font-bold mb-6 border border-red-100 dark:border-red-900/30"
<!-- success -->
class="bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400 p-4
       rounded-xl text-sm font-bold flex items-center gap-2
       border border-green-100 dark:border-green-900/30"
<!-- warning -->
class="flex items-center gap-2 p-3 bg-orange-50 text-orange-700 rounded-xl
       border border-orange-100"
<!-- job status banner (full width, top of page) -->
class="px-6 py-4 rounded-2xl flex items-center justify-between"  /* + status colors */
```

### 3.10 Avatars

**[EXACT]** Initial-letter circles, sized by context:

| Size | Class | Where |
|---|---|---|
| 32px | `w-8 h-8 rounded-full … text-xs font-black` | Table rows, member lists |
| 40px | `w-10 h-10 rounded-full … font-bold` | Sidebar user, header, list rows |
| 48px | `w-12 h-12 rounded-full … text-xl font-black` | Grading list, modal header |
| 96–112px | `w-24 h-24 sm:w-28 sm:h-28 rounded-3xl` | Settings profile (note: **rounded-3xl, not full**) |

**[EXACT]** Fills: `bg-sw-red text-white` (instructor/self), `bg-sw-cyan text-white`
(student in class management), `bg-gray-200 text-gray-500` (generic), `bg-gray-100
text-gray-500` (header link). Content is `displayName.charAt(0)` with `email.charAt(0)` as
fallback. Stacked avatar groups use `flex -space-x-2` with
`border-2 border-white dark:border-gray-900`.

### 3.11 Focus and accessibility — [DERIVED], read this before rebuilding

Reading the source, the following are simply absent. Milestone 2 should treat these as
**improvements to make**, not as fidelity to preserve:

- **No visible focus indicator.** `.input-field` sets `outline-none` and styles only
  `:focus` (not `:focus-visible`) via border color; buttons define no focus style at all.
  Keyboard navigation is effectively invisible.
- **No focus trapping, no `Escape` key handling, and no `role="dialog"`** on any modal.
- **Toggle switches** are plain `<button>`s without `role="switch"` / `aria-checked`.
- **`aria-label` appears exactly once** in the entire app — on `ThemeToggle`. Every other
  icon-only button (bell, search, back, close, delete, override) is unlabeled.
- **Tables** have no `scope` attributes and no caption.
- **`window.confirm()` / `window.alert()` / `window.prompt()` are used for real destructive
  and data-entry flows** — delete problem, delete assignment, copy problem, and (notably)
  **the manual grade override in the Automated Gradebook is a `window.prompt()`**.
  **[DERIVED]** That last one is a genuine UX weak point the desktop app should improve on.
- **Color-only status encoding** in gradebook `✓`/`✗` cells (mitigated slightly by the
  glyphs themselves).

---

## 4. Layout and navigation

### 4.1 The app shell — `components/Layout.tsx`

**[EXACT]** Structure:

```
<div class="min-h-screen bg-gray-50 dark:bg-gray-950 flex transition-colors duration-300">

  <aside class="hidden lg:flex flex-col w-72 bg-white dark:bg-gray-900
                border-r border-gray-100 dark:border-gray-800 sticky top-0 h-screen">
     [p-8]  Logo (size="sm")
     [flex-1 px-4 space-y-1]  nav items
     [p-4 border-t]  user card + Logout
  </aside>

  <main class="flex-1 flex flex-col min-w-0">
    <header class="bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800
                   h-16 lg:h-20 flex items-center justify-between
                   px-4 lg:px-8 sticky top-0 z-10">
       [lg:hidden]  hamburger + Logo (icon only)
       [hidden sm:flex]  search box, max-w-xs / lg:max-w-md, mx-4
       [ml-auto]  ThemeToggle · Bell (with dot) · avatar → /settings
    </header>

    <div class="p-4 lg:p-8 max-w-7xl mx-auto w-full">
      <Outlet />
    </div>
  </main>

  [mobile drawer: framer-motion, w-72, spring]
</div>
```

**[EXACT]** Key dimensions:

| Element | Value |
|---|---|
| Sidebar width | `w-72` = 18rem / **288px** |
| Sidebar visibility | `hidden lg:flex` — hidden below 1024px |
| Header height | **64px** mobile, **80px** at `lg` |
| Header padding | `px-4` mobile, `px-8` at `lg` |
| Content padding | `p-4` mobile, `p-8` at `lg` |
| Content max width | `max-w-7xl` = **1280px**, centered |
| Header `z-index` | `z-10`; mobile drawer `z-50`; modals `z-50`, nested `z-[60]` |
| Sidebar/header position | `sticky top-0`; sidebar `h-screen` |

**[EXACT]** Nav item styling:

```html
<!-- active -->
class="flex items-center gap-3 px-4 py-3 rounded-xl font-bold transition-all
       bg-red-50 dark:bg-sw-red/10 text-sw-red"
<!-- inactive -->
class="... text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800
       hover:text-gray-900 dark:hover:text-white"
```

**[EXACT]** Active detection is `location.pathname.startsWith(item.path)`.
**[DERIVED]** This means `/classes/:id/gradebook` lights up *both* "Classes" and
"Gradebook" (they share the `/classes` path) — a real, visible quirk.

**[EXACT]** Logout button reuses the nav item shape but hovers red:
`hover:bg-red-50 dark:hover:bg-sw-red/10 hover:text-sw-red`.

### 4.2 Navigation items and role gating

**[EXACT]** from `Layout.tsx`:

| Label | Path | Icon | Shown to |
|---|---|---|---|
| Dashboard | `/dashboard` | `LayoutDashboard` | everyone |
| Assignments | `/assignments` | `FileText` | everyone |
| Problems | `/problems` | `BookOpen` | everyone |
| Classes | `/classes` | `Users` | everyone |
| Grading Automation | `/grading-automation` | `Terminal` | **instructor / co-instructor only** |
| Gradebook | `/classes` | `TrendingUp` | **instructor / co-instructor only** |
| Settings | `/settings` | `SettingsIcon` | everyone |

**[DERIVED]** "Gradebook" points at `/classes`, the same target as "Classes" — you pick a
class first, then open its gradebook. Not a dedicated route.

### 4.3 The logo

**[EXACT]** `components/Logo.tsx` — a rounded-square brand mark plus a wordmark:

- **Mark**: `bg-sw-red rounded-lg shadow-lg shadow-sw-red/20`, containing a white
  3-stroke "layers/stack" SVG at 75% of the box:
  ```
  viewBox 0 0 24 24, fill none, stroke white, strokeWidth 3, round caps/joins
  path: M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5
  ```
  (**[DERIVED]** this is the Feather/lucide `layers` glyph.)
- **Mark sizes**: `sm` 24px, `md` 32px, `lg` 48px.
- **Wordmark**: `font-black tracking-tighter` — `SOLID` in `text-gray-900 dark:text-white`,
  `GRADE` in `text-sw-red`, no space. Text sizes: `sm` `text-lg`, `md` `text-2xl`,
  `lg` `text-4xl`. `gap-3` (12px) between mark and wordmark.
- Clicking navigates to `/dashboard` if signed in, `/` otherwise.
- **[EXACT]** Browser title: `SolidGrade | Automated SOLIDWORKS Grading`.

### 4.4 Complete route map

**[EXACT]** from `App.tsx`. Routes inside the `<Layout>` group get the shell; the two above
it are full-bleed.

| Path | Component | Shell? | Guard |
|---|---|---|---|
| `/` | `LandingPage` | no | redirects to `/dashboard` if signed in |
| `/auth` | `AuthPage` | no | redirects to `/dashboard` if signed in; `?mode=signup` |
| `/dashboard` | `Dashboard` | yes | auth |
| `/assignments` | `AssignmentList` | yes | auth |
| `/assignments/new` | `AssignmentForm` | yes | auth |
| `/assignments/:id` | `AssignmentDetail` | yes | auth; **students auto-redirect to `/attempt`** |
| `/assignments/:id/edit` | `AssignmentForm` | yes | auth |
| `/assignments/:id/test` | `StudentAssignment` | yes | auth — instructor preview mode |
| `/assignments/:id/attempt` | `StudentAssignment` | yes | auth |
| `/assignments/:id/grading` | `GradingPage` | yes | auth |
| `/assignments/:id/gradebook` | `AutomatedGradebook` | yes | auth |
| `/my-assignments` | `StudentAssignmentList` | yes | auth |
| `/problems` | `ProblemList` | yes | auth |
| `/problems/new` | `ProblemForm` | yes | auth |
| `/problems/:id` | `ProblemDetail` | yes | auth |
| `/problems/:id/edit` | `ProblemForm` | yes | auth |
| `/classes` | `ClassManagement` | yes | auth; `?manage=<classId>` deep-links the manage modal |
| `/classes/:classId/gradebook` | `Gradebook` | yes | auth |
| `/grading-automation` | `GradingAutomation` | yes | auth + **instructor role, else `<Navigate to="/">`** |
| `/settings` | `Settings` | yes | auth |

**[DERIVED] Dead links.** The landing page links to `/demo` ("Watch Demo") and `/contact`
("Talk to Sales"); neither route exists. The footer's Privacy / Terms / Support / API links
are all `href="#"`. Not features — just unbuilt.

**[DERIVED] Orphaned route.** `/my-assignments` (`StudentAssignmentList`) is fully built and
functional but **is not linked from the sidebar**. Students reach the same content through
"Assignments" (`AssignmentList`'s student branch) instead. This is a real, complete screen
that is currently unreachable through normal navigation — see §5.13.

### 4.5 How a user moves through the app

**[DERIVED]** — traced from the links in the code.

**Instructor flow:**

```
Landing → Auth (role: Instructor) → Dashboard
  ├─ Classes → create class → Manage modal (edit, members) → Invite modal (single/bulk)
  │            └─ Gradebook (manual grades, per-class × per-assignment matrix)
  ├─ Problems → Create/Edit Problem (upload model, drawing, .slddrw, extras, tags)
  ├─ Assignments → Create Assignment (pick class, pick problems, weights, timing,
  │                 visibility, draft/publish; can create a Problem inline via modal)
  │  └─ Assignment Detail
  │       ├─ Test  → StudentAssignment in preview mode
  │       ├─ Auto Grade → writes a `grading_jobs` doc → banner tracks status
  │       ├─ Grading → GradingPage (per-student manual grading, 3D compare, Sync Grades)
  │       └─ Gradebook → AutomatedGradebook (auto results, flags, override, publish, CSV)
  ├─ Grading Automation → download/install instructions for the desktop client
  └─ Settings
```

**Student flow:**

```
Landing → Auth (role: Student) → Dashboard
  ├─ Classes → Join Class (from an invitation)
  ├─ Assignments → Start / View
  │   └─ StudentAssignment → Start Attempt → upload per problem → Submit
  │        └─ after grading is published: automated grade breakdown + 3D comparison
  └─ Settings
```

---

## 5. Feature inventory, screen by screen

Everything in this section is **[EXACT]** unless marked otherwise — it describes what the
code at commit `99a68a5` actually does.

### 5.1 Landing page — `/`

- Top nav: logo, theme toggle, "Login" (hidden below `sm`), "Get Started" → `/auth?mode=signup`.
- Hero: full-bleed background image (`sw-3dcad-hero-mechanical-sheet-metal-productivity-001_1.png`,
  ~810 KB, bundled in `src/`) at `opacity-40` under a white→transparent (or gray-950→transparent)
  gradient. Headline: **"Learn CAD, Teach CAD, for Modern Engineers."** — second line in
  `text-sw-red`. Subhead names the value props: automated workflows, timed assessments,
  industry-standard grading.
- Three feature cards, each with a 56px `bg-sw-red rounded-2xl` icon tile that scales to
  110% on card hover:
  - **Automated Grading** — "grade SOLIDWORKS files based on mass properties, geometry, and feature tree analysis."
  - **Timed Assessments** — "Prepare students for CSWA/CSWP exams with realistic timed environments and auto-submission."
  - **Class Management** — "manage hundreds of students, track progress, and share problem banks with other instructors."
- Dark CTA panel: `bg-gray-900 rounded-[2rem]` with two 256px blurred color orbs
  (`bg-sw-red/20 blur-[100px]` top-right, `bg-sw-cyan/20 blur-[100px]` bottom-left).
- Footer: logo, four dead links, "© 2026 SOLIDGRADE. All rights reserved."

### 5.2 Auth — `/auth`

**Two-step signup, one-step login.**

- **Role selection** (signup only, shown first): two large `rounded-[2.5rem]` cards with
  `border-4 border-transparent hover:border-sw-red` — "I am an Instructor" / "I am a Student".
  Escape hatch: "Already have an account? Sign in here."
- **Credential form**: Back link, a role badge chip when signing up (red for instructor,
  cyan for student), heading "Welcome back" / "Create account".
  - Fields: Full Name (signup only), Email (`name@institution.edu`), Password.
  - "Forgot?" link on login — **`href="#"`, not implemented**.
  - Submit button turns **cyan** when signing up as a student (`bg-sw-cyan`), red otherwise.
  - "OR CONTINUE WITH" divider → **Google sign-in** (`signInWithPopup`), rendering the
    Google `g` logo from `gstatic.com`.
- **Error handling**: raw Firebase error message rendered in the red banner.
  **[DERIVED]** Not humanized — e.g. `Firebase: Error (auth/wrong-password).` reaches the user.
- **Login timeout**: `Promise.race` against a 30s timer → "Login timed out. Please check
  your connection."
- On signup, writes a `users/{uid}` profile doc with `uid, email, displayName, role, createdAt`.
- Google sign-in creates the profile if absent, defaulting to `selectedRole ?? 'student'`.

### 5.3 Dashboard — `/dashboard`

Role-branched. Heading: "Welcome back, {firstName}!" / "Here's what's happening with your
CAD classes today."

**Four stat tiles**, all with a `bg-sw-red` icon tile:

| | Instructor | Student |
|---|---|---|
| 1 | Active Classes (live count) | My Classes (live count) |
| 2 | Assignments (count of recent, max 5) | Assignments (count of recent, max 5) |
| 3 | **Avg. Grade — hardcoded `'84%'`** | Completed (submitted + graded attempts) |
| 4 | **Pending Review — hardcoded `12`** | Avg. Grade (mean of `attempt.grade`, or `N/A`) |

> **[DERIVED] Two instructor stat tiles are placeholders.** "Avg. Grade" is the string
> `'84%'` and "Pending Review" is the number `12`, both literals in `Dashboard.tsx`. They
> are not computed. Milestone 2 must not treat these as existing capabilities — but it
> should note that the *intent* to show them exists.

**Recent Assignments** (max 5, sorted by `createdAt` desc) — card rows with a calendar icon
tile, title, and "Due {MMM d, h:mm a}". Instructors link to the detail page, students to
`/attempt`. "View All" → `/assignments`.

**Recent Grading Jobs** (instructor only, shown only when non-empty) — max 5 from
`grading_jobs` where `createdBy == profile.email`, ordered `createdAt` desc. Each row shows
the status icon/color from §3.5, the assignment name, status, and timestamp. Completed jobs
get a trailing `TrendingUp` button linking to the automated gradebook. "View Tools" →
`/grading-automation`.

**My Classes** sidebar — class cards with a stacked-avatar cluster (three static A/B/C
placeholders plus a "+N" bubble) and "N Students". "Manage" → `/classes`.

**Data**: all live `onSnapshot` listeners. Students query classes via a Firestore `or()` of
`studentIds array-contains uid` and `invitedStudentEmails array-contains email`, then
assignments via `classId in [...]` + `status == 'published'`.

### 5.4 Assignment list — `/assignments`

Role-branched.

**Instructor:**
- "Create Assignment" button.
- Tabs: **My Assignments** (`instructorId == uid`) / **Community Bank**
  (`visibility in ['public_instructors','public_general']`).
- Search box filtering by title (client-side, case-insensitive).
- Each row: red calendar icon tile, title, visibility icon+label, due date, problem count,
  and a `Timed` marker in cyan when applicable.
- Four row actions: **Results** (green, → automated gradebook), **Test** (cyan, → preview),
  **Edit** (neutral), **Grade** (red, → GradingPage).

**Student:**
- No create button, no tabs.
- Loads classes by `studentIds array-contains uid`, then assignments by `classId in [...]`
  + `status == 'published'`.
- Per row: if an attempt is `graded`, shows the grade in cyan; if `submitted`, a blue
  "Pending Grade" chip; button reads **"View"** if an attempt exists, else **"Start"**.

**Guards**: an auth-loading spinner, and a "Profile Not Found" state with a link back to
`/auth` if the Firestore profile is missing.

### 5.5 Assignment form — `/assignments/new`, `/assignments/:id/edit`

The most feature-dense instructor screen.

**Basics card**: Title, Description (textarea), Target Class (`<select>`, populated from
classes the user owns), Due Date (`datetime-local`).

**Manage Problems card**:
- **"Create New Problem"** button opens `ProblemModal` inline — a full problem-creation form
  in a modal, which on success adds the problem to the bank *and* auto-selects it.
- Live counters: "N Selected" (red chip) and "X / Y pts" — **green when the weights sum
  matches `totalPoints`, orange when it doesn't**.
- **Selected Problems** list: thumbnail (falls back to `drawingUrl`, then a `BookOpen`
  placeholder, with `onError` tracking for broken images), title, inline Copy / Edit links,
  a **Points** number input per problem, and a remove button. Rows are
  `border-2 border-sw-red bg-red-50/30`.
- **Problem bank** list: searchable, scrollable (`max-h-[400px]`), shows non-selected
  problems (own + public). Per row: Copy, Edit (owner only), and a `+` to select.
  Selecting auto-assigns the remaining unallocated points.
- **Copy** duplicates a problem as `"{title} (Copy)"` under your ownership, `visibility:
  'private'`. Confirmed with `window.confirm`, reported with `window.alert`.

**Settings card**:
- **Timed Assessment** toggle → reveals a Time Limit field, **minimum 10 minutes**,
  enforced on submit with an `alert()`.
- **Allow Solution Download** toggle — "Students can download solution files after grades
  are posted."
- **Total Assignment Points** (default 100). Submit is blocked with an `alert()` unless
  `|sum(weights) − totalPoints| < 0.01`; an inline orange warning shows the mismatch live.
- **Status**: Draft / Publish (two-button selector; Draft is `bg-gray-900`, Publish is `bg-sw-red`).
- **Visibility**: Private (`Lock`) / Instructors Only (`Shield`) / Public (`Globe`).

Writes `problemIds` *and* a denormalized `problems` array (full problem snapshots) onto the
assignment doc.

### 5.6 Assignment detail — `/assignments/:id`

Instructor-only in practice — students are redirected to `/attempt` on mount.

- **Grading job status banner** (when a job exists) — live-bound to the newest
  `grading_jobs` doc for this assignment; colors/copy per §3.5. Includes "View Gradebook"
  when results exist, and a **Retry** button on `error`/`timeout`.
- Header: title, status pill, visibility pill, due date, problem count.
- **Actions**: Test · **Auto Grade** · Grading · Edit · Delete (`window.confirm`).
- **Auto Grade** creates a `grading_jobs` document — this is the handoff to the desktop
  client. See §6.3 for the exact payload; it matters for Milestone 2.
- Description card (preserves newlines via `whitespace-pre-wrap`).
- Problems list — numbered rows with a per-problem download link to the SOLIDWORKS file.
- Submissions sidebar — one row per attempt with the student's name, status or grade, and a
  status icon; live count.

### 5.7 Grading page (manual) — `/assignments/:id/grading`

The instructor's hands-on grading surface.

- Header: "Grading: {title}", "Total Points: N".
- Counters: N Total / N Graded (green) / N Pending (orange).
- **Auto Grade** button (same job creation as §5.6), disabled while `pending`/`running`.
- **Gradebook** link, shown when the current job is `complete`.
- **Sync Grades** (cyan) — appears once automated results exist. Opens a confirmation modal
  ("This will overwrite current manual grades with automated grades for all students. You
  can still manually override them later.") then writes each matched student's
  `grade.total` onto their attempt as `grade` + `automatedGrade` and sets status `graded`.
- Per-student card: avatar, name, submit time, status chip, **inline-editable final grade**
  (pencil → number input → save/cancel), the automated grade shown underneath when it
  differs, and a **Grade Detail** button.
- **Grade Detail modal** — per problem:
  - Problem number, title, difficulty, "View Submission" link (or a "No Submission" chip).
  - **3D Comparison** — a Show/Hide Viewer toggle that mounts the embedded `STLViewer`
    (300px mobile / 500px desktop). When no automated geometry exists, an overlay reads
    "No 3D data found. / Run auto-grading to generate models."
  - **Feedback** textarea and a **Points / {weight}** number input.
  - **"Use Auto"** link to adopt the automated score (and its feedback) for that problem.
  - **Quick-set buttons: 0% / 50% / 100%** of the problem's weight.
  - Footer shows the running total against `totalPoints`; Save writes `problemGrades`,
    `problemFeedback`, summed `grade`, `status: 'graded'`, `gradedAt`, `gradedBy`.

**[DERIVED]** Student-record matching is heuristic and fragile — it tries
`username.startsWith(studentId)`, then `username === email`, then
`username === displayName`, plus filename containment. Worth knowing if the desktop client
generates those usernames.

### 5.8 Automated gradebook — `/assignments/:id/gradebook`

Reads `grading_results/{assignmentId}` live. **This is the screen that consumes the desktop
grader's output**, so it is the most important one for Milestone 2 parity.

- Header: "Automated Gradebook", "{assignment title} • N Submissions".
- **Publish Grades / Grades Published** toggle — flips `results.published`, which is what
  gates student visibility (both in the UI and in `firestore.rules`).
- **Export CSV** — client-side blob download, filename `Grades_{title}.csv`, columns:
  `Student, Email, Total Grade, Shape, Volume, Material, Sketches, Plagiarism, Needs Review`.
- **Four summary tiles**: Class Average (cyan-tinted), Needs Review (red-tinted),
  Plagiarism Flags (amber), Graded On (neutral).
- **Toolbar**: student search + filter segments **All / Review / Plagiarism**.
- **Results table** — columns: Student · Total · Shape · Volume · Material · Sketches ·
  Flags · Actions.
  - Total is color-coded by threshold (§3.4) and shows an "Overridden" caption when
    `grade.override !== null`.
  - Shape shows `round(shape_score × 100)%`; Volume/Material/Sketches show ✓/✗.
  - Sketches additionally lists the `underdefined_sketches` names in tiny red text, with the
    full list in a `title` tooltip.
  - Flags column renders the plagiarism / needs-review / clean icon tiles from §3.5.
  - Actions: **Eye** → opens the full-screen `STLViewer` comparison; **Pencil** → manual
    override via `window.prompt('Enter new score (0-100):')`, writing
    `grade.override`, `override_by: 'Instructor'`, `override_note: 'Manual override'`.
- Sorting state exists (`sortConfig`, default name/asc) but **no column headers are
  clickable** — sorting is not wired to the UI.
- Student names are resolved from `users` profiles when possible; otherwise parsed out of
  the grader's `username` string (`{uid}_{something}_{first.last}-…` → `"first, last"`).
- Empty state: "No Results Found / Automated grading has not been run or completed for this
  assignment."

### 5.9 Class gradebook (manual) — `/classes/:classId/gradebook`

- Header: "Gradebook: {class name}", "N Assignments • N Students".
- **Export CSV button exists but has no handler** — **[DERIVED]** it is a dead control.
- Toolbar: student search; live "Class Avg: N%".
- Matrix table: rows = students, columns = Student (sticky) · Avg · one column per
  assignment (with the assignment's `totalPoints` as a sub-caption). Missing grades show `--`.
- Empty state: "No students found matching your search."

### 5.10 Problem list — `/problems`

- Tabs: **All Problems** / **My Problems** / **Community Bank**.
- Search by title **or tag**.
- Card grid (`md:2 / lg:3`), each card: 16:9 thumbnail area (thumbnail → drawing → `BookOpen`
  placeholder, with broken-image tracking), a **Copy** button, a **difficulty badge**, and a
  visibility icon, all floating top-right over the image.
- Body: title, `#tag` chips, and — for problems you own — Edit / Delete icons plus a
  "Manage Problem" link.
- Delete is `window.confirm` → `deleteDoc`. Copy duplicates the problem as private under
  your ownership and switches to the "My Problems" tab.

### 5.11 Problem form — `/problems/new`, `/problems/:id/edit`

- Title, Description & Instructions.
- **Problem Assets** — four drag-and-drop upload zones plus a thumbnail zone:
  1. **SOLIDWORKS File** (`.sldprt`, `.sldasm`) — **required**; blocks submit with
     "SOLIDWORKS model file is required."
  2. **Drawing / Reference Image** (`image/*, .pdf`)
  3. **SOLIDWORKS Drawing** (`.slddrw`)
  4. **Additional Parts / Files** (multiple; listed with per-file remove)
  5. **Thumbnail Image** (optional) — "If empty, a preview will be generated from the drawing"
- **Automatic thumbnail generation**: if the drawing is a PDF and no thumbnail is set,
  `pdfjs-dist` renders page 1 to a canvas, exports JPEG at quality 0.8, and uploads it to
  `problems/{uid}/thumbs/{ts}_thumb.jpg`. If the drawing is an image, it is reused as the
  thumbnail directly.
- Sidebar: **Difficulty** (easy/medium/hard), **Visibility** (private / instructors only /
  public), **Tags** (type + Enter to add, click × to remove).
- Uploads go to Firebase Storage at `problems/{uid}/{timestamp}_{filename}`.

`components/ProblemModal.tsx` is a near-duplicate of this form rendered as a modal, used
from the Assignment form.

### 5.12 Problem detail — `/problems/:id`

- Header: title, difficulty badge, "Updated {date}".
- Owner actions: **Download All Files** (sequential fetch→blob→click with a 500ms gap
  between files to avoid browser download blocking), Edit Problem. Everyone: Download Model.
- Hero preview panel: thumbnail or drawing over `bg-gray-900` with a bottom gradient and a
  "Model Preview / SOLIDWORKS Part/Assembly File" caption; falls back to a large `Box` icon.
- Description, then **Reference Drawing** — inline `<img>`, or a "PDF Document" placeholder
  card with a "View PDF in New Tab" button when the URL looks like a PDF.
- **Instructor Assets** (owner only): a labeled download tile per asset — SOLIDWORKS Model
  (.SLDPRT/.SLDASM), SOLIDWORKS Drawing (.SLDDRW), Reference Drawing, Thumbnail, and each
  additional file.
- Tags section.
- Sidebar: Problem Info (visibility, difficulty, created date) and a placeholder panel —
  **"3D Viewer / Interactive 3D preview coming soon. Download the file to view in
  SOLIDWORKS."** (`STLViewer` exists but is not wired in here.)

### 5.13 Student assignment list — `/my-assignments`

**[DERIVED]** Fully built but not linked from navigation (see §4.4).

- Sections: **Upcoming & Active** and **Past Assignments** (split on due date; past section
  is rendered at `opacity-75`).
- Card per assignment: a `GraduationCap` tile colored by state (green when auto-graded,
  cyan when submitted, red otherwise), title, status chip, an **"Auto: N%"** cyan chip when
  published automated results exist, plus class name, due date, and time limit.
- Loads published `grading_results` for up to 30 assignments (Firestore `in` limit).

### 5.14 Student assignment / attempt — `/assignments/:id/attempt` (and `/test`)

The student-facing exam surface, and the instructor's preview of it.

- **Preview Mode banner** (instructors only): a solid `bg-sw-cyan` bar — "PREVIEW MODE / You
  are viewing this assignment as a student would see it." with a "Back to Manage" button.
- **Pre-start state**: a centered card — "Ready to start?" with copy that differs for timed
  vs untimed assignments, and a **Start Assignment** button. Starting writes
  `attempts/{uid}_{assignmentId}` with `status: 'started'` and `startTime`.
- **Timer** (timed assignments): a large pill showing `H:MM:SS`, cyan normally, switching to
  `bg-red-50 text-sw-red border-sw-red animate-pulse` **under 5 minutes**. Ticks once per
  second. **Auto-submits at zero.**
- **Per-problem cards** (border turns green once submitted): description, **Reference
  Drawing** inline with a "View Full Size Drawing" link, tag chips, **Additional Files**
  download chips, and a **Download Solution** panel shown only to instructors or when
  `allowStudentSolutionDownload` is on *and* the attempt is `graded`.
- **Upload**: one dashed dropzone label per problem — "Upload SOLIDWORKS File" / "Replace
  Submission". Uploads to
  `submissions/{assignmentId}/{uid}/{problemId}_{timestamp}_{filename}` and updates the
  attempt's `submissions` array (replacing any prior entry for that problem).
- **Submit**: a confirmation modal — "Ready to submit? / Once you submit, you won't be able
  to change your answers. Make sure you've uploaded all your SOLIDWORKS files."
- **Attempt Status sidebar**: status chip, started-at, submitted-at, and **Progress** as
  `submissions / problems`.
- **Final Grade card** (when graded): a solid cyan card with the grade at `text-5xl` and
  optional overall feedback.
- **Automated Grade card** (when `grading_results.published` and a record matches this
  student): the score plus a 2×2 breakdown of **Shape / Volume / Material / Sketches**
  points, a **"View 3D Comparison"** button, and an amber **Instructor Note** panel when the
  grade was overridden.
- Per-problem grade + feedback blocks appear under each submitted problem once graded.

### 5.15 Class management — `/classes`

- Class cards: red `GraduationCap` tile, name, 2-line-clamped description, member count,
  and (instructor) a **Gradebook** link and an **Invite** action. Managers get gear/trash
  icons; the whole card opens the manage modal.
- Students see either a **Join Class** button (accepting an invitation — adds their uid to
  `studentIds` and removes their email from `invitedStudentEmails`) or a green
  "Class Joined" chip.
- **Create Class modal**: Name (e.g. "MECH 101: Intro to CAD") + Description. Generates a
  6-character uppercase alphanumeric `inviteCode` (`Math.random().toString(36)`).
  **[DERIVED]** The invite code is generated and stored but **never displayed anywhere in
  the UI**, and nothing consumes it — invitations work by email, not by code.
- **Manage Class modal** (deep-linkable via `?manage=<id>`):
  - Edit name/description.
  - Member counts: "N Active Students" (cyan chip) / "N Invited" (gray chip).
  - **Co-Instructors** section (red `Shield`) and **Students** section (cyan `Users`), each
    listing active members (avatar + "(Active)") and invited emails (italic, dashed border,
    "(Invited)"), with a `UserMinus` remove button on every row.
  - On open, it self-heals: any invited email that now belongs to an active member is
    removed from the invited list.
- **Invite modal**: role selector (Student / Co-Instructor), a **Single ⇄ Bulk** mode
  switch, single email input or a bulk textarea (comma- **or** newline-separated, filtered
  to strings containing `@`, lowercased and trimmed), and a live "Currently Invited" list.

> **[DERIVED] Invitation emails are not actually sent from this screen.** `server.ts`
> implements `POST /api/send-invite` (Resend, subject *"Invitation to join {className} on
> SolidGrade"*), but **no client code calls it** — `ClassManagement` only writes emails into
> the Firestore array. The email path is built but unwired.

### 5.16 Grading Automation — `/grading-automation`

**Instructor-only** (hard `<Navigate to="/">` otherwise). **This page is about SolidGrade
Desktop itself** — it is the distribution and onboarding page for the very app being built.

Content, verbatim:

- **Installation Instructions**, four numbered steps:
  1. *Download the Installer* — "the latest version of the SolidGrade Automation Suite
     (Windows 10/11 required)."
  2. *Run the Setup* — "Extract the ZIP file and run `SolidGrade_Setup.exe`."
  3. *Configure SOLIDWORKS Path* — "Usually found in
     `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe`."
  4. *Link your Account* — "Use your instructor credentials to sign in within the app to
     sync assignments and student submissions."
- **System Requirements**: OS *Windows 10 / 11 (64-bit)* · Software *SOLIDWORKS 2021 or
  newer* · Hardware *8GB RAM (16GB Recommended)* · Network *Active Internet Connection*.
- **Latest Release** panel (dark `bg-gray-900` card): **v1.2.4**, "Released March 15, 2026",
  a **Download Now** button, and "SHA-256: 8f3c...a9b2".
- **Quick Links**: Troubleshooting Guide · API Documentation · Report an Issue.
- **Verified Secure** panel: "All downloads are scanned for malware and digitally signed."

> **[DERIVED] Every control on this page is inert.** The Download button, all three quick
> links, the version number, the release date, and the SHA-256 are hardcoded placeholders
> with no handlers. **Milestone 2 should read this page as a specification of what the
> desktop app is supposed to be**, not as a working distribution channel — and note that
> the desktop app it describes (a `SolidGrade_Setup.exe` installer that asks for the
> SOLIDWORKS path and signs in with instructor credentials to sync) differs from what
> Milestone 1 actually built (a PyInstaller folder-bundle with no login and no sync). That
> gap is a decision for the instructor, not something to resolve by assumption.

### 5.17 Settings — `/settings`

- Left rail (horizontal-scrolling on mobile): **Account Settings** (active) · Notifications ·
  Security & Privacy · Billing & Plans · LMS Integrations.
  **[DERIVED]** Only Account Settings is implemented; the other four are non-functional
  list items with no routing or panels behind them.
- Profile card: large `rounded-3xl` avatar with a camera button (**no handler**), and a form
  with **Full Name** (editable), **Email** (disabled), **Institution / University**
  (editable), **Account Role** (disabled). Save shows a green "Profile updated
  successfully!" banner for 3 seconds.
- **Danger Zone** card (red-tinted): "Once you delete your account, there is no going back.
  Please be certain." with a **Delete Account** button — **no handler**.

### 5.18 STL viewer — `components/STLViewer.tsx`

Used from the Automated Gradebook (modal), the Grade Detail modal (embedded), and the
student's automated-grade card (modal). Three.js-based.

- Loads two STLs by URL (`fetch` with `mode: 'cors'`), parsed with `STLLoader`.
  **The meshes are expected to arrive already PCA-normalized and aligned by the Python
  grading script** — the viewer only centers and uniformly scales them (the solution's
  max dimension defines the scale; the student mesh gets the same factor).
- **Solution mesh** green `0x4caf50`; **student mesh** blue `0x2196f3`; both
  `MeshPhongMaterial`, `DoubleSide`, `opacity 0.6`, `depthWrite: false`, solution
  `renderOrder 1`, student `renderOrder 2`.
- **Discrepancy mesh**: per-vertex coloring of the student mesh by approximate nearest-
  neighbour distance to the solution's vertices (sampled every 3rd vertex) —
  green `0x4caf50` ≤ 0.02, red `0xf44336` ≥ 0.08, green→yellow→red ramp between.
- Scene background `0xf8fafc`; grid helper `GridHelper(2, 20, 0xcbd5e1, 0xe2e8f0)`;
  ambient 0.7 + two directional lights (0.8 and 0.3); `PerspectiveCamera(45, …, 0.001, 100)`
  starting at `(3, 2, 3)`; `OrbitControls` with damping 0.05.
- Sidebar controls (256px, `md:w-64`):
  - **Visibility** toggles for Solution / Student / Discrepancies, each a colored pill with
    a dot and an eye icon.
  - **Blend slider** (0→1): a single range input cross-fading student↔solution opacity, with
    a live readout ("Student 60%" / "Both 100%" / "Solution 40%") and the caption
    "Center = both fully opaque". The track is
    `bg-gradient-to-r from-blue-300 via-gray-200 to-green-300`, `accent-red-500`.
  - **Discrepancy legend** (when enabled): Match / Small gap / Large gap.
  - **View presets**: Top · Front · Right · Iso.
  - **Controls hint**: "Drag: Rotate · Right drag: Pan · Scroll: Zoom".
- Floating **reset camera** button top-right of the canvas; **fullscreen** toggle in
  embedded mode.
- States: loading spinner over `bg-slate-50/90` ("Loading 3D Models…"), and an error state
  on `bg-red-50` ("Error Loading Models" + the message + a Close button).

### 5.19 Cross-cutting behavior

- **Error boundary** (`ErrorBoundary.tsx`) wraps the whole app: a centered white
  `rounded-3xl` card with a red `AlertTriangle` tile, "Something went wrong", the message,
  and a **Reload Application** button. Firestore errors are decoded from JSON into
  "Firestore Error: {error} during {operationType} on {path}".
- **Firestore error handling** (`firestoreUtils.ts`): every failure logs a structured
  payload (error, operation type, path, and full auth context including uid, email,
  emailVerified, isAnonymous, tenantId, and provider list) **and then rethrows**, which is
  what surfaces it to the error boundary.
- **Auth bootstrap** (`AuthContext.tsx`): an 8-second safety timeout forces `loading: false`
  if Firebase hangs, so the app can never spin forever.
- **Search box in the header is decorative** — **[DERIVED]** it has no state, no handler, and
  no results UI. Per-screen search boxes are the real ones.
- **Notification bell is decorative** — a red dot is always rendered; there is no
  notification system.

---

## 6. Data model

**[EXACT]** from `src/types.ts` and `firestore.rules`. Milestone 2 needs this because the
desktop app already reads and writes two of these collections.

### 6.1 Firestore collections

| Collection | Doc id | Written by | Read by |
|---|---|---|---|
| `users` | `{uid}` | self (on signup) | everyone authenticated |
| `classes` | auto | instructors; students may append themselves to `studentIds` | members + invitees |
| `problems` | auto | instructors | owner, or anyone if not `private` |
| `assignments` | auto | instructors | per visibility; students only when `status == 'published'` |
| `attempts` | **`{uid}_{assignmentId}`** | the student; instructors may update | the student + instructors |
| `grading_jobs` | auto | instructors (web) → **consumed by the desktop client** | instructors |
| `grading_results` | **`{assignmentId}`** | the grading client | instructors always; students only when `published == true` |

### 6.2 Core types

```ts
type UserRole = 'student' | 'instructor' | 'co-instructor' | 'admin';

interface UserProfile { uid; email; displayName; role: UserRole;
                        institution?; photoURL?; createdAt: string }

interface Problem { id; title; description; difficulty: 'easy'|'medium'|'hard';
                    tags: string[]; solidworksFileUrl; thumbnailUrl?; drawingUrl?;
                    slddrwUrl?; instructorId;
                    visibility: 'private'|'public_instructors'|'public_general';
                    additionalFiles?: { name; url }[]; createdAt; updatedAt }

interface Class { id; name; description; instructorId; coInstructorIds: string[];
                  studentIds: string[]; invitedStudentEmails?: string[];
                  invitedCoInstructorEmails?: string[]; inviteCode; createdAt }

interface Assignment { id; classId; title; description; problemIds: string[];
                       problems: Problem[];        // denormalized snapshot
                       dueDate; isTimed; timeLimitMinutes?; visibility; instructorId;
                       totalPoints; assignmentType: 'single'|'multi';
                       problemWeights: { [problemId]: number };
                       allowStudentSolutionDownload?; status: 'draft'|'published';
                       createdAt }

interface StudentAttempt { id; assignmentId; studentId;
                           status: 'started'|'submitted'|'graded';
                           startTime; submitTime?;
                           submissions: { problemId; fileUrl; submittedAt }[];
                           grade?; automatedGrade?;
                           problemGrades?: { [problemId]: number };
                           problemFeedback?: { [problemId]: string }; feedback? }
```

### 6.3 The grading handoff — the desktop app's contract

**[EXACT]** Both `AssignmentDetail` and `GradingPage` create this document when "Auto Grade"
is pressed. These are the literal values the web app writes today:

```ts
{
  assignmentId, assignmentName,
  assignmentType: 'single' | 'multi',
  status: 'pending',                       // → running → complete | error | timeout
  createdAt: Timestamp.now(),
  createdBy: <instructor email>,
  solutionStoragePath:    <first problem's solidworksFileUrl>  // AssignmentDetail
                          | `solutions/${id}/`,                // GradingPage
  submissionsStoragePath: `submissions/${id}/`,
  solutionsStoragePath:   `solutions/${id}/` (multi) | '',
  resultStoragePath:      `grading/${id}/`,
  rubric: { shape: 0.65, volume: 0.10, material: 0.10, sketches: 0.15 },
  volumeTolerance: 0.01,
  voxelResolution: 48,
  studentCount: <attempts.length>,
  completedAt: null, resultJsonUrl: null, resultCsvUrl: null,
  stlFolderUrl: null, error: null
}
```

> **[DERIVED] Two discrepancies Milestone 2 must not paper over.**
>
> 1. **`solutionStoragePath` differs between the two call sites.** `AssignmentDetail` sends
>    the first problem's `solidworksFileUrl`; `GradingPage` sends the literal string
>    `solutions/${id}/` (with the comment `// Placeholder, adjust as needed`). A desktop
>    client consuming these jobs will receive two different shapes for the same field
>    depending on which button the instructor pressed.
> 2. **`voxelResolution: 48` here vs `VOXEL_RES=64` in the desktop app.**
>    `MILESTONE_1_REPORT.md` records this session's grading runs at 64. The web app
>    requests 48. Whichever is authoritative, they currently disagree — this needs an
>    explicit decision, not a silent default.
>
> `grading_agent.py` in this repo already targets the same `grading_jobs` /
> `grading_results` collection names, so the plumbing exists. Only the field-level
> agreement is in doubt.

### 6.4 The result shape the gradebook expects

**[EXACT]** — `grading_results/{assignmentId}` is read as `{ results: GradingResults }` in
`AutomatedGradebook`, and as a bare `GradingResults` in `StudentAssignment`.
**[DERIVED]** `GradingPage` defensively handles both (`data.results?.students ||
data.students`), so both shapes exist in the wild.

```ts
interface GradingResults {
  assignmentId; assignmentName; gradedAt; published: boolean;
  solution:   { volume_mm3; material; stl_path };
  rubric:     { shape; volume; material; sketches };
  thresholds: { volume_tolerance; shape_threshold; voxel_resolution };
  students:   StudentGradeRecord[];
}

interface StudentGradeRecord {
  username; filename; sw_author; last_saved_date;
  grade:    { total; shape_points; volume_points; material_points; sketch_points;
              override; override_note; override_by };
  checks:   { shape_score; volume_ok; material_ok; sketches_ok;
              underdefined_sketches: string[]; volume_mm3; material; mass_kg };
  geometry: { student_stl_path; solution_stl_path;
              alignment_transform: number[]; best_flip: number[] };
  flags:    { plagiarism; plagiarism_with; needs_review };
  error;
}
```

**[EXACT]** The `geometry.student_stl_path` / `solution_stl_path` values are fetched
directly by `STLViewer` with `fetch(url, { mode: 'cors' })`, so they must be
publicly-readable URLs (or Firebase download URLs), not storage object paths.
`GradingPage` additionally handles `https://storage.googleapis.com/...` URLs by converting
them to download URLs via `getDownloadURL(ref(storage, path))`.

**[DERIVED]** Note also that `StudentGradeRecord` has no `feedback` field in the type, yet
`GradingPage` reads `record.feedback` when adopting automated feedback. Either the type is
incomplete or that code path is dead.

---

## 7. Notes for SolidGrade Desktop, Milestone 2

**[DERIVED]** throughout this section. Recorded here rather than acted on, per this
session's scope.

### 7.1 What transfers cleanly

- **The whole token system.** Two brand colors, Tailwind's default gray/status palettes, the
  system font stack, a 4px spacing base, and the radius/shadow scales in §2. All of it maps
  to plain CSS custom properties with no build step. The desktop app serves HTML to a
  browser, so this is a direct port, not an approximation.
- **The component recipes in §3** — `.card`, `.btn-primary`, `.btn-secondary`,
  `.input-field`, the table pattern, the modal shells, the empty-state card, the ring
  spinner, and the status-badge mapping. Resolved CSS is given for the four that matter most.
- **The status vocabulary in §3.5.** The desktop app already produces grading job states and
  per-file check results; the colors, icons, and copy for each are specified there and
  should match the web app exactly so an instructor sees one consistent language.
- **The loading and error copy** in §3.8 / §5.19, which is already well-suited to a desktop
  startup sequence.

### 7.2 What needs a deliberate decision, not a default

1. **The `btn-primary` hover hue** (§2.3) — off-brand today.
2. **`.btn-secondary`'s missing border width** (§3.1) — call sites clearly intend outlines.
3. **`voxelResolution` 48 vs 64** (§6.3) — the two apps disagree.
4. **`solutionStoragePath`'s two shapes** (§6.3).
5. **The `animate-in` animations that never run** (§2.9) — implement or omit, but knowingly.
6. **Dark mode's red `<h1>`** (§2.11) — striking and deliberate-looking; keep or drop, but ask.
7. **Whether the desktop app matches the Grading Automation page's description of itself**
   (§5.16) — installer, SOLIDWORKS path prompt, and account login/sync vs. what Milestone 1
   actually shipped.

### 7.3 What the desktop app should improve rather than replicate

- **`window.prompt()` for grade overrides** (§5.8) and `window.confirm()`/`window.alert()`
  for destructive actions (§5.10, §5.5). A desktop app should use real dialogs styled per §3.6.
- **The accessibility gaps in §3.11** — especially the total absence of focus indicators,
  which matters more in a keyboard-heavy desktop grading workflow than on a marketing site.
- **Incomplete dark mode** (§2.11) — implement it uniformly the first time.
- **Raw Firebase error strings shown to users** (§5.2).
- **Placeholder dashboard stats** (§5.3) — either compute them or leave them out; don't ship
  literals.

### 7.4 Where the two apps touch

Recorded, not changed:

- `grading_agent.py` in this repo already uses the collection names `grading_jobs` and
  `grading_results` (`JOBS_COLLECTION` / `RESULTS_COLLECTION`) and writes
  `status: "running"` and `resultJsonUrl` — the same fields §6.3/§6.4 describe. The
  integration surface exists; §6.3's two discrepancies are the open items.
- `app.py`'s current Flask endpoints (`/healthz`, `/api/self_test`, `/api/status`,
  `/api/launch_sw`, `/api/pick_folder`, `/api/pick_file`, `/api/run_grading`,
  `/api/run_status`, `/api/shutdown`) are the surface a styled UI would drive. Nothing in
  this document requires changing them.
- The desktop app uses **native `tkinter` file/folder pickers**, not browser file inputs
  (SPEC §13: student files are referenced, never copied). §3.3's dropzone should therefore
  become a *path picker* wearing the same visual clothes, not a literal drop target.

---

## 8. Quick-reference: the tokens, as CSS

**[DERIVED]** — a consolidated starting point assembled from §2. Values are exact per their
individual labels; the *organization* into this block is this document's own.

```css
:root {
  /* Brand */
  --sg-red: #E31E24;
  --sg-cyan: #00AEEF;

  /* Neutrals */
  --sg-gray-50: #f9fafb;   --sg-gray-100: #f3f4f6;  --sg-gray-200: #e5e7eb;
  --sg-gray-300: #d1d5dc;  --sg-gray-400: #99a1af;  --sg-gray-500: #6a7282;
  --sg-gray-600: #4a5565;  --sg-gray-700: #364153;  --sg-gray-800: #1e2939;
  --sg-gray-900: #101828;  --sg-gray-950: #030712;

  /* Status */
  --sg-green-50: #f0fdf4;  --sg-green-500: #00c950; --sg-green-600: #00a63e;
  --sg-amber-50: #fffbeb;  --sg-amber-500: #fe9a00; --sg-amber-600: #e17100;
  --sg-orange-50: #fff7ed; --sg-orange-500: #ff6900;
  --sg-blue-50: #eff6ff;   --sg-blue-600: #155dfc;
  --sg-red-50: #fef2f2;    --sg-red-600: #e7000b;

  /* Semantic — light */
  --sg-bg: var(--sg-gray-50);
  --sg-surface: #ffffff;
  --sg-surface-sunken: var(--sg-gray-50);
  --sg-border: var(--sg-gray-100);
  --sg-text: var(--sg-gray-900);
  --sg-text-muted: var(--sg-gray-500);
  --sg-text-faint: var(--sg-gray-400);

  /* Type */
  --sg-font: ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji",
             "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji";
  --sg-font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
                  "Liberation Mono", "Courier New", monospace;
  --sg-weight-bold: 700;
  --sg-weight-black: 900;
  --sg-tracking-widest: 0.1em;
  --sg-tracking-tighter: -0.05em;

  /* Space (4px base) */
  --sg-space-1: 0.25rem; --sg-space-2: 0.5rem;  --sg-space-3: 0.75rem;
  --sg-space-4: 1rem;    --sg-space-6: 1.5rem;  --sg-space-8: 2rem;

  /* Radii */
  --sg-radius-lg: 0.5rem;   /*  8px */
  --sg-radius-xl: 0.75rem;  /* 12px — buttons, inputs, nav */
  --sg-radius-2xl: 1rem;    /* 16px */
  --sg-radius-3xl: 1.5rem;  /* 24px — cards, modals */

  /* Shadows */
  --sg-shadow-sm: 0 1px 3px 0 rgb(0 0 0 / .1), 0 1px 2px -1px rgb(0 0 0 / .1);
  --sg-shadow-lg: 0 10px 15px -3px rgb(0 0 0 / .1), 0 4px 6px -4px rgb(0 0 0 / .1);
  --sg-shadow-xl: 0 20px 25px -5px rgb(0 0 0 / .1), 0 8px 10px -6px rgb(0 0 0 / .1);
  --sg-shadow-2xl: 0 25px 50px -12px rgb(0 0 0 / .25);
  --sg-glow-red:  0 10px 15px -3px rgb(227 30 36 / .2), 0 4px 6px -4px rgb(227 30 36 / .2);
  --sg-glow-cyan: 0 10px 15px -3px rgb(0 174 239 / .2), 0 4px 6px -4px rgb(0 174 239 / .2);

  /* Motion */
  --sg-ease: cubic-bezier(0.4, 0, 0.2, 1);
  --sg-duration: 150ms;
  --sg-duration-theme: 300ms;

  /* Layout */
  --sg-sidebar-w: 18rem;    /* 288px */
  --sg-header-h: 5rem;      /* 80px desktop, 64px mobile */
  --sg-content-max: 80rem;  /* 1280px */
}

.dark {
  --sg-bg: var(--sg-gray-950);
  --sg-surface: var(--sg-gray-900);
  --sg-surface-sunken: var(--sg-gray-800);
  --sg-border: var(--sg-gray-800);
  --sg-text: #ffffff;
  --sg-text-muted: var(--sg-gray-400);
  --sg-text-faint: var(--sg-gray-500);
}
```

---

## 9. What this reference cannot tell you

Stated plainly so a future session doesn't mistake absence for completeness.

- **No live instance was visited.** Everything here comes from source. That makes the values
  exact, but it means a handful of things were reasoned about rather than observed:
  - How the layout actually behaves at specific viewport widths.
  - Whether any screen has a rendering bug that only appears with real data.
  - What real Firestore data looks like — actual `username` formats from the desktop grader,
    real class sizes, real STL URLs.
  - Which of the "dead control" findings (§4.4, §5.9, §5.15, §5.16, §5.17) the instructor
    considers unfinished versus intentionally out of scope.
- **No screenshots exist in this document.** If Milestone 2 wants visual confirmation before
  building, either the instructor should share the deployed URL (then click through every
  screen and state, including empty and error states, as originally intended) or the app can
  be run locally — `npm install && npm run dev`, Vite on port 3000, with Firebase config
  already committed at `firebase-applet-config.json`.
- **The repo is at commit `99a68a5` (2026-04-02).** If the instructor has deployed changes
  since, re-check §2 and §5 before building against them.
