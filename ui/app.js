/* ==========================================================================
   SolidGrade Desktop — UI logic
   --------------------------------------------------------------------------
   Drives the existing Flask endpoints (/healthz, /api/self_test, /api/status,
   /api/launch_sw, /api/pick_folder, /api/pick_file, /api/run_grading,
   /api/run_status, /api/shutdown) plus three additive ones this UI needs
   (/api/validate_paths, /api/override, /api/export_csv). No existing endpoint
   changed shape.

   THE REHYDRATION FIX (MILESTONE_1_REPORT.md post-milestone item 3).
   The Milestone 1 page kept the two picked paths in bare JS variables and
   only ever called /api/run_status from inside the poll loop that
   runGrading() started. Refreshing therefore showed "(none selected)" and
   "(no results yet)" while the server was still holding a live run — the
   server never lost anything, the page did. Diagnosed live: a server
   instance from 2026-08-29 was still up, healthy, and holding a complete
   26-student result. Fixed in boot() below: paths persist to localStorage
   and are re-validated server-side, and /api/run_status is read on every
   page load, so a refresh restores the picked paths, an in-flight run's
   progress, and a finished run's full results.
   ========================================================================== */

'use strict';

/* ==========================================================================
   0. Small helpers
   ========================================================================== */

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const icon = (name, size = 16, stroke = 2) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round"
        aria-hidden="true"><use href="#i-${name}"/></svg>`;

async function api(path, opts) {
  const r = await fetch(path, opts);
  let body = null;
  try { body = await r.json(); } catch (_) { /* non-JSON error page */ }
  if (!r.ok) {
    const msg = (body && body.error) || `${r.status} ${r.statusText}`;
    const err = new Error(msg);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return body;
}

const post = (path, data) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(data || {}),
});

function fmtDuration(sec) {
  if (sec == null || !isFinite(sec)) return '—';
  const s = Math.max(0, Math.round(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
               : `${m}:${String(r).padStart(2, '0')}`;
}

/* A number that may legitimately be absent. Never coerce null to 0 — SPEC
   §15.1: a null check result means "not evaluated", not "scored zero". */
function fmtNum(v, digits = 1) {
  return (v == null || typeof v !== 'number' || !isFinite(v)) ? '—' : v.toFixed(digits);
}

function basename(p) {
  if (!p) return '';
  const parts = String(p).split(/[\\/]/);
  return parts[parts.length - 1] || parts[parts.length - 2] || p;
}

function toast(message) {
  const region = $('toast-region');
  const t = el('div', 'toast', message);
  region.appendChild(t);
  setTimeout(() => t.remove(), 4200);
}

/* ==========================================================================
   1. Client state
   ========================================================================== */

const LS = {
  theme: 'sg.theme',
  solution: 'sg.solutionPath',
  folder: 'sg.folderPath',
  name: 'sg.assignmentName',
  voxel: 'sg.voxelResolution',
  view: 'sg.view',
};

function lsGet(k, fallback = null) {
  try { const v = localStorage.getItem(k); return v === null ? fallback : v; }
  catch (_) { return fallback; }
}
function lsSet(k, v) {
  try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); }
  catch (_) { /* private mode / storage disabled — degrade to session-only */ }
}

const state = {
  status: null,          // last /api/status payload
  run: null,             // last /api/run_status payload
  solutionPath: null,
  folderPath: null,
  pathsValid: { solution: null, folder: null },  // null = unchecked
  fileSeries: [],        // per-file seconds, for the §11.5 trend
  statusTimer: null,
  runTimer: null,
  launching: false,
  picking: false,
  view: 'home',
  results: { filter: 'all', query: '', sortKey: 'total', sortDir: 'asc' },
};

/* ==========================================================================
   2. Theme — §2.11
   --------------------------------------------------------------------------
   Reproduces ThemeContext.tsx exactly: reads localStorage 'theme', accepts
   only 'dark'/'light', and if unset defaults BY TIME OF DAY (dark when the
   local hour is >= 18 or < 6). It deliberately does not consult
   prefers-color-scheme, because the web app does not.
   ========================================================================== */

function resolveInitialTheme() {
  const stored = lsGet(LS.theme);
  if (stored === 'dark' || stored === 'light') return stored;
  const h = new Date().getHours();
  return (h >= 18 || h < 6) ? 'dark' : 'light';
}

function applyTheme(theme) {
  const dark = theme === 'dark';
  document.documentElement.classList.toggle('dark', dark);
  document.body.classList.toggle('dark', dark);
  document.documentElement.setAttribute('data-theme', theme);
  document.body.setAttribute('data-theme', theme);
  document.documentElement.style.colorScheme = theme;
  lsSet(LS.theme, theme);

  const btn = $('btn-theme');
  btn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  btn.querySelector('use').setAttribute('href', dark ? '#i-sun' : '#i-moon');
}

/* ==========================================================================
   3. Modal — §3.6 with the §7.3 accessibility fixes
   --------------------------------------------------------------------------
   role="dialog" + aria-modal, focus trapping, Escape to close, and focus
   restored to the invoking element. The web app has none of these, and uses
   window.prompt() for the grade override; this replaces it.
   ========================================================================== */

const modal = {
  lastFocus: null,
  onClose: null,

  open({ title, description, body, actions, wide, onClose }) {
    this.lastFocus = document.activeElement;
    this.onClose = onClose || null;

    $('modal-title').textContent = title;
    const desc = $('modal-desc');
    desc.textContent = description || '';
    desc.classList.toggle('hidden', !description);

    const bodyEl = $('modal-body');
    bodyEl.innerHTML = '';
    if (body) bodyEl.appendChild(body);

    const foot = $('modal-foot');
    foot.innerHTML = '';
    (actions || []).forEach((a) => {
      const b = el('button', a.className || 'btn-secondary', a.label);
      b.type = 'button';
      b.addEventListener('click', () => a.onClick && a.onClick());
      foot.appendChild(b);
    });

    $('modal-panel').classList.toggle('modal__panel--wide', !!wide);
    $('modal-root').hidden = false;

    /* Land on the first real field if the dialog has one — a keyboard user
       opening "Override" should be able to type the score immediately,
       not tab past the close button first. */
    const field = $('modal-body').querySelector('input, textarea, select');
    (field || this._focusables()[0] || $('modal-close')).focus();
    if (field && field.select) field.select();
  },

  close() {
    if ($('modal-root').hidden) return;
    $('modal-root').hidden = true;
    const cb = this.onClose;
    this.onClose = null;
    if (this.lastFocus && this.lastFocus.focus) this.lastFocus.focus();
    if (cb) cb();
  },

  isOpen() { return !$('modal-root').hidden; },

  _focusables() {
    return Array.from($('modal-panel').querySelectorAll(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
    )).filter((n) => n.offsetParent !== null);
  },

  trap(e) {
    if (!this.isOpen() || e.key !== 'Tab') return;
    const f = this._focusables();
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  },
};

/* A real confirm dialog, replacing window.confirm() (§7.3). */
function confirmDialog({ title, description, confirmLabel, danger }) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => { if (!settled) { settled = true; resolve(v); } };
    modal.open({
      title,
      description,
      actions: [
        { label: 'Cancel', className: 'btn-secondary', onClick: () => { done(false); modal.close(); } },
        { label: confirmLabel || 'Confirm',
          className: danger ? 'btn-primary' : 'btn-primary',
          onClick: () => { done(true); modal.close(); } },
      ],
      onClose: () => done(false),
    });
  });
}

/* ==========================================================================
   4. Navigation
   ========================================================================== */

function setView(view) {
  state.view = view;
  lsSet(LS.view, view);

  document.querySelectorAll('.page').forEach((p) => {
    p.classList.toggle('hidden', p.dataset.view !== view);
  });
  document.querySelectorAll('#nav .nav-item').forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle('is-active', active);
    b.setAttribute('aria-current', active ? 'page' : 'false');
  });

  closeDrawer();
  if (view === 'results') renderResults();
  if (view === 'system') renderSystem();
  if (view === 'home') renderHome();
}

function openDrawer() {
  $('sidebar').classList.add('is-open');
  $('scrim').hidden = false;
  $('scrim').classList.remove('hidden');
  $('btn-menu').setAttribute('aria-expanded', 'true');
}
function closeDrawer() {
  $('sidebar').classList.remove('is-open');
  $('scrim').hidden = true;
  $('scrim').classList.add('hidden');
  $('btn-menu').setAttribute('aria-expanded', 'false');
}

/* ==========================================================================
   5. System status — SPEC §3
   ========================================================================== */

function setRowIcon(rowId, tone, iconName) {
  const node = $(rowId);
  node.className = `status-row__icon ${tone}`;
  node.querySelector('use').setAttribute('href', `#i-${iconName}`);
}

