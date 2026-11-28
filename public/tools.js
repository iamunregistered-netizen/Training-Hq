/* Training HQ — workout & progress tools.
 *
 * Loaded after app.js. It extends the app by wrapping a few of its functions
 * (openWorkout, saveWorkout, closeModal, renderProgram, renderProgress, renderSettings)
 * so the large render functions in app.js stay untouched.
 *
 *  1. "Last time" values per exercise (+ one-tap "Use these")
 *  2. Floating rest timer with default rest, +/-15s, sound and vibration
 *  3. Screen wake lock while a workout is open
 *  4. Plate calculator (per-side plates) + settings
 *  5. Swap an exercise for today, or in the plan
 *  6. Smarter personal records (heaviest, est. 1RM, rep bests) + "NEW PR" on save
 *  7. Training calendar heatmap + week streaks
 *  8. Volume by muscle group
 *  9. Bodyweight log + chart
 * 10. Deload copy of a week
 */
(function () {
  'use strict';

  /* ───────────── helpers ───────────── */
  const $ = id => document.getElementById(id);
  const num = x => Number(x) || 0;
  const r1 = x => Math.round(x * 10) / 10;
  const r2 = x => Math.round(x * 100) / 100;
  const norm = s => String(s || '').trim().toLowerCase();
  const pad = n => String(n).padStart(2, '0');
  const ymd = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  const parseYmd = s => { const [y, m, d] = String(s).split('-').map(Number); return new Date(y, (m || 1) - 1, d || 1, 12); };
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const mondayOf = d => addDays(d, -((d.getDay() + 6) % 7));
  const fmtDate = s => { try { return parseYmd(s).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' }); } catch (e) { return s; } };
  const noon = () => { const t = new Date(); t.setHours(12, 0, 0, 0); return t; };

  const DEFAULT_CFG = { barKg: 20, plates: [25, 20, 15, 10, 5, 2.5, 1.25], defaultRest: 90, keepAwake: true, sound: true };
  const cfg = () => ({ ...DEFAULT_CFG, ...(state.settings || {}) });
  const logWeek = () => Math.max(1, Math.min(programWeekCount(), Number($('logWeek')?.value) || activeWeek()));
  const logDateValue = () => $('logDate')?.value || localISODate();

  /* ───────────── 4. plate calculator ───────────── */
  function plateBreakdown(total, bar, plates) {
    total = num(total);
    if (!(total > 0)) return null;
    const side = (total - bar) / 2;
    if (side < -1e-9) return { below: true };
    let rem = r2(side);
    const used = [];
    [...plates].filter(p => p > 0).sort((a, b) => b - a).forEach(p => {
      while (rem >= p - 1e-9) { used.push(p); rem = r2(rem - p); }
    });
    return { used, rem, loaded: r2(bar + 2 * (side - rem)) };
  }
  function fmtPlates(used) {
    if (!used.length) return 'bar only';
    const m = new Map();
    used.forEach(p => m.set(p, (m.get(p) || 0) + 1));
    return [...m].map(([p, n]) => (n > 1 ? n + '×' + p : String(p))).join(' + ');
  }
  function plateLine(w) {
    const c = cfg();
    const b = plateBreakdown(w, c.barKg, c.plates);
    if (!b) return '';
    if (b.below) return `<div class="plateline"><strong>${w} kg</strong> <span class="muted">lighter than the ${c.barKg} kg bar</span></div>`;
    return `<div class="plateline"><strong>${w} kg</strong> → ${fmtPlates(b.used)} <span class="muted">per side</span>${b.rem > 0 ? ` <span class="platewarn">closest loadable: ${b.loaded} kg</span>` : ''}</div>`;
  }
  function refreshPlatePanel(card) {
    const panel = card?.querySelector('[data-plate-panel]');
    if (!panel || panel.classList.contains('hidden')) return;
    const ws = [...new Set([...card.querySelectorAll('.setrow [data-field=weight]')].map(i => num(i.value)).filter(w => w > 0))].sort((a, b) => a - b);
    const c = cfg();
    panel.innerHTML = ws.length
      ? `<div class="muted small">Bar ${c.barKg} kg · plates ${c.plates.join(', ')}</div>` + ws.map(plateLine).join('')
      : '<div class="muted small">Enter a weight to see the plates.</div>';
  }

  /* ───────────── 2. rest timer (floating) ───────────── */
  const rest = { end: 0, total: 0, iv: 0, hideT: 0, label: '' };
  let audioCtx = null;
  function prepAudio() {
    if (!cfg().sound) return;
    try {
      const C = window.AudioContext || window.webkitAudioContext;
      if (!C) return;
      audioCtx = audioCtx || new C();
      if (audioCtx.state === 'suspended') audioCtx.resume();
    } catch (e) { /* audio is optional */ }
  }
  function beep() {
    if (!cfg().sound) return;
    try {
      prepAudio();
      if (!audioCtx) return;
      const t = audioCtx.currentTime;
      [0, 0.22].forEach(off => {
        const o = audioCtx.createOscillator(), g = audioCtx.createGain();
        o.type = 'sine';
        o.frequency.value = off ? 1175 : 880;
        g.gain.setValueAtTime(0.0001, t + off);
        g.gain.exponentialRampToValueAtTime(0.3, t + off + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + off + 0.4);
        o.connect(g); g.connect(audioCtx.destination);
        o.start(t + off); o.stop(t + off + 0.45);
      });
    } catch (e) { /* audio is optional */ }
  }
  function restEl() {
    let el = $('restPill');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'restPill';
    el.className = 'restpill hidden';
    el.setAttribute('role', 'timer');
    el.innerHTML = '<div class="restpill-main"><span class="restpill-label"></span><strong class="restpill-time"></strong></div>' +
      '<div class="restpill-actions"><button type="button" data-rest-adj="-15" aria-label="15 seconds less">−15</button><button type="button" data-rest-adj="15" aria-label="15 seconds more">＋15</button><button type="button" data-rest-skip>Skip</button></div>' +
      '<div class="restpill-bar"><i></i></div>';
    document.body.appendChild(el);
    el.querySelectorAll('[data-rest-adj]').forEach(b => b.onclick = () => {
      const d = Number(b.dataset.restAdj);
      rest.end = Math.max(Date.now(), rest.end) + d * 1000;
      rest.total = Math.max(1, rest.total + d);
      el.classList.remove('done');
      clearTimeout(rest.hideT);
      if (!rest.iv) rest.iv = setInterval(tickRest, 250);
      tickRest();
    });
    el.querySelector('[data-rest-skip]').onclick = stopRest;
    return el;
  }
  function tickRest() {
    const el = restEl();
    const left = Math.max(0, Math.ceil((rest.end - Date.now()) / 1000));
    el.querySelector('.restpill-time').textContent = left ? formatTimer(left) : 'Go!';
    el.querySelector('.restpill-bar i').style.width = (rest.total ? Math.min(100, 100 * (1 - left / rest.total)) : 100) + '%';
    if (left <= 0) {
      clearInterval(rest.iv); rest.iv = 0;
      el.classList.add('done');
      beep();
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
      clearTimeout(rest.hideT);
      rest.hideT = setTimeout(stopRest, 6000);
    }
  }
  function startRest(seconds, label) {
    seconds = Math.max(1, Math.round(num(seconds)));
    const el = restEl();
    clearInterval(rest.iv); clearTimeout(rest.hideT);
    rest.total = seconds; rest.end = Date.now() + seconds * 1000; rest.label = label || '';
    el.querySelector('.restpill-label').textContent = 'Rest' + (label ? ' · ' + label : '');
    el.classList.remove('hidden', 'done');
    document.body.classList.add('has-restpill'); // reserves room so the pill never covers the Save button
    rest.iv = setInterval(tickRest, 250);
    tickRest();
  }
  function stopRest() {
    clearInterval(rest.iv); clearTimeout(rest.hideT);
    rest.iv = 0; rest.end = 0;
    $('restPill')?.classList.add('hidden');
    document.body.classList.remove('has-restpill');
  }

  /* ───────────── 3. wake lock ───────────── */
  let wake = null;
  async function syncWake() {
    const want = cfg().keepAwake && !document.hidden && !!$('workoutExercises');
    try {
      if (want && !wake && navigator.wakeLock) {
        wake = await navigator.wakeLock.request('screen');
        if (wake && wake.addEventListener) wake.addEventListener('release', () => { wake = null; });
      } else if (!want && wake) {
        const w = wake; wake = null;
        await w.release();
      }
    } catch (e) { wake = null; }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) syncWake(); });

  /* ───────────── 1. last time ───────────── */
  function lastSession(exercise, before) {
    const key = norm(exercise);
    const had = l => norm(l.exercise) === key && (num(l.weight) > 0 || num(l.reps) > 0 || num(l.metricValue) > 0);
    let date = '';
    for (const l of state.logs || []) { if (l.date && l.date < before && had(l) && l.date > date) date = l.date; }
    if (!date) return null;
    return { date, sets: (state.logs || []).filter(l => l.date === date && had(l)) };
  }
  function fmtSet(l) {
    const w = num(l.weight), reps = num(l.reps), m = num(l.metricValue);
    if (reps > 0) return (w > 0 ? r2(w) + '×' : '') + reps;
    if (m > 0) return (w > 0 ? r2(w) + 'kg · ' : '') + m + (l.metricUnit ? ' ' + l.metricUnit : '');
    return r2(w) + ' kg';
  }
  function useLastValues(card) {
    const last = lastSession(card.dataset.name, logDateValue());
    if (!last || !last.sets.length) return;
    card.querySelectorAll('.setrow').forEach((row, i) => {
      const src = last.sets[Math.min(i, last.sets.length - 1)];
      const set = (sel, v) => { const inp = row.querySelector(sel); if (inp && v > 0) { inp.value = v; inp.dispatchEvent(new Event('input', { bubbles: true })); } };
      set('[data-field=weight]', num(src.weight));
      set('[data-field=reps]', num(src.reps));
      set('[data-field=metric]', num(src.metricValue));
    });
    toast('Filled from ' + fmtDate(last.date));
  }

  /* ───────────── 5. swap ───────────── */
  const swapKey = (program, week, day, name) => [program, week, day, norm(name)].join('|');
  function ensureLibraryDatalist() {
    let dl = $('thqLibrary');
    if (!dl) { dl = document.createElement('datalist'); dl.id = 'thqLibrary'; document.body.appendChild(dl); }
    dl.innerHTML = (state.exerciseLibrary || []).map(x => `<option value="${esc(x)}">`).join('');
  }
  // Re-creates what openWorkout binds per card, for a card that was swapped in place.
  function bindWorkoutCard(card) {
    const head = card.querySelector('.exercisehead');
    if (head && !head.querySelector('[data-log-drag-handle]')) head.insertAdjacentHTML('afterbegin', '<button type="button" class="logdraghandle" data-log-drag-handle aria-label="Drag to reorder exercise" title="Hold and drag to reorder">☷</button>');
    card.querySelectorAll('[data-addset]').forEach(b => b.onclick = () => {
      const n = card.querySelectorAll('.setrow').length + 1;
      card.querySelector('.setrows').insertAdjacentHTML('beforeend', card.dataset.unitType && card.dataset.unitType !== 'reps'
        ? metricRowHTML(n, Number(card.dataset.suggest) || 0, '', card.dataset.unitLabel || 'value')
        : setRowHTML(n, Number(card.dataset.suggest) || 0, 1, !!card.querySelector('[data-field="reps"]')));
      bindSetRows(card);
    });
    card.querySelectorAll('[data-remove-ex]').forEach(b => b.onclick = () => card.remove());
    bindSetRows(card); bindExerciseTimers(card);
    card.classList.toggle('is-expanded', !card.classList.contains('exercise-done'));
    const collapse = card.querySelector('[data-collapse-ex]');
    if (collapse) collapse.onclick = () => {
      card.classList.toggle('is-expanded');
      card.classList.toggle('is-collapsed', !card.classList.contains('is-expanded'));
      collapse.textContent = card.classList.contains('is-expanded') ? 'Minimise' : 'Expand';
    };
    card.classList.toggle('is-collapsed', !card.classList.contains('is-expanded'));
    const photo = card.querySelector('[data-photo-note]');
    if (photo) photo.onchange = () => {
      const f = photo.files?.[0], label = card.querySelector('[data-photo-status]');
      if (label) label.textContent = f ? f.name + ' · ready to save' : 'Attach a photo for this exercise';
    };
    const cb = card.querySelector('[data-exdone]');
    if (cb) cb.addEventListener('change', () => {
      setExerciseChecked(activeWorkout.program, logWeek(), activeWorkout.day, card.dataset.name, cb.checked);
      card.classList.toggle('exercise-done', cb.checked);
      card.classList.toggle('is-expanded', !cb.checked);
      card.classList.toggle('is-collapsed', cb.checked);
      if (collapse) collapse.textContent = cb.checked ? 'Expand' : 'Minimise';
    });
  }
  function doSwap(card, newName, mode) {
    const items = activeWorkout.items, cur = card.dataset.name;
    const idx = items.findIndex(it => it.name === cur);
    if (idx < 0) return null;
    const original = card.dataset.swappedFrom || cur;
    const week = logWeek(), day = activeWorkout.day, prog = activeWorkout.program;
    const key = swapKey(prog, week, day, original);
    state.swaps = state.swaps || {};
    let item = { ...items[idx] };
    if (mode === 'restore') {
      const planItem = (dayPlanForWeek(day, week)?.items || []).find(x => norm(x.name) === norm(original));
      item = { ...(planItem || item), name: original };
      delete item.swappedFrom;
      delete state.swaps[key];
      save();
    } else {
      const name = String(newName || '').trim();
      if (!name) { toast('Choose or type an exercise'); return null; }
      if (norm(name) === norm(cur)) { toast('That is already the exercise'); return null; }
      if (mode === 'today') { state.swaps[key] = name; item.swappedFrom = original; }
      else if (mode === 'plan') {
        const plan = mutableDayPlan(day, week);
        const t = (plan.items || []).find(x => norm(x.name) === norm(original));
        if (t) t.name = name;
        delete state.swaps[key];
        delete item.swappedFrom;
      } else if (mode === 'stored') item.swappedFrom = original;
      item.name = name;
      if (!(state.exerciseLibrary || []).some(x => norm(x) === norm(name))) state.exerciseLibrary.push(name);
      if (mode !== 'stored') save();
    }
    items[idx] = item;
    const tpl = document.createElement('template');
    tpl.innerHTML = workoutItemHTML(item, idx).trim();
    const nc = tpl.content.firstElementChild;
    if (item.swappedFrom) nc.dataset.swappedFrom = item.swappedFrom;
    card.replaceWith(nc);
    bindWorkoutCard(nc);
    if (mode !== 'stored') {
      enhanceCard(nc);
      toast(mode === 'restore' ? 'Restored ' + item.name : mode === 'plan' ? 'Plan updated: now ' + item.name : 'Swapped for today: ' + item.name);
    }
    return nc;
  }
  function toggleSwapPanel(card) {
    const p = card.querySelector('[data-swap-panel]');
    if (!p) return;
    if (!p.classList.contains('hidden')) { p.classList.add('hidden'); return; }
    ensureLibraryDatalist();
    p.innerHTML = `<div class="swapbox"><label>Swap <strong>${esc(card.dataset.name)}</strong> for…</label>` +
      '<input type="text" data-swap-name list="thqLibrary" placeholder="Type or pick an exercise" autocomplete="off">' +
      '<div class="btnrow"><button type="button" class="btn primary" data-swap-go="today">Swap for today</button>' +
      '<button type="button" class="btn" data-swap-go="plan" title="Renames this exercise in the plan for this week">Swap &amp; update plan</button>' +
      (card.dataset.swappedFrom ? `<button type="button" class="btn ghost" data-swap-go="restore">↩ Restore ${esc(card.dataset.swappedFrom)}</button>` : '') +
      '<button type="button" class="btn ghost" data-swap-go="cancel">Cancel</button></div></div>';
    p.classList.remove('hidden');
    p.querySelector('input').focus();
  }

  /* ───────────── workout modal wiring ───────────── */
  function enhanceCard(card) {
    if (card.dataset.thq) return;
    card.dataset.thq = '1';
    const head = card.querySelector('.exercisehead');
    const actions = card.querySelector('.exercisehead > div:last-child');
    if (actions && !actions.querySelector('[data-swap]')) actions.insertAdjacentHTML('afterbegin', '<button type="button" class="btn ghost" data-swap aria-label="Swap exercise" title="Swap this exercise">⇄</button>');
    if (head) head.insertAdjacentHTML('afterend', '<div class="swappanel hidden" data-swap-panel></div>');
    if (card.dataset.swappedFrom) {
      const pres = card.querySelector('.prescription');
      if (pres) pres.insertAdjacentHTML('beforeend', ` · <span class="swapped-tag">swapped for ${esc(card.dataset.swappedFrom)}</span>`);
    }
    if (card.dataset.run === '1') return;
    // last time
    const last = lastSession(card.dataset.name, logDateValue());
    const anchor = card.querySelector('.exercise-collapsible > .setline:not(.setrow)') || card.querySelector('.setrows');
    if (anchor && last) {
      anchor.insertAdjacentHTML('beforebegin',
        `<div class="lasttime"><span>Last time · ${esc(fmtDate(last.date))}: <strong>${esc(last.sets.map(fmtSet).join(' · '))}</strong></span><button type="button" class="btn ghost" data-use-last>Use these</button></div>`);
    }
    // plates
    const add = card.querySelector('[data-addset]');
    if (add && card.querySelector('.setrow [data-field=weight]')) {
      add.insertAdjacentHTML('afterend', '<button type="button" class="btn ghost plates-btn" data-plates>⚖ Plates</button><div class="platepanel hidden" data-plate-panel></div>');
    }
  }
  function enhanceWorkoutModal() {
    const list = $('workoutExercises');
    if (!list) return;
    list.querySelectorAll('.exercise').forEach(card => {
      const orig = card.dataset.name;
      const to = state.swaps && state.swaps[swapKey(activeWorkout.program, logWeek(), activeWorkout.day, orig)];
      if (to && norm(to) !== norm(orig)) doSwap(card, to, 'stored');
    });
    list.querySelectorAll('.exercise').forEach(enhanceCard);
    list.addEventListener('input', e => refreshPlatePanel(e.target.closest('.exercise')));
    list.addEventListener('click', e => {
      const card = e.target.closest('.exercise');
      if (!card) return;
      if (e.target.closest('[data-use-last]')) { useLastValues(card); return; }
      if (e.target.closest('[data-plates]')) {
        const p = card.querySelector('[data-plate-panel]');
        p.classList.toggle('hidden');
        refreshPlatePanel(card);
        return;
      }
      if (e.target.closest('[data-addset]')) setTimeout(() => refreshPlatePanel(card), 0);
      if (e.target.closest('[data-swap]')) { toggleSwapPanel(card); return; }
      const go = e.target.closest('[data-swap-go]');
      if (go) {
        if (go.dataset.swapGo === 'cancel') { card.querySelector('[data-swap-panel]').classList.add('hidden'); return; }
        doSwap(card, card.querySelector('[data-swap-name]')?.value, go.dataset.swapGo);
      }
    });
    syncWake();
  }
  // start the rest pill when a set is ticked
  document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('#workoutExercises [data-setcheck]');
    if (!b) return;
    setTimeout(() => {
      if (!b.classList.contains('checked')) return;
      prepAudio();
      const card = b.closest('.exercise');
      let rests = [];
      try { rests = JSON.parse(card.dataset.restTimes || '[]'); } catch (_) { /* ignore */ }
      const n = card.querySelectorAll('[data-setcheck].checked').length;
      const secs = rests.length ? num(rests[Math.min(Math.max(n - 1, 0), rests.length - 1)]) : cfg().defaultRest;
      if (secs > 0) startRest(secs, card.dataset.name);
    }, 0);
  });

  /* ───────────── 6. personal records ───────────── */
  const epley = (w, r) => (w > 0 && r > 0 && r <= 12) ? (r === 1 ? w : w * (1 + r / 30)) : 0;
  function prTable(logs) {
    const t = {};
    for (const l of logs || []) {
      const w = num(l.weight), r = Math.round(num(l.reps));
      if (!(w > 0) || !(r > 0) || !l.exercise) continue;
      const k = norm(l.exercise);
      const e = t[k] || (t[k] = { name: String(l.exercise).trim(), bestW: null, bestE: null, byReps: {} });
      if (!e.bestW || w > e.bestW.w || (w === e.bestW.w && r > e.bestW.r)) e.bestW = { w, r, date: l.date };
      const ev = epley(w, r);
      if (ev > 0 && (!e.bestE || ev > e.bestE.v)) e.bestE = { v: ev, w, r, date: l.date };
      if (!e.byReps[r] || w > e.byReps[r].w) e.byReps[r] = { w, date: l.date };
    }
    return t;
  }
  function detectPRs(before, added) {
    const after = prTable(state.logs);
    const out = [];
    const seen = new Set(added.map(l => norm(l.exercise)).filter(Boolean));
    seen.forEach(k => {
      const b = before[k], a = after[k];
      if (!b || !a) return; // first time logging an exercise is a baseline, not a PR
      if (a.bestW.w > b.bestW.w) out.push(`${a.name} ${a.bestW.w} kg × ${a.bestW.r}`);
      else if (a.bestE && b.bestE && a.bestE.v > b.bestE.v + 0.05) out.push(`${a.name} est. 1RM ${r1(a.bestE.v)} kg`);
      else {
        const reps = added.filter(l => norm(l.exercise) === k).map(l => Math.round(num(l.reps))).filter(r => r > 0);
        const hit = reps.find(r => b.byReps[r] && a.byReps[r] && a.byReps[r].w > b.byReps[r].w);
        if (hit) out.push(`${a.name} ${a.byReps[hit].w} kg × ${hit}`);
      }
    });
    return out;
  }
  function renderRecords() {
    const el = $('recordsList');
    if (!el) return;
    const rows = Object.values(prTable(state.logs)).sort((a, b) => b.bestW.w - a.bestW.w);
    if (!rows.length) { el.innerHTML = '<div class="empty">Your logged bests will appear here.</div>'; return; }
    el.innerHTML = rows.map(e => {
      const reps = Object.keys(e.byReps).map(Number).sort((a, b) => a - b).slice(0, 12);
      return `<details class="record"><summary><span>${esc(e.name)}</span><strong>${r2(e.bestW.w)} kg</strong></summary><div class="record-body">` +
        `<div class="muted small">Heaviest: <strong>${r2(e.bestW.w)} kg × ${e.bestW.r}</strong> · ${esc(fmtDate(e.bestW.date))}</div>` +
        (e.bestE ? `<div class="muted small">Est. 1RM (Epley): <strong>${r1(e.bestE.v)} kg</strong> from ${r2(e.bestE.w)} × ${e.bestE.r} · ${esc(fmtDate(e.bestE.date))}</div>` : '') +
        `<div class="repbests">${reps.map(r => `<span class="pill">${r} rep${r > 1 ? 's' : ''}: <strong>${r2(e.byReps[r].w)}</strong></span>`).join('')}</div></div></details>`;
    }).join('');
  }

  /* ───────────── 7. calendar heatmap + streaks ───────────── */
  function renderHeatmap() {
    const el = $('consistency');
    if (!el) return;
    const days = new Map();
    for (const l of state.logs || []) { if (l.date) days.set(l.date, (days.get(l.date) || 0) + (num(l.sets) || 1)); }
    const today = noon(), thisMon = mondayOf(today), COLS = 16, start = addDays(thisMon, -7 * (COLS - 1));
    let cells = '';
    for (let c = 0; c < COLS; c++) for (let r = 0; r < 7; r++) {
      const d = addDays(start, c * 7 + r), key = ymd(d), n = days.get(key) || 0;
      const lvl = d > today ? 'f' : n === 0 ? 0 : n <= 6 ? 1 : n <= 14 ? 2 : n <= 24 ? 3 : 4;
      cells += `<i class="heat l${lvl}" title="${esc(fmtDate(key))}${n ? ' · ' + n + ' set' + (n > 1 ? 's' : '') : ''}"></i>`;
    }
    const weekSet = new Set();
    days.forEach((_, k) => weekSet.add(ymd(mondayOf(parseYmd(k)))));
    let cur = 0, w = thisMon;
    if (!weekSet.has(ymd(w))) w = addDays(w, -7); // a quiet Monday should not zero the streak
    while (weekSet.has(ymd(w))) { cur++; w = addDays(w, -7); }
    let best = 0, run = 0, prev = null;
    [...weekSet].sort().forEach(k => {
      const d = parseYmd(k);
      run = prev && Math.round((d - prev) / 864e5) === 7 ? run + 1 : 1;
      best = Math.max(best, run); prev = d;
    });
    const keys = [...days.keys()];
    const thisWeek = keys.filter(k => k >= ymd(thisMon) && k <= ymd(today)).length;
    const last30 = keys.filter(k => k > ymd(addDays(today, -30)) && k <= ymd(today)).length;
    el.insertAdjacentHTML('afterbegin',
      `<div class="streaks"><div><strong>${cur}</strong><small>week streak</small></div><div><strong>${best}</strong><small>best streak</small></div><div><strong>${thisWeek}</strong><small>this week</small></div><div><strong>${last30}</strong><small>last 30 days</small></div></div>` +
      `<div class="heatmap" role="img" aria-label="Training calendar, last ${COLS} weeks">${cells}</div>` +
      '<div class="heatlegend">Less <i class="heat l0"></i><i class="heat l1"></i><i class="heat l2"></i><i class="heat l3"></i><i class="heat l4"></i> More</div>');
  }

  /* ───────────── 8. muscle volume ───────────── */
  const GROUPS = ['Quads', 'Hams & glutes', 'Chest', 'Back', 'Shoulders', 'Arms', 'Core', 'Olympic', 'Conditioning', 'Other'];
  const MUSCLE_RULES = [
    [/treadmill|\baerobic\b|\brun(ning)?\b|\bbike\b|\bcycle\b|\berg\b|rowing|\browers?\b|recovery walk|mobility|shuttle|jump rope|skipping|assault|swim|\bwalk\b/i, 'Conditioning'],
    [/snatch|clean|jerk|thruster|muscle.?up|swing/i, 'Olympic'],
    [/rear delt|lateral raise|overhead press|military|shoulder|face pull|arnold|upright row|\bohp\b|push press/i, 'Shoulders'],
    [/deadlift|romanian|\brdl\b|hip thrust|glute|hamstring|leg curl|abduction|adduction|good ?morning|bridge|hyperextension|back extension/i, 'Hams & glutes'],
    [/squat|leg press|lunge|leg extension|step.?up|sissy|hack/i, 'Quads'],
    [/row|pull.?up|chin.?up|pulldown|vertical pull|\blat\b|shrug|pullover/i, 'Back'],
    [/bench|chest|\bfly\b|flye|push.?up|dip|\bpec\b|press/i, 'Chest'],
    [/curl|tricep|bicep|skull|hammer|pushdown|forearm/i, 'Arms'],
    [/plank|crunch|sit.?up|\bcore\b|ab wheel|leg raise|hanging|pallof|\bab\b|v-up|russian twist/i, 'Core']
  ];
  function muscleOf(name) {
    const o = state.muscles && state.muscles[name];
    if (o && GROUPS.includes(o)) return o;
    for (const [re, g] of MUSCLE_RULES) if (re.test(name || '')) return g;
    return 'Other';
  }
  function weekOptions() {
    const m = mondayOf(noon());
    return Array.from({ length: 8 }, (_, i) => {
      const d = addDays(m, -7 * i);
      return { key: ymd(d), label: i === 0 ? 'This week' : i === 1 ? 'Last week' : 'Week of ' + d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) };
    });
  }
  function muscleTotals(mondayKey) {
    const end = ymd(addDays(parseYmd(mondayKey), 6)), out = {};
    for (const l of state.logs || []) {
      if (!l.date || l.date < mondayKey || l.date > end || !l.exercise) continue;
      const o = out[muscleOf(l.exercise)] || (out[muscleOf(l.exercise)] = { sets: 0, tonnes: 0 });
      const sets = num(l.sets) || 1;
      o.sets += sets;
      o.tonnes += num(l.weight) * Math.max(0, num(l.reps)) * sets / 1000;
    }
    return out;
  }
  function renderMuscleVolume() {
    const sel = $('mvWeek'), box = $('muscleVolume'), metric = $('mvMetric')?.value || 'sets';
    if (!sel || !box) return;
    const opts = weekOptions();
    if (!sel.options.length) sel.innerHTML = opts.map(o => `<option value="${o.key}">${esc(o.label)}</option>`).join('');
    const cur = sel.value || opts[0].key;
    const prevKey = ymd(addDays(parseYmd(cur), -7));
    const a = muscleTotals(cur), b = muscleTotals(prevKey);
    const rows = Object.keys(a).map(g => ({ g, v: a[g][metric] || 0, p: (b[g] && b[g][metric]) || 0 })).filter(x => x.v > 0).sort((x, y) => y.v - x.v);
    if (!rows.length) { box.innerHTML = '<div class="empty">No logged sets for that week.</div>'; return; }
    const max = Math.max(...rows.map(x => x.v)), unit = metric === 'sets' ? '' : ' t';
    box.innerHTML = rows.map(x => {
      const d = r1(x.v - x.p);
      return `<div class="mvrow"><span class="mvname">${esc(x.g)}</span><div class="mvbar"><i style="width:${Math.max(3, Math.round(100 * x.v / max))}%"></i></div><strong>${r1(x.v)}${unit}</strong><small class="mvdelta ${d > 0 ? 'up' : d < 0 ? 'down' : ''}">${d > 0 ? '+' : ''}${d || '–'}</small></div>`;
    }).join('') + '<div class="muted small" style="margin-top:6px">Change is versus the previous week.</div>';
  }
  function openMuscleEditor(name) {
    modal('Muscle group · ' + name,
      `<div class="field"><label>Counts towards</label><select id="muscleSel">${GROUPS.map(g => `<option ${g === muscleOf(name) ? 'selected' : ''}>${g}</option>`).join('')}</select></div><div class="muted small">Automatic guess: ${esc(MUSCLE_RULES.reduce((f, [re, g]) => f || (re.test(name) ? g : ''), '') || 'Other')}</div>`,
      [{ label: 'Cancel', cls: 'btn ghost', action: closeModal },
       { label: 'Reset to automatic', cls: 'btn ghost', action: () => { if (state.muscles) delete state.muscles[name]; save(); closeModal(); renderProgram(); } },
       { label: 'Save', cls: 'btn primary', action: () => { state.muscles = state.muscles || {}; state.muscles[name] = $('muscleSel').value; save(); closeModal(); renderProgram(); toast(name + ' → ' + state.muscles[name]); } }]);
  }

  /* ───────────── 9. bodyweight log ───────────── */
  const bodyLog = () => (state.bodyLog = Array.isArray(state.bodyLog) ? state.bodyLog : []);
  function syncProfileWeight() {
    const l = [...bodyLog()].sort((a, b) => a.date.localeCompare(b.date)).pop();
    state.profile = state.profile || {};
    if (l) state.profile.bodyweight = String(l.kg);
  }
  function addBodyEntry(date, kg) {
    kg = r1(num(kg));
    if (!date || !(kg > 0)) { toast('Enter a date and a weight'); return false; }
    const log = bodyLog(), i = log.findIndex(x => x.date === date);
    if (i >= 0) log[i] = { date, kg }; else log.push({ date, kg });
    log.sort((a, b) => a.date.localeCompare(b.date));
    syncProfileWeight(); save();
    return true;
  }
  function renderBodyLog() {
    const list = $('bwList'), chart = $('bwChart'), sum = $('bwSummary');
    if (!list || !chart || !sum) return;
    if (!$('bwDate').value) $('bwDate').value = localISODate();
    const log = [...bodyLog()].sort((a, b) => a.date.localeCompare(b.date));
    if (!log.length) {
      sum.textContent = 'No entries yet.'; chart.innerHTML = '<div class="empty">Add your weight to see a trend.</div>'; list.innerHTML = ''; return;
    }
    const latest = log[log.length - 1];
    const ref = [...log].reverse().find(x => x.date <= ymd(addDays(parseYmd(latest.date), -28)));
    sum.textContent = `Latest ${latest.kg} kg (${fmtDate(latest.date)})` + (ref ? ` · ${latest.kg - ref.kg >= 0 ? '+' : '−'}${r1(Math.abs(latest.kg - ref.kg))} kg vs 4 weeks earlier` : '');
    const W = 330, H = 170, L = 34, R = 8, T = 12, B = 26, iw = W - L - R, ih = H - T - B;
    const vals = log.map(x => x.kg), lo = Math.floor(Math.min(...vals) - 1), hi = Math.ceil(Math.max(...vals) + 1);
    const t0 = parseYmd(log[0].date).getTime(), t1 = parseYmd(log[log.length - 1].date).getTime();
    const pts = log.map((p, i) => ({ ...p, x: L + (log.length === 1 || t1 === t0 ? iw / 2 : (parseYmd(p.date).getTime() - t0) / (t1 - t0) * iw), y: T + (hi - p.kg) / ((hi - lo) || 1) * ih }));
    let grid = '';
    for (let i = 0; i < 4; i++) { const v = lo + (hi - lo) * i / 3, y = T + ih - i / 3 * ih; grid += `<line x1="${L}" y1="${y}" x2="${W - R}" y2="${y}" stroke="#293953"/><text x="${L - 6}" y="${y + 3}" fill="#9aabc5" font-size="9" text-anchor="end">${r1(v)}</text>`; }
    chart.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Bodyweight trend">${grid}<polyline points="${pts.map(p => p.x + ',' + p.y).join(' ')}" fill="none" stroke="#8ce0b2" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>${pts.map(p => `<circle cx="${p.x}" cy="${p.y}" r="3.5" fill="#8ce0b2"><title>${p.date}: ${p.kg} kg</title></circle>`).join('')}${pts.filter((p, i) => i === 0 || i === pts.length - 1).map(p => `<text x="${p.x}" y="${H - 8}" fill="#9aabc5" font-size="9" text-anchor="middle">${esc(p.date.slice(5))}</text>`).join('')}</svg>`;
    list.innerHTML = [...log].reverse().slice(0, 8).map(x => `<div class="switchrow"><span>${esc(fmtDate(x.date))}</span><strong>${x.kg} kg</strong><button type="button" class="btn ghost danger" data-bw-del="${x.date}" aria-label="Delete entry">✕</button></div>`).join('');
    list.querySelectorAll('[data-bw-del]').forEach(b => b.onclick = () => {
      const entry = bodyLog().find(x => x.date === b.dataset.bwDel);
      state.bodyLog = bodyLog().filter(x => x.date !== b.dataset.bwDel);
      syncProfileWeight(); save(); renderBodyLog();
      toastAction('Entry removed', 'Undo', () => { if (entry) { addBodyEntry(entry.date, entry.kg); renderBodyLog(); } });
    });
  }

  /* ───────────── 10. deload copy ───────────── */
  function scaleItemForDeload(it, volPct, loadPct) {
    const c = structuredClone(it), f = loadPct / 100;
    const sets = Math.max(1, Math.round((Number(c.sets) || 1) * volPct / 100));
    c.sets = sets;
    if (num(c.loadKg) > 0) c.loadKg = roundWeight(c.loadKg * f);
    if (num(c.pct) > 0) c.pct = r1(c.pct * f);
    if (Array.isArray(c.setScheme) && c.setScheme.length) {
      c.setScheme = c.setScheme.slice(0, sets).map(x => ({ ...x, loadKg: num(x.loadKg) > 0 ? roundWeight(x.loadKg * f) : x.loadKg }));
    }
    c.planNote = [c.planNote, 'Deload'].filter(Boolean).join(' · ');
    return c;
  }
  function createDeloadWeek(w, volPct, loadPct, name) {
    const p = active(), next = programWeekCount(p) + 1, hadCount = p.weekCount, hadNames = { ...(p.weekNames || {}) }, prevWeek = activeWeek();
    const plan = {};
    PLAN_DAYS.forEach(d => {
      const src = dayPlanForWeek(d, w, p) || { type: '', description: '', items: [] };
      plan[d] = { ...structuredClone(src), items: (src.items || []).map(it => scaleItemForDeload(it, volPct, loadPct)) };
    });
    p.weekPlans = p.weekPlans || {};
    p.weekPlans[String(next)] = plan;
    p.weekCount = next; p.week = next; state.week = next;
    p.weekNames = p.weekNames || {};
    p.weekNames[String(next)] = name || ('Deload — ' + weekLabel(w, p));
    save(); render();
    toastAction(weekLabel(next, p) + ' created (' + volPct + '% sets, ' + loadPct + '% load)', 'Undo', () => {
      const q = active();
      delete q.weekPlans[String(next)];
      if (hadCount === undefined) delete q.weekCount; else q.weekCount = hadCount;
      q.weekNames = hadNames; q.week = prevWeek; state.week = prevWeek;
      save(); render();
    });
  }
  function openDeload() {
    const w = activeWeek();
    modal('Deload copy of ' + weekLabel(w),
      '<div class="notice">Creates a new week at the end of the program from the week you are viewing, with fewer sets and slightly lighter loads. Your original week is not changed.</div>' +
      '<div class="formgrid"><div class="field"><label>Sets (% of normal)</label><input id="dlVol" type="number" min="10" max="100" step="5" value="60"></div>' +
      '<div class="field"><label>Load (% of normal)</label><input id="dlLoad" type="number" min="40" max="100" step="5" value="90"></div></div>' +
      `<div class="field"><label>Week name</label><input id="dlName" maxlength="40" value="${esc('Deload — ' + weekLabel(w))}"></div>`,
      [{ label: 'Cancel', cls: 'btn ghost', action: closeModal },
       { label: 'Create deload week', cls: 'btn primary', action: () => {
         const v = Math.max(10, Math.min(100, num($('dlVol').value) || 60)), l = Math.max(40, Math.min(100, num($('dlLoad').value) || 90));
         const name = $('dlName').value.trim();
         closeModal(); createDeloadWeek(w, v, l, name);
       } }]);
  }

  /* ───────────── settings (tools card) ───────────── */
  function renderToolSettings() {
    if (!$('toolBarKg')) return;
    const c = cfg();
    $('toolBarKg').value = c.barKg;
    $('toolDefaultRest').value = c.defaultRest;
    $('toolPlates').value = c.plates.join(', ');
    $('toolKeepAwake').checked = !!c.keepAwake;
    $('toolSound').checked = !!c.sound;
    updatePlateTool();
  }
  function updatePlateTool() {
    const out = $('plateOut'), t = num($('plateTarget')?.value);
    if (!out) return;
    out.innerHTML = t > 0 ? plateLine(t) : 'Enter a weight to see the plates per side.';
  }
  function bindToolSettings() {
    const save_ = $('saveTools');
    if (!save_ || save_.dataset.bound) return;
    save_.dataset.bound = '1';
    save_.onclick = () => {
      const plates = [...new Set(String($('toolPlates').value).split(/[,\s]+/).map(Number).filter(x => x > 0))].sort((a, b) => b - a);
      if (!plates.length) { toast('Enter at least one plate size'); return; }
      state.settings = { ...(state.settings || {}), barKg: Math.max(0, num($('toolBarKg').value)), plates, defaultRest: Math.max(0, Math.round(num($('toolDefaultRest').value))), keepAwake: $('toolKeepAwake').checked, sound: $('toolSound').checked };
      save(); renderToolSettings(); toast('Tool settings saved');
    };
    $('plateTarget').addEventListener('input', updatePlateTool);
    $('bwAdd')?.addEventListener('click', () => { if (addBodyEntry($('bwDate').value, $('bwKg').value)) { $('bwKg').value = ''; renderBodyLog(); toast('Bodyweight saved'); } });
    $('mvWeek')?.addEventListener('change', renderMuscleVolume);
    $('mvMetric')?.addEventListener('change', renderMuscleVolume);
  }

  /* ───────────── wrappers around app.js ───────────── */
  const baseOpenWorkout = openWorkout;
  openWorkout = function () {
    const r = baseOpenWorkout.apply(this, arguments);
    try { enhanceWorkoutModal(); } catch (e) { console.error('Training HQ tools', e); }
    return r;
  };

  const baseSaveWorkout = saveWorkout;
  saveWorkout = async function () {
    const before = prTable(state.logs), start = state.logs.length;
    const r = await baseSaveWorkout.apply(this, arguments);
    try {
      const added = state.logs.slice(start);
      if (added.length) {
        const prs = detectPRs(before, added);
        if (prs.length) {
          const shown = prs.slice(0, 3).join(' · ') + (prs.length > 3 ? ' · +' + (prs.length - 3) + ' more' : '');
          toastAction('🏆 New PR: ' + shown, 'View', () => navigate('progress'), 9000);
        }
      }
    } catch (e) { console.error('Training HQ tools', e); }
    return r;
  };

  const baseCloseModal = closeModal;
  closeModal = function () {
    baseCloseModal.apply(this, arguments);
    stopRest();
    syncWake();
  };

  const baseRenderProgress = renderProgress;
  renderProgress = function () {
    const r = baseRenderProgress.apply(this, arguments);
    try { renderRecords(); renderHeatmap(); renderMuscleVolume(); renderBodyLog(); } catch (e) { console.error('Training HQ tools', e); }
    return r;
  };

  const baseRenderProgram = renderProgram;
  renderProgram = function () {
    const r = baseRenderProgram.apply(this, arguments);
    try {
      const row = $('programMeta')?.querySelector('.btnrow');
      if (row && !$('deloadProgramWeek')) {
        row.insertAdjacentHTML('beforeend', '<button class="btn" id="deloadProgramWeek" type="button">⧉ Deload copy</button>');
        $('deloadProgramWeek').onclick = openDeload;
      }
      const lib = $('exerciseLibrary');
      if (lib) {
        lib.innerHTML = (state.exerciseLibrary || []).map(x => `<button type="button" class="pill pill-btn" data-muscle-ex="${esc(x)}" title="Change muscle group">${esc(x)} <small>· ${esc(muscleOf(x))}</small></button>`).join('');
        lib.querySelectorAll('[data-muscle-ex]').forEach(b => b.onclick = () => openMuscleEditor(b.dataset.muscleEx));
      }
    } catch (e) { console.error('Training HQ tools', e); }
    return r;
  };

  const baseRenderSettings = renderSettings;
  renderSettings = function () {
    const r = baseRenderSettings.apply(this, arguments);
    try { renderToolSettings(); } catch (e) { console.error('Training HQ tools', e); }
    return r;
  };

  bindToolSettings();
  renderToolSettings();
  if (typeof compressDashboardPanels === 'function') compressDashboardPanels(); // wraps the cards added in index.html

  // exposed for the browser tests
  window.THQ = { cfg, plateBreakdown, fmtPlates, prTable, detectPRs, muscleOf, lastSession, startRest, stopRest, GROUPS, scaleItemForDeload, createDeloadWeek };
})();