function renderStatus(s) {
  state.status = s;

  const running = !!(s.solidworks && s.solidworks.running);
  const installed = !!(s.solidworks && s.solidworks.installed);
  const selfTestPassed = !!(s.runtime && s.runtime.self_test_passed);
  const busy = state.run && state.run.status === 'running';

  /* --- The header pill --- */
  const pill = $('ready-pill');
  const text = $('ready-pill-text');
  if (busy) {
    pill.dataset.state = 'busy';
    text.textContent = 'Grading in progress';
  } else if (s.ready) {
    pill.dataset.state = 'ready';
    text.textContent = 'System Ready';
  } else {
    pill.dataset.state = 'blocked';
    text.textContent = !running ? 'SOLIDWORKS not running'
                     : !selfTestPassed ? 'Self-test failed'
                     : 'Not ready';
  }

  /* --- Row 1: runtime (§3.1) --- */
  if (selfTestPassed) {
    setRowIcon('row-runtime-icon', 'is-ok', 'check-circle');
    $('row-runtime-detail').textContent =
      s.runtime.self_test_detail || 'Bundled runtime present; self-test passed.';
  } else if (!running) {
    /* Not a runtime verdict — the self-test needs live SOLIDWORKS and
       deliberately will not launch it (SPEC §3: checking status must never
       launch SolidWorks as a side effect). Show that honestly rather than
       reporting a runtime failure that has not been established. */
    setRowIcon('row-runtime-icon', 'is-idle', 'clock');
    $('row-runtime-detail').textContent =
      'Not yet verified — the self-test needs a live SOLIDWORKS instance and will not launch one for you.';
  } else {
    setRowIcon('row-runtime-icon', 'is-bad', 'x-circle');
    $('row-runtime-detail').textContent =
      (s.runtime.self_test_error || 'Self-test failed.') +
      (s.runtime.self_test_detail ? ' ' + s.runtime.self_test_detail : '');
  }

  /* --- Row 2: SOLIDWORKS (§3.2) --- */
  const swDetail = $('row-sw-detail');
  const launchBtn = $('btn-launch-sw');
  if (running) {
    setRowIcon('row-sw-icon', 'is-ok', 'check-circle');
    swDetail.textContent = 'Running and responding to COM.';
    launchBtn.classList.add('hidden');
    state.launching = false;
  } else if (installed) {
    setRowIcon('row-sw-icon', 'is-bad', 'x-circle');
    swDetail.textContent = state.launching
      ? 'Launching… this can take up to 90 seconds on this machine.'
      : 'Installed, but not running.';
    launchBtn.classList.remove('hidden');
    launchBtn.disabled = state.launching;
    launchBtn.innerHTML = state.launching
      ? '<span class="spinner spinner--sm"></span> Launching…'
      : 'Launch SOLIDWORKS';
  } else {
    setRowIcon('row-sw-icon', 'is-bad', 'x-circle');
    swDetail.textContent = s.solidworks.installed_error
      ? `Not detected — ${s.solidworks.installed_error}`
      : 'Not detected on this machine.';
    launchBtn.classList.add('hidden');
  }

  /* --- Row 3: edition (§3.2 / §3.3) --- */
  const ed = $('row-edition-detail');
  if (running) {
    const label = s.solidworks.application_type_label || 'Unknown edition';
    const rev = s.solidworks.revision_number;
    const year = s.solidworks.release_year;
    ed.textContent = `${label}${rev ? ` · build ${rev}` : ''}${year ? ` · ${year}` : ''}`;
    /* §3.3: frame the caveat around edition, not year, and do not hard-block. */
    if (s.solidworks.application_type === 2 || s.solidworks.application_type === 1) {
      setRowIcon('row-edition-icon', 'is-warn', 'alert-circle');
      ed.textContent += ' — this edition reports ApplicationType ' +
        s.solidworks.application_type + '; the DISPID sketch probe is used rather than the ' +
        'named API. Validated on this machine during Milestone 1.';
    } else {
      setRowIcon('row-edition-icon', 'is-ok', 'check-circle');
    }
  } else {
    setRowIcon('row-edition-icon', 'is-idle', 'cpu');
    ed.textContent = 'Unknown until SOLIDWORKS is running.';
  }

  updateRunGate();
  if (state.view === 'system') renderSystem();
}

async function refreshStatus() {
  try {
    renderStatus(await api('/api/status'));
  } catch (e) {
    const pill = $('ready-pill');
    pill.dataset.state = 'blocked';
    $('ready-pill-text').textContent = 'Status unavailable';
  }
}

async function launchSolidWorks() {
  state.launching = true;
  if (state.status) renderStatus(state.status);
  try {
    await post('/api/launch_sw');
  } catch (e) {
    toast(`Launch failed: ${e.message}`);
    state.launching = false;
  }
  /* §3.2: auto-poll until COM responds, flip green with no further user
     action. Poll faster than the idle cadence while we're waiting. */
  const started = Date.now();
  const iv = setInterval(async () => {
    await refreshStatus();
    const running = state.status && state.status.solidworks && state.status.solidworks.running;
    if (running || Date.now() - started > 180000) {
      clearInterval(iv);
      state.launching = false;
      if (state.status) renderStatus(state.status);
      if (!running) toast('SOLIDWORKS did not come up within 3 minutes.');
    }
  }, 3000);
}

/* ==========================================================================
   6. Path pickers — §3.3 dropzone visuals, native dialog behaviour
   ========================================================================== */

function renderPicker(kind) {
  const isSolution = kind === 'solution';
  const path = isSolution ? state.solutionPath : state.folderPath;
  const valid = isSolution ? state.pathsValid.solution : state.pathsValid.folder;

  const wrap = $(isSolution ? 'picker-solution' : 'picker-folder');
  const title = $(isSolution ? 'solution-title' : 'folder-title');
  const hint = $(isSolution ? 'solution-hint' : 'folder-hint');
  const pathEl = $(isSolution ? 'solution-path' : 'folder-path');
  const clear = $(isSolution ? 'clear-solution' : 'clear-folder');
  const btn = $(isSolution ? 'pick-solution' : 'pick-folder');

  wrap.classList.remove('is-chosen', 'is-stale');
  clear.classList.toggle('hidden', !path);

  if (!path) {
    title.textContent = isSolution ? 'Choose solution .SLDPRT' : 'Choose submissions folder';
    hint.textContent = isSolution ? 'Opens a SOLIDWORKS file browser' : 'Prompted fresh every run';
    hint.classList.remove('hidden');
    pathEl.classList.add('hidden');
    btn.setAttribute('aria-label', isSolution
      ? 'Choose solution part. Nothing selected.'
      : 'Choose submissions folder. Nothing selected.');
    return;
  }

  pathEl.textContent = path;
  pathEl.classList.remove('hidden');

  if (valid === false) {
    /* A restored path that no longer exists. Say so instead of showing it
       green and letting the instructor discover it at Run. */
    wrap.classList.add('is-stale');
    title.textContent = basename(path);
    hint.textContent = isSolution ? 'This file no longer exists — choose again.'
                                  : 'This folder no longer exists — choose again.';
    hint.classList.remove('hidden');
    btn.setAttribute('aria-label', `${basename(path)} — missing. Choose again.`);
  } else if (!isSolution && valid && valid.part_count === 0) {
    /* The folder exists but holds nothing to grade. Showing this green
       would let the instructor start a run that grades zero students. */
    wrap.classList.add('is-stale');
    title.textContent = basename(path);
    hint.textContent = 'No .SLDPRT files in this folder — choose another.';
    hint.classList.remove('hidden');
    btn.setAttribute('aria-label', `${basename(path)} — contains no SOLIDWORKS parts. Choose another folder.`);
  } else {
    wrap.classList.add('is-chosen');
    title.textContent = basename(path);
    if (!isSolution && valid && valid.part_count != null) {
      hint.textContent = valid.part_count === 1
        ? '1 SOLIDWORKS part found' : `${valid.part_count} SOLIDWORKS parts found`;
      hint.classList.remove('hidden');
    } else {
      hint.classList.add('hidden');
    }
    btn.setAttribute('aria-label', `${basename(path)} selected. Choose a different ${isSolution ? 'file' : 'folder'}.`);
  }
}

async function pick(kind) {
  if (state.picking) return;
  state.picking = true;
  const btn = $(kind === 'solution' ? 'pick-solution' : 'pick-folder');
  btn.disabled = true;
  try {
    const endpoint = kind === 'solution' ? '/api/pick_file' : '/api/pick_folder';
    const d = await post(endpoint);
    if (d && d.path) {
      if (kind === 'solution') { state.solutionPath = d.path; lsSet(LS.solution, d.path); }
      else                     { state.folderPath = d.path;  lsSet(LS.folder, d.path); }
      await validatePaths();
    }
  } catch (e) {
    toast(`Could not open the file browser: ${e.message}`);
  } finally {
    state.picking = false;
    btn.disabled = false;
    renderPicker(kind);
    updateRunGate();
  }
}

function clearPath(kind) {
  if (kind === 'solution') { state.solutionPath = null; state.pathsValid.solution = null; lsSet(LS.solution, null); }
  else                     { state.folderPath = null;  state.pathsValid.folder = null;  lsSet(LS.folder, null); }
  renderPicker(kind);
  updateRunGate();
}

async function validatePaths() {
  if (!state.solutionPath && !state.folderPath) return;
  try {
    const d = await post('/api/validate_paths', {
      solution_path: state.solutionPath,
      students_folder: state.folderPath,
    });
    state.pathsValid.solution = d.solution;
    state.pathsValid.folder = d.students_folder;
  } catch (_) {
    state.pathsValid.solution = null;
    state.pathsValid.folder = null;
  }
  renderPicker('solution');
  renderPicker('folder');
}

/* ==========================================================================
   7. Run gate — §10 step 5
   ========================================================================== */

function readVoxel() {
  const raw = parseInt($('voxel-res').value, 10);
  const errEl = $('voxel-error');
  if (!isFinite(raw)) { errEl.textContent = 'Enter a number.'; errEl.classList.remove('hidden'); return null; }
  if (raw < 64) {
    /* SPEC §7.4 / D3: hard floor of 64. Below it the form score is not
       valid (§7.5), so this is refused rather than silently accepted. */
    errEl.textContent = 'Below the hard floor of 64 (SPEC §7.4) — the form score would not be valid.';
    errEl.classList.remove('hidden');
    return null;
  }
  errEl.classList.add('hidden');
  return raw;
}

function updateRunGate() {
  const s = state.status;
  const running = state.run && state.run.status === 'running';
  const gate = $('run-gate');
  const btn = $('btn-run');
  const reason = $('run-blocked-reason');
  const voxel = readVoxel();

  const solutionOk = !!state.solutionPath && state.pathsValid.solution !== false;
  const folderInfo = state.pathsValid.folder;
  /* An existing folder with no .SLDPRT files is not a usable selection —
     starting a run on it grades nobody. */
  const folderEmpty = !!(folderInfo && folderInfo.part_count === 0);
  const folderOk = !!state.folderPath && folderInfo !== false && !folderEmpty;

  $('files-step-state').textContent =
    (solutionOk && folderOk) ? 'Ready' : (state.solutionPath || state.folderPath) ? 'Incomplete' : 'Not started';
  $('files-step-state').className =
    'chip ' + ((solutionOk && folderOk) ? 'chip-green' : (state.solutionPath || state.folderPath) ? 'chip-amber' : 'chip-gray');

  gate.innerHTML = '';
  let blocked = null;

  if (running) {
    blocked = 'A grading run is already in progress.';
    $('run-step-state').textContent = 'Running';
    $('run-step-state').className = 'chip chip-blue';
  } else if (!s) {
    blocked = 'Checking system status…';
    $('run-step-state').textContent = 'Waiting';
    $('run-step-state').className = 'chip chip-gray';
  } else if (!s.solidworks.running) {
    /* §10 step 5: block with an inline Launch button and recheck, so the
       user never backs out of the wizard. */
    blocked = 'SOLIDWORKS is not running.';
    const banner = el('div', 'banner banner--warning');
    banner.innerHTML = `${icon('alert-circle', 18)}<div class="grow"><div>SOLIDWORKS is not running.</div>
      <div class="tiny" style="font-weight:400;margin-top:.25rem">Grading needs a live instance. Launch it here — you do not need to leave this screen.</div></div>`;
    if (s.solidworks.installed) {
      const b = el('button', 'btn-primary btn-sm', state.launching ? 'Launching…' : 'Launch SOLIDWORKS');
      b.type = 'button';
      b.disabled = state.launching;
      b.addEventListener('click', launchSolidWorks);
      banner.appendChild(b);
    }
    gate.appendChild(banner);
    $('run-step-state').textContent = 'Blocked';
    $('run-step-state').className = 'chip chip-red';
  } else if (!s.runtime.self_test_passed) {
    blocked = 'The startup self-test has not passed.';
    const banner = el('div', 'banner banner--error');
    banner.innerHTML = `${icon('alert-circle', 18)}<div class="grow"><div>Self-test has not passed.</div>
      <div class="tiny" style="font-weight:400;margin-top:.25rem">${
        (s.runtime.self_test_error || '')} ${(s.runtime.self_test_detail || '')}</div></div>`;
    gate.appendChild(banner);
    $('run-step-state').textContent = 'Blocked';
    $('run-step-state').className = 'chip chip-red';
  } else if (!solutionOk || !folderOk) {
    blocked = folderEmpty && solutionOk
        ? 'The submissions folder holds no .SLDPRT files.'
      : !solutionOk && !folderOk ? 'Choose a solution part and a submissions folder.'
      : !solutionOk ? 'Choose a solution part.' : 'Choose a submissions folder.';
    $('run-step-state').textContent = 'Waiting';
    $('run-step-state').className = 'chip chip-gray';
  } else if (voxel == null) {
    blocked = 'Fix the voxel resolution.';
    $('run-step-state').textContent = 'Waiting';
    $('run-step-state').className = 'chip chip-gray';
  } else {
    const banner = el('div', 'banner banner--success');
    const n = state.pathsValid.folder && state.pathsValid.folder.part_count;
    banner.innerHTML = `${icon('check-circle', 18)}<div>Ready to grade${
      n ? ` — ${n} part${n === 1 ? '' : 's'} in the submissions folder` : ''}. Files are opened read-only and never modified.</div>`;
    gate.appendChild(banner);
    $('run-step-state').textContent = 'Ready';
    $('run-step-state').className = 'chip chip-green';
  }

  btn.disabled = !!blocked;
  reason.textContent = blocked || '';
}

/* ==========================================================================
   8. Running — §10 step 6
   ========================================================================== */

async function startRun() {
  const voxel = readVoxel();
  if (voxel == null) { updateRunGate(); return; }
  const name = ($('assignment-name').value || 'SolidGrade_Run').trim();

  $('btn-run').disabled = true;
  try {
    await post('/api/run_grading', {
      students_folder: state.folderPath,
      solution_path: state.solutionPath,
      assignment_name: name,
      voxel_resolution: voxel,
    });
    state.fileSeries = [];
    $('progress-card').classList.remove('hidden');
    startRunPolling();
  } catch (e) {
    const banner = el('div', 'banner banner--error');
    banner.innerHTML = `${icon('alert-circle', 18)}<div>${e.message}</div>`;
    $('run-banner-slot').innerHTML = '';
    $('run-banner-slot').appendChild(banner);
    updateRunGate();
  }
}

function renderProgress(r) {
  const card = $('progress-card');
  if (r.status === 'idle') { card.classList.add('hidden'); return; }
  card.classList.remove('hidden');

  const total = r.total || 0;
  const current = r.current || 0;
  const pct = total > 0 ? Math.min(100, (current / total) * 100) : 0;

  $('progress-count').textContent = total ? `${current} of ${total}` : 'Starting…';
  $('progress-elapsed').textContent = `${fmtDuration(r.elapsed_s)} elapsed`;
  $('progress-fill').style.width = `${pct}%`;
  $('progress-file').textContent = r.filename || '—';

  const badge = $('progress-badge');
  const badgeText = $('progress-badge-text');
  const fill = $('progress-fill');
  fill.classList.remove('progress-fill--done', 'progress-fill--error');

  /* §3.5 [EXACT] status → style and banner copy. */
  if (r.status === 'running') {
    badge.className = 'badge badge-blue'; badgeText.textContent = 'Grading in progress';
    /* Remaining-time estimate from the observed mean, not a fixed constant —
       per-file time on this machine is measured to vary 33–97s (R-7). */
    if (state.fileSeries.length && total > current) {
      const mean = state.fileSeries.reduce((a, b) => a + b, 0) / state.fileSeries.length;
      $('progress-count').textContent =
        `${current} of ${total} · about ${fmtDuration(mean * (total - current))} remaining`;
    }
  } else if (r.status === 'complete') {
    badge.className = 'badge badge-green'; badgeText.textContent = 'Grading complete';
    fill.classList.add('progress-fill--done');
    fill.style.width = '100%';
  } else if (r.status === 'error') {
    badge.className = 'badge badge-red'; badgeText.textContent = 'Grading error';
    fill.classList.add('progress-fill--error');
  }

  /* §11.5 per-file duration trend */
  const trend = $('progress-trend');
  const caption = $('progress-trend-caption');
  if (!state.fileSeries.length) {
    trend.innerHTML = '';
    caption.textContent = r.status === 'running' ? 'Waiting for the first file…' : 'No per-file timings recorded.';
  } else {
    const max = Math.max(...state.fileSeries);
    trend.innerHTML = '';
    state.fileSeries.slice(-60).forEach((sec) => {
      const bar = el('div', 'trend__bar');
      bar.style.height = `${Math.max(6, (sec / max) * 100)}%`;
      bar.title = `${sec.toFixed(1)}s`;
      trend.appendChild(bar);
    });
    const mean = state.fileSeries.reduce((a, b) => a + b, 0) / state.fileSeries.length;
    const last = state.fileSeries[state.fileSeries.length - 1];
    caption.textContent =
      `Last ${last.toFixed(1)}s · mean ${mean.toFixed(1)}s · slowest ${max.toFixed(1)}s`;
    trend.setAttribute('aria-label',
      `Per-file grading duration: last ${last.toFixed(1)} seconds, mean ${mean.toFixed(1)} seconds, slowest ${max.toFixed(1)} seconds.`);
  }
}

function ingestRun(r) {
  const prev = state.run;
  state.run = r;

  /* Accumulate the per-file series as new files complete. */
  if (r.file_seconds != null && (!prev || prev.current !== r.current)) {
    if (typeof r.file_seconds === 'number' && isFinite(r.file_seconds)) {
      state.fileSeries.push(r.file_seconds);
    }
  }

  renderProgress(r);
  updateRunGate();
  if (state.status) renderStatus(state.status);

  const reviewCount = r.result && r.result.students
    ? r.result.students.filter((s) => s.flags && s.flags.needs_review).length : 0;
  const badge = $('nav-review-count');
  badge.textContent = reviewCount;
  badge.classList.toggle('hidden', !reviewCount);
  if (reviewCount) badge.setAttribute('aria-hidden', 'false');

  if (state.view === 'results') renderResults();
  if (state.view === 'home') renderHome();
}

function startRunPolling() {
  if (state.runTimer) clearInterval(state.runTimer);
  state.runTimer = setInterval(async () => {
    try {
      const r = await api('/api/run_status');
      ingestRun(r);
      if (r.status !== 'running') {
        clearInterval(state.runTimer);
        state.runTimer = null;
        if (r.status === 'complete') {
          toast('Grading complete.');
          setView('results');
        } else if (r.status === 'error') {
          toast('Grading failed — see the Run screen.');
        }
      }
    } catch (_) { /* transient; keep polling */ }
  }, 1000);
}

/* ==========================================================================
   9. Home — SPEC §5.1
   ========================================================================== */

function renderHome() {
  const body = $('home-recent-body');
  const openBtn = $('home-open-results');
  const r = state.run;

  if (!r || !r.result) {
    openBtn.classList.add('hidden');
    body.innerHTML = '';
    const empty = el('div', 'empty empty--compact');
    empty.innerHTML = `${icon('inbox', 32)}<h3>No grading runs yet</h3>
      <p>Run your first assignment to see results here.</p>`;
    body.appendChild(empty);
    return;
  }

  openBtn.classList.remove('hidden');
  const students = r.result.students || [];
  const review = students.filter((s) => s.flags && s.flags.needs_review).length;
  const plag = students.filter((s) => s.flags && s.flags.plagiarism).length;
  const errors = students.filter((s) => s.error).length;
  const totals = students.map(effectiveTotal).filter((v) => v != null);
  const avg = totals.length ? totals.reduce((a, b) => a + b, 0) / totals.length : null;

  body.innerHTML = '';
  const head = el('div', 'stack-2');
  head.appendChild(el('div', 'black', r.result.assignmentName || '(unnamed run)'));
  head.appendChild(el('div', 'small muted',
    `Graded ${r.result.gradedAt || 'recently'} · voxel resolution ${
      (r.result.thresholds && r.result.thresholds.voxel_resolution) ?? '—'}`));
  body.appendChild(head);

  const stats = el('div', 'grid-stats');
  stats.style.marginTop = '1.5rem';
  const stat = (value, label, mod) => {
    const d = el('div', mod ? `stat ${mod}` : 'stat');
    d.appendChild(el('div', 'stat__value', value));
    d.appendChild(el('div', 'stat__label', label));
    return d;
  };
  stats.appendChild(stat(String(students.length), 'Students graded'));
  /* §5.1: "The review count belongs on the card. It is the number the
     instructor actually acts on." */
  stats.appendChild(stat(String(review), 'Need review', 'stat--review'));
  stats.appendChild(stat(String(plag), 'Plagiarism prompts', 'stat--plag'));
  stats.appendChild(stat(avg == null ? '—' : avg.toFixed(1), 'Average score'));
  if (errors) stats.appendChild(stat(String(errors), 'Errored', 'stat--review'));
  body.appendChild(stats);
}

/* ==========================================================================
   10. Results — SPEC §12
   ========================================================================== */

/* §12.4: computed and override are an explicit pair; the computed value is
   never mutated, so the original is always retrievable. */
function effectiveTotal(s) {
  if (!s || !s.grade) return null;
  if (s.grade.override != null) return s.grade.override;
  return typeof s.grade.total === 'number' ? s.grade.total : null;
}
const isOverridden = (s) => !!(s && s.grade && s.grade.override != null);

/* §12.3 three states. A check is pass, fail, or NOT EVALUATED. `null` is
   the third state and must never be rendered as 0 or as a fail — SPEC
   §15.1 and the `_voxel_iou` "return None, not zero" rule. */
function checkCell(status) {
  if (status === 'pass') return { cls: 'check--pass', glyph: '✓', label: 'Pass' };
  if (status === 'fail') return { cls: 'check--fail', glyph: '✗', label: 'Fail' };
  return { cls: 'check--none', glyph: '—', label: 'Not evaluated' };
}

function renderCheck(td, status) {
  const c = checkCell(status);
  const span = el('span', `check ${c.cls}`);
  span.appendChild(el('span', 'check__glyph', c.glyph));
  /* Never colour-only (§3.11): the glyph and a text label both carry it. */
  span.appendChild(el('span', 'sr-only', c.label));
  td.appendChild(span);
  return span;
}

function studentRows() {
  const r = state.run;
  if (!r || !r.result || !r.result.students) return [];
  let rows = r.result.students.slice();

  const q = state.results.query.trim().toLowerCase();
  if (q) {
    rows = rows.filter((s) =>
      String(s.username || '').toLowerCase().includes(q) ||
      String(s.filename || '').toLowerCase().includes(q));
  }

  const f = state.results.filter;
  if (f === 'review') rows = rows.filter((s) => s.flags && s.flags.needs_review);
  else if (f === 'plag') rows = rows.filter((s) => s.flags && s.flags.plagiarism);
  else if (f === 'clean') rows = rows.filter((s) =>
    s.flags && !s.flags.needs_review && !s.flags.plagiarism && !s.error);

  const key = state.results.sortKey, dir = state.results.sortDir === 'desc' ? -1 : 1;
  rows.sort((a, b) => {
    let va, vb;
    if (key === 'name') { va = String(a.username || ''); vb = String(b.username || ''); return va.localeCompare(vb) * dir; }
    if (key === 'shape') { va = a.checks && a.checks.shape_score; vb = b.checks && b.checks.shape_score; }
    else { va = effectiveTotal(a); vb = effectiveTotal(b); }
    /* Not-evaluated sorts last in both directions — it is not a low score. */
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return (va - vb) * dir;
  });
  return rows;
}

function renderResults() {
  const host = $('results-body');
  const r = state.run;

  /* Re-rendering the whole table blows away the search caret. Capture it
     first and restore it at the end, so typing in the filter box works. */
  const active = document.activeElement;
  const keepSearch = !!(active && active.type === 'search' && host.contains(active));
  const caret = keepSearch ? active.selectionStart : null;

  host.innerHTML = '';
  const restoreFocus = () => {
    if (!keepSearch) return;
    const next = host.querySelector('input[type="search"]');
    if (next) { next.focus(); if (caret != null) next.setSelectionRange(caret, caret); }
  };

  if (r && r.status === 'running') {
    $('results-sub').textContent = 'A run is in progress.';
    $('btn-export-csv').disabled = true;
    const card = el('div', 'card');
    const row = el('div', 'row');
    row.appendChild(el('div', 'spinner spinner--md'));
    row.appendChild(el('p', 'bold muted',
      `Grading in progress… (${r.current || 0} of ${r.total || 0} students)`));
    card.appendChild(row);
    host.appendChild(card);
    return;
  }

  if (r && r.status === 'error') {
    $('results-sub').textContent = 'The last run failed.';
    $('btn-export-csv').disabled = true;
    const banner = el('div', 'banner banner--error');
    banner.innerHTML = `${icon('alert-circle', 18)}<div class="grow"><div>Grading error</div>
      <div class="tiny mono" style="font-weight:400;margin-top:.25rem"></div></div>`;
    banner.querySelector('.mono').textContent = r.error || 'Unknown error.';
    host.appendChild(banner);
    return;
  }

  if (!r || !r.result) {
    $('results-sub').textContent = 'No run loaded.';
    $('btn-export-csv').disabled = true;
    const empty = el('div', 'empty');
    empty.innerHTML = `${icon('trending', 48)}<h3>No results found</h3>
      <p>Run a grading job to see results here.</p>`;
    host.appendChild(empty);
    return;
  }

  const res = r.result;
  const all = res.students || [];
  const rows = studentRows();
  $('btn-export-csv').disabled = false;
  $('results-sub').textContent =
    `${res.assignmentName || 'Run'} · ${all.length} student${all.length === 1 ? '' : 's'} · graded ${res.gradedAt || '—'}`;

  /* --- Summary stats --- */
  const review = all.filter((s) => s.flags && s.flags.needs_review).length;
  const plag = all.filter((s) => s.flags && s.flags.plagiarism).length;
  const clean = all.filter((s) => s.flags && !s.flags.needs_review && !s.flags.plagiarism && !s.error).length;
  const totals = all.map(effectiveTotal).filter((v) => v != null);
  const avg = totals.length ? totals.reduce((a, b) => a + b, 0) / totals.length : null;

  const statCard = el('div', 'card');
  const stats = el('div', 'grid-stats');
  const stat = (v, l, mod) => {
    const d = el('div', mod ? `stat ${mod}` : 'stat');
    d.appendChild(el('div', 'stat__value', v));
    d.appendChild(el('div', 'stat__label', l));
    return d;
  };
  stats.appendChild(stat(String(all.length), 'Students'));
  stats.appendChild(stat(String(clean), 'Clean', 'stat--clean'));
  stats.appendChild(stat(String(review), 'Need review', 'stat--review'));
  stats.appendChild(stat(String(plag), 'Plagiarism', 'stat--plag'));
  stats.appendChild(stat(avg == null ? '—' : avg.toFixed(1), 'Average'));
  statCard.appendChild(stats);

  const meta = el('p', 'tiny faint');
  meta.style.marginTop = '1.5rem';
  meta.textContent =
    `Solution ${basename(res.solution && res.solution.file)} · ` +
    `volume ${fmtNum(res.solution && res.solution.volume_mm3, 1)} mm³ · ` +
    `material ${(res.solution && res.solution.material) || '—'} · ` +
    `voxel resolution ${(res.thresholds && res.thresholds.voxel_resolution) ?? '—'} · ` +
    `volume tolerance ±${((res.thresholds && res.thresholds.volume_tolerance) ?? 0) * 100}% · ` +
    `shape threshold ${(res.thresholds && res.thresholds.shape_threshold) ?? '—'}`;
  statCard.appendChild(meta);
  host.appendChild(statCard);

  /* --- Table --- */
  const card = el('div', 'card card--flush');
  card.style.marginTop = '1.5rem';

  const toolbar = el('div', 'table-toolbar');
  const search = el('div', 'input-wrap');
  search.style.maxWidth = '20rem';
  search.style.flex = '1';
  search.innerHTML = icon('search', 18);
  const input = el('input', 'input-field');
  input.type = 'search';
  input.placeholder = 'Search students or files…';
  input.value = state.results.query;
  input.setAttribute('aria-label', 'Search students or files');
  input.addEventListener('input', () => { state.results.query = input.value; renderResults(); });
  search.appendChild(input);
  toolbar.appendChild(search);

  const filters = el('div', 'segmented segmented--filters');
  filters.setAttribute('role', 'group');
  filters.setAttribute('aria-label', 'Filter results');
  [['all', 'All', all.length], ['review', 'Need review', review],
   ['plag', 'Plagiarism', plag], ['clean', 'Clean', clean]].forEach(([k, label, n]) => {
    const b = el('button', 'segmented__btn', `${label} (${n})`);
    b.type = 'button';
    b.dataset.tone = k;
    b.setAttribute('aria-pressed', String(state.results.filter === k));
    b.addEventListener('click', () => { state.results.filter = k; renderResults(); });
    filters.appendChild(b);
  });
  toolbar.appendChild(filters);
  card.appendChild(toolbar);

  const scroll = el('div', 'table-scroll');
  const table = el('table', 'grid');
  table.appendChild(el('caption', 'sr-only',
    `Grading results for ${res.assignmentName || 'this run'}: ${rows.length} of ${all.length} students shown.`));

  const thead = el('thead');
  const htr = el('tr');
  const sortableTh = (key, label, sticky) => {
    const th = el('th', sticky ? 'col-sticky' : null);
    th.scope = 'col';
    const b = el('button', 'th-sort');
    b.type = 'button';
    b.innerHTML = `<span>${label}</span><span class="th-sort__caret">${icon('chevron-down', 12)}</span>`;
    const isSorted = state.results.sortKey === key;
    b.setAttribute('aria-sort', isSorted ? (state.results.sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
    th.setAttribute('aria-sort', isSorted ? (state.results.sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
    b.addEventListener('click', () => {
      if (state.results.sortKey === key) {
        state.results.sortDir = state.results.sortDir === 'asc' ? 'desc' : 'asc';
      } else { state.results.sortKey = key; state.results.sortDir = 'asc'; }
      renderResults();
    });
    th.appendChild(b);
    return th;
  };
  const plainTh = (label, hint) => {
    const th = el('th');
    th.scope = 'col';
    th.textContent = label;
    if (hint) th.title = hint;
    return th;
  };

  htr.appendChild(sortableTh('name', 'Student', true));
  htr.appendChild(plainTh('Form', 'PCA-normalized voxel IoU'));
  htr.appendChild(sortableTh('shape', 'IoU'));
  htr.appendChild(plainTh('Volume'));
  htr.appendChild(plainTh('Material'));
  htr.appendChild(plainTh('Sketches'));
  htr.appendChild(plainTh('Flags'));
  htr.appendChild(sortableTh('total', 'Total'));
  htr.appendChild(plainTh('Override'));
  thead.appendChild(htr);
  table.appendChild(thead);

  const tbody = el('tbody');
  rows.forEach((s) => {
    const tr = el('tr');
    if (isOverridden(s)) tr.classList.add('is-overridden');

    const nameTd = el('td', 'col-sticky');
    nameTd.appendChild(el('div', 'cell-name', s.username || s.uid || '(unknown)'));
    nameTd.appendChild(el('div', 'cell-file', s.filename || ''));
    tr.appendChild(nameTd);

    const c = s.checks || {};

    /* Form verdict, then the raw IoU behind it, then the other three checks. */
    const formTd = el('td');
    renderCheck(formTd, c.shape_status);
    tr.appendChild(formTd);

    const iouTd = el('td', 'cell-num');
    if (c.shape_score == null) { iouTd.textContent = '—'; iouTd.classList.add('faint'); }
    else iouTd.textContent = c.shape_score.toFixed(3);
    tr.appendChild(iouTd);

    [c.volume_status, c.material_status, c.sketches_status].forEach((status) => {
      const td = el('td');
      renderCheck(td, status);
      tr.appendChild(td);
    });

    /* Flags — §3.5 [EXACT] result-flag tiles */
    const flagTd = el('td');
    const flagRow = el('div', 'row row--tight');
    const f = s.flags || {};
    if (s.error) {
      const t = el('span', 'flag-tile flag-tile--review');
      t.innerHTML = icon('alert-circle', 14);
      t.title = s.error;
      t.setAttribute('aria-label', `Error: ${s.error}`);
      flagRow.appendChild(t);
    }
    if (f.plagiarism) {
      const t = el('span', 'flag-tile flag-tile--plag');
      t.innerHTML = icon('shield-alert', 14);
      const withWhom = f.plagiarism_with ? ` with ${f.plagiarism_with}` : '';
      t.title = `Plagiarism prompt${withWhom}`;
      t.setAttribute('aria-label', `Plagiarism prompt${withWhom}`);
      flagRow.appendChild(t);
    }
    if (f.needs_review) {
      const t = el('span', 'flag-tile flag-tile--review');
      t.innerHTML = icon('alert-circle', 14);
      t.title = 'Needs review';
      t.setAttribute('aria-label', 'Needs review');
      flagRow.appendChild(t);
    }
    if (!s.error && !f.plagiarism && !f.needs_review) {
      const t = el('span', 'flag-tile flag-tile--clean');
      t.innerHTML = icon('shield-check', 14);
      t.title = 'Clean — passed every enabled check';
      t.setAttribute('aria-label', 'Clean, passed every enabled check');
      flagRow.appendChild(t);
    }
    flagTd.appendChild(flagRow);
    tr.appendChild(flagTd);

    /* Total, with the §12.4 override marker */
    const totalTd = el('td', 'cell-total');
    const eff = effectiveTotal(s);
    totalTd.appendChild(document.createTextNode(fmtNum(eff, 1)));
    if (isOverridden(s)) {
      const mark = el('span', 'override-mark');
      mark.innerHTML = icon('pencil', 12);
      mark.title = `Overridden from ${fmtNum(s.grade.total, 1)}${
        s.grade.override_note ? ` — ${s.grade.override_note}` : ''}`;
      mark.setAttribute('aria-label', mark.title);
      totalTd.appendChild(mark);
    }
    tr.appendChild(totalTd);

    /* Override action — a real dialog, not window.prompt() (§7.3) */
    const actTd = el('td');
    const actRow = el('div', 'row row--tight');
    const editBtn = el('button', 'btn-tint btn-tint--cyan');
    editBtn.type = 'button';
    editBtn.innerHTML = `${icon('pencil', 12)} Override`;
    editBtn.setAttribute('aria-label', `Override the grade for ${s.username || 'this student'}`);
    editBtn.addEventListener('click', () => openOverrideDialog(s));
    actRow.appendChild(editBtn);
    if (isOverridden(s)) {
      const rev = el('button', 'btn-tint btn-tint--neutral');
      rev.type = 'button';
      rev.innerHTML = `${icon('revert', 12)} Revert`;
      rev.setAttribute('aria-label', `Revert ${s.username || 'this student'} to the auto-generated grade`);
      rev.addEventListener('click', () => submitOverride(s, null, null));
      actRow.appendChild(rev);
    }
    actTd.appendChild(actRow);
    tr.appendChild(actTd);

    tbody.appendChild(tr);
  });

  if (!rows.length) {
    const tr = el('tr');
    const td = el('td');
    td.colSpan = 9;
    td.style.padding = '3rem 1.5rem';
    td.style.textAlign = 'center';
    td.className = 'faint';
    td.textContent = 'No students match this filter.';
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  scroll.appendChild(table);
  card.appendChild(scroll);
  host.appendChild(card);
  restoreFocus();
}

function openOverrideDialog(s) {
  const body = el('div', 'stack');

  const summary = el('div', 'banner banner--info');
  summary.innerHTML = `${icon('alert-circle', 18)}<div class="grow small" style="font-weight:400">
    Auto-generated total is <strong>${fmtNum(s.grade && s.grade.total, 1)}</strong>. The computed value is
    kept, never replaced — the override is stored alongside it and can be reverted at any time.</div>`;
  body.appendChild(summary);

  const scoreWrap = el('div');
  const scoreLabel = el('label', 'micro-label', 'Override total');
  scoreLabel.htmlFor = 'ovr-score';
  const scoreInput = el('input', 'input-field input-md');
  scoreInput.id = 'ovr-score';
  scoreInput.type = 'number';
  scoreInput.min = '0'; scoreInput.max = '100'; scoreInput.step = '0.1';
  scoreInput.value = s.grade && s.grade.override != null ? s.grade.override : '';
  scoreInput.placeholder = fmtNum(s.grade && s.grade.total, 1);
  scoreWrap.appendChild(scoreLabel);
  scoreWrap.appendChild(scoreInput);
  const scoreErr = el('p', 'field-error hidden');
  scoreWrap.appendChild(scoreErr);
  body.appendChild(scoreWrap);

  const noteWrap = el('div');
  const noteLabel = el('label', 'micro-label', 'Reason (recorded with the override)');
  noteLabel.htmlFor = 'ovr-note';
  const noteInput = el('textarea', 'input-field input-md');
  noteInput.id = 'ovr-note';
  noteInput.rows = 3;
  noteInput.value = (s.grade && s.grade.override_note) || '';
  noteWrap.appendChild(noteLabel);
  noteWrap.appendChild(noteInput);
  body.appendChild(noteWrap);

  modal.open({
    title: `Override — ${s.username || 'student'}`,
    description: s.filename || '',
    body,
    actions: [
      { label: 'Cancel', className: 'btn-secondary', onClick: () => modal.close() },
      { label: 'Save override', className: 'btn-primary', onClick: () => {
          const raw = scoreInput.value.trim();
          if (raw === '') { scoreErr.textContent = 'Enter a score, or Cancel.'; scoreErr.classList.remove('hidden'); scoreInput.focus(); return; }
          const v = Number(raw);
          if (!isFinite(v) || v < 0 || v > 100) {
            scoreErr.textContent = 'Enter a number between 0 and 100.';
            scoreErr.classList.remove('hidden'); scoreInput.focus(); return;
          }
          modal.close();
          submitOverride(s, v, noteInput.value.trim() || null);
        } },
    ],
  });
}

async function submitOverride(s, value, note) {
  try {
    const d = await post('/api/override', {
      username: s.username || s.uid,
      filename: s.filename,
      override: value,
      override_note: note,
    });
    if (d && d.student && state.run && state.run.result) {
      const list = state.run.result.students;
      const i = list.findIndex((x) => (x.username || x.uid) === (s.username || s.uid));
      if (i >= 0) list[i] = d.student;
    }
    renderResults();
    renderHome();
    toast(value == null ? 'Reverted to the auto-generated grade.' : 'Override saved.');
  } catch (e) {
    toast(`Could not save the override: ${e.message}`);
  }
}

async function exportCsv() {
  const btn = $('btn-export-csv');
  btn.disabled = true;
  try {
    const d = await post('/api/export_csv');
    modal.open({
      title: 'CSV exported',
      description: 'The full table, including overrides and their markers.',
      body: (() => {
        const b = el('div');
        const p = el('p', 'mono small');
        p.style.wordBreak = 'break-all';
        p.textContent = d.path;
        b.appendChild(p);
        return b;
      })(),
      actions: [{ label: 'Done', className: 'btn-primary', onClick: () => modal.close() }],
    });
  } catch (e) {
    toast(`Export failed: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
}

/* ==========================================================================
   11. System view
   ========================================================================== */

function renderSystem() {
  const host = $('system-body');
  const s = state.status;
  host.innerHTML = '';
  if (!s) {
    const card = el('div', 'card');
    const row = el('div', 'row');
    row.appendChild(el('div', 'spinner spinner--md'));
    row.appendChild(el('p', 'bold muted', 'Checking system status…'));
    card.appendChild(row);
    host.appendChild(card);
    return;
  }

  const rows = [
    ['Overall', s.ready ? 'Ready' : 'Not ready', s.ready],
    ['Self-test passed', s.runtime.self_test_passed ? 'Yes' : 'No', s.runtime.self_test_passed],
    ['Self-test detail', s.runtime.self_test_detail || s.runtime.self_test_error || '—', null],
    ['SOLIDWORKS installed', s.solidworks.installed ? 'Yes' : 'No', s.solidworks.installed],
    ['SOLIDWORKS running', s.solidworks.running ? 'Yes' : 'No', s.solidworks.running],
    ['Edition', s.solidworks.application_type_label || '—', null],
    ['ApplicationType', s.solidworks.application_type == null ? '—' : String(s.solidworks.application_type), null],
    ['Build (RevisionNumber)', s.solidworks.revision_number || '—', null],
    ['Release year', s.solidworks.release_year || '—', null],
  ];

  const card = el('div', 'card');
  card.appendChild(el('h2', 'card__title', 'Status detail'));
  const table = el('table', 'grid');
  table.style.marginTop = '1rem';
  const tb = el('tbody');
  rows.forEach(([k, v, ok]) => {
    const tr = el('tr');
    const th = el('th');
    th.scope = 'row';
    th.textContent = k;
    th.style.textTransform = 'none';
    th.style.letterSpacing = 'normal';
    th.style.fontSize = '.8125rem';
    th.style.position = 'static';
    tr.appendChild(th);
    const td = el('td');
    td.style.whiteSpace = 'normal';
    if (ok === true) { const c = el('span', 'check check--pass'); c.appendChild(el('span', 'check__glyph', '✓')); c.appendChild(el('span', null, ` ${v}`)); td.appendChild(c); }
    else if (ok === false) { const c = el('span', 'check check--fail'); c.appendChild(el('span', 'check__glyph', '✗')); c.appendChild(el('span', null, ` ${v}`)); td.appendChild(c); }
    else td.textContent = v;
    tr.appendChild(td);
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  card.appendChild(table);
  host.appendChild(card);

  const about = el('div', 'card');
  about.style.marginTop = '1.5rem';
  about.appendChild(el('h2', 'card__title', 'Shut down'));
  about.appendChild(el('p', 'muted small',
    'Releases SOLIDWORKS document handles, stops the popup dismisser, restores any modified STL export preferences, and exits.'));
  const btn = el('button', 'btn-primary btn-md');
  btn.type = 'button';
  btn.style.marginTop = '1.5rem';
  btn.innerHTML = `${icon('power', 18)} Shut Down`;
  btn.addEventListener('click', requestShutdown);
  about.appendChild(btn);
  host.appendChild(about);
}

/* ==========================================================================
   12. Shutdown — SPEC §1.2
   ========================================================================== */

async function requestShutdown() {
  const running = state.run && state.run.status === 'running';
  const ok = await confirmDialog({
    title: 'Shut down SolidGrade?',
    description: running
      ? 'A grading run is in progress. Shutting down now will abandon it — the students graded so far are already written to disk, but the rest will not be graded.'
      : 'This releases SOLIDWORKS document handles, stops the popup dismisser, restores STL export preferences, and exits.',
    confirmLabel: 'Shut down',
    danger: true,
  });
  if (!ok) return;

  try {
    const d = await post('/api/shutdown');
    if (state.statusTimer) clearInterval(state.statusTimer);
    if (state.runTimer) clearInterval(state.runTimer);
    document.body.innerHTML =
      `<div style="display:flex;align-items:center;justify-content:center;height:100vh;
                   font-family:var(--sg-font);text-align:center;padding:2rem">
         <div>
           <div style="font-weight:900;font-size:1.25rem">${d.status}</div>
         </div>
       </div>`;
  } catch (e) {
    toast(`Shutdown failed: ${e.message}`);
  }
}

/* ==========================================================================
   13. Boot
   ========================================================================== */

function wireEvents() {
  $('btn-theme').addEventListener('click', () => {
    applyTheme(document.documentElement.classList.contains('dark') ? 'light' : 'dark');
  });

  $('btn-menu').addEventListener('click', () => {
    $('sidebar').classList.contains('is-open') ? closeDrawer() : openDrawer();
  });
  $('scrim').addEventListener('click', closeDrawer);

  document.querySelectorAll('#nav .nav-item').forEach((b) => {
    b.addEventListener('click', () => setView(b.dataset.view));
  });
  document.querySelectorAll('[data-goto]').forEach((b) => {
    b.addEventListener('click', () => setView(b.dataset.goto));
  });
  $('home-open-results').addEventListener('click', () => setView('results'));

  $('ready-pill').addEventListener('click', () => {
    const panel = $('status-panel');
    const open = panel.classList.toggle('hidden');
    $('ready-pill').setAttribute('aria-expanded', String(!open));
  });

  $('btn-launch-sw').addEventListener('click', launchSolidWorks);
  $('pick-solution').addEventListener('click', () => pick('solution'));
  $('pick-folder').addEventListener('click', () => pick('folder'));
  $('clear-solution').addEventListener('click', () => clearPath('solution'));
  $('clear-folder').addEventListener('click', () => clearPath('folder'));
  $('btn-run').addEventListener('click', startRun);
  $('btn-shutdown').addEventListener('click', requestShutdown);
  $('btn-export-csv').addEventListener('click', exportCsv);

  $('assignment-name').addEventListener('input', (e) => lsSet(LS.name, e.target.value));
  $('voxel-res').addEventListener('input', (e) => { lsSet(LS.voxel, e.target.value); updateRunGate(); });

  $('modal-close').addEventListener('click', () => modal.close());
  $('modal-scrim').addEventListener('click', () => modal.close());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.isOpen()) { e.preventDefault(); modal.close(); }
    else if (e.key === 'Escape' && $('sidebar').classList.contains('is-open')) closeDrawer();
    modal.trap(e);
  });
}

async function boot() {
  applyTheme(resolveInitialTheme());
  wireEvents();

  /* ---- Rehydrate from localStorage ---- */
  state.solutionPath = lsGet(LS.solution);
  state.folderPath = lsGet(LS.folder);
  $('assignment-name').value = lsGet(LS.name, 'SolidGrade_Run');
  $('voxel-res').value = lsGet(LS.voxel, '64');
  renderPicker('solution');
  renderPicker('folder');

  setView(lsGet(LS.view, 'home'));

  /* ---- Rehydrate from the server. THIS is the refresh fix: the run state
     lives on the server and always did; the old page simply never asked
     for it outside the poll loop. ---- */
  try {
    const r = await api('/api/run_status');
    /* Rebuild an approximate per-file series for a run that started before
       this page load, so the trend is not blank after a refresh. */
    if (r.status !== 'idle' && r.current > 0 && r.elapsed_s) {
      const mean = r.elapsed_s / r.current;
      state.fileSeries = Array.from({ length: r.current }, () => mean);
      if (typeof r.file_seconds === 'number') state.fileSeries[state.fileSeries.length - 1] = r.file_seconds;
    }
    ingestRun(r);
    if (r.status === 'running') {
      startRunPolling();
      toast('Reconnected to a grading run already in progress.');
    }
  } catch (_) { /* server not up yet; the status poll will retry */ }

  validatePaths();
  await refreshStatus();

  /* Idle status cadence. Deliberately 10s: background browser tabs clamp
     timers to 60s, which is what produced the 5-tabs-at-:50 signature in
     the Milestone 1 logs. In the webview shell there is only ever one
     page, so this stays honest. */
  state.statusTimer = setInterval(refreshStatus, 10000);
}

document.addEventListener('DOMContentLoaded', boot);
