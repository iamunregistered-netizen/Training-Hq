// Cross-device sync via the Worker's /api/sync (D1). Loaded after app.js (shares its globals).
(function () {
  const SK = 'trainingHQ_sync';
  let meta = { since: 0, hashes: {}, stamps: {}, init: false };
  try { Object.assign(meta, JSON.parse(localStorage.getItem(SK) || '{}')); } catch (e) {}
  let busy = false, timer = null;
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : 'id-' + Date.now() + '-' + Math.random().toString(16).slice(2));
  const persist = () => { try { localStorage.setItem(SK, JSON.stringify(meta)); } catch (e) {} };
  const hash = o => { const s = JSON.stringify(o, (k, v) => (k === 'updatedAt' ? undefined : v)); let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h + ':' + s.length; };
  const setStatus = (pill, text) => {
    const p = document.getElementById('saveStatus'); if (p) p.textContent = pill;
    const s = document.getElementById('syncStatus'); if (s) s.textContent = text || pill;
  };

  function snapshot() {
    const m = {};
    state.programs.forEach(p => { p.id = p.id || uid(); m['program:' + p.id] = { kind: 'program', ...p }; });
    state.logs.forEach(l => { l.id = l.id || uid(); const { photoNote, ...r } = l; m['log:' + l.id] = { kind: 'log', ...r }; }); // photos stay on-device
    m['settings:settings'] = { kind: 'settings', id: 'settings', maxes: state.maxes, profile: state.profile, rounding: state.rounding, weekLoads: state.weekLoads, checklists: state.checklists, progressionEngines: state.progressionEngines };
    return m;
  }

  function applyRemote(recs) {
    const applied = [];
    for (const r of recs) {
      const key = r.kind + ':' + r.id;
      if ((meta.stamps[key] || 0) >= r.updatedAt) continue;
      const { kind, updatedAt, deleted, ...data } = r;
      if (kind === 'program') {
        const i = state.programs.findIndex(p => p.id === r.id);
        if (deleted) { if (i >= 0 && state.programs.length > 1) state.programs.splice(i, 1); }
        else if (i >= 0) state.programs[i] = data; else state.programs.push(data);
      } else if (kind === 'log') {
        const i = state.logs.findIndex(l => l.id === r.id);
        if (deleted) { if (i >= 0) state.logs.splice(i, 1); }
        else if (i >= 0) state.logs[i] = { ...data, ...(state.logs[i].photoNote ? { photoNote: state.logs[i].photoNote } : {}) };
        else state.logs.push(data);
      } else if (kind === 'settings' && !deleted) {
        const { id, ...s } = data; Object.assign(state, s);
      }
      meta.stamps[key] = updatedAt; applied.push({ key, deleted: !!deleted });
    }
    if (applied.length) {
      if (!state.programs.some(p => p.name === state.activeProgram)) state.activeProgram = state.programs[0].name;
      _save(); render();
    }
    return applied;
  }

  async function post(payload) {
    let res;
    const key = localStorage.getItem('trainingHQ_syncKey') || '';
    const hdr = { 'Content-Type': 'application/json' }; if (key) hdr.Authorization = 'Bearer ' + key;
    const ac = new AbortController(), to = setTimeout(() => ac.abort(), 20000);
    try { res = await fetch('/api/sync', { method: 'POST', headers: hdr, body: JSON.stringify(payload), credentials: 'same-origin', redirect: 'manual', signal: ac.signal }); }
    catch (e) { throw ac.signal.aborted ? { http: 'timed out after 20s' } : { offline: true }; }
    finally { clearTimeout(to); }
    const ct = res.headers.get('content-type') || '';
    if (res.type === 'opaqueredirect') throw { auth: true, detail: 'Cloudflare Access is redirecting to its login page (sign in, or turn Access off to use the passcode only)' };
    if (res.status === 401 || res.status === 403) { let d = ''; try { d = (await res.json()).error || ''; } catch (e) {} throw { auth: true, detail: d || ('Blocked before reaching the Worker (HTTP ' + res.status + ', likely Cloudflare Access)') }; }
    if (!ct.includes('json')) throw { auth: true, detail: 'Unexpected reply (HTTP ' + res.status + ', ' + (ct || 'no content-type') + ') - the new Worker code may not be deployed' };
    if (!res.ok) throw { http: res.status };
    return res.json();
  }

  async function syncNow(manual) {
    if (busy) { if (manual) toast('A sync is already running…'); return; }
    if (!navigator.onLine) { setStatus('● Saved · offline, will sync later'); if (manual) toast('Offline — will sync when you reconnect'); return; }
    busy = true; setStatus('↻ Syncing…');
    try {
      if (!meta.init) {
        const first = await post({ since: 0, changes: [] });
        if (first.records.some(r => r.kind === 'program') &&
            confirm('Cloud data was found. OK = replace this device’s programs and logs with the cloud copy (recommended for a second device). Cancel = keep this device’s data and merge it with the cloud (may create duplicate programs).')) {
          state.programs = []; state.logs = []; meta.stamps = {}; applyRemote(first.records);
          const snap = snapshot(); meta.hashes = {}; Object.keys(snap).forEach(k => meta.hashes[k] = hash(snap[k]));
          meta.since = first.serverTime;
        }
        meta.init = true; persist();
      }
      const snap = snapshot(), now = Date.now(), changes = [], sent = {};
      for (const [key, rec] of Object.entries(snap)) {
        const h = hash(rec); sent[key] = h;
        if (meta.hashes[key] !== h) { meta.stamps[key] = now; changes.push({ ...rec, updatedAt: now }); }
      }
      for (const key of Object.keys(meta.hashes)) if (!(key in snap)) {
        const [kind, ...rest] = key.split(':'); meta.stamps[key] = now;
        changes.push({ kind, id: rest.join(':'), deleted: true, updatedAt: now });
      }
      for (let i = 0; i < changes.length; i += 200) await post({ changes: changes.slice(i, i + 200), pull: false });
      const out = await post({ since: meta.since, changes: [] });
      const applied = applyRemote(out.records);
      if (manual) await new Promise(r => setTimeout(r, 500));
      meta.hashes = sent;
      applied.forEach(a => { if (a.deleted) delete meta.hashes[a.key]; });
      if (applied.length) { const s2 = snapshot(); applied.forEach(a => { if (s2[a.key]) meta.hashes[a.key] = hash(s2[a.key]); }); }
      meta.since = out.serverTime; persist();
      setStatus('● Synced', 'Synced ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' · sent ' + changes.length + ' · received ' + applied.length);
      if (manual) toast('Sync complete · sent ' + changes.length + ', received ' + applied.length);
    } catch (e) {
      let msg;
      if (e.auth) { setStatus('⚠ Sync refused', 'Refused: ' + (e.detail || 'unknown reason')); msg = 'Refused: ' + (e.detail || 'unknown reason'); }
      else if (e.offline) { setStatus('● Saved · offline, will sync later', 'Could not reach the server.'); msg = 'Could not reach the server'; }
      else { setStatus('⚠ Sync error', 'Sync failed (' + (e.http || e.message || 'unknown') + '). Your data is safe on this device.'); msg = 'Sync failed (' + (e.http || e.message || 'unknown') + ')'; }
      if (manual) toast(msg);
    } finally { busy = false; }
  }

  const _save = save;
  save = function () { _save.apply(this, arguments); clearTimeout(timer); timer = setTimeout(() => syncNow(false), 4000); };
  const keyInfo = () => { const k = localStorage.getItem('trainingHQ_syncKey') || '', el = document.getElementById('syncKeyInfo'); if (el && k) el.textContent = 'Saved on this device: ' + k[0] + '…' + k[k.length - 1] + ' (' + k.length + ' characters)'; };
  keyInfo();
  window.thqSync = () => { toast('Syncing…'); try { const k = document.getElementById('syncKey'); if (k && k.value.trim()) { localStorage.setItem('trainingHQ_syncKey', k.value.trim()); k.value = ''; k.placeholder = 'Passcode saved on this device'; keyInfo(); } syncNow(true).catch(e => setStatus('⚠ Sync error', 'Sync crashed: ' + (e && e.message || e))); } catch (e) { setStatus('⚠ Sync error', 'Sync crashed: ' + (e && e.message || e)); } };
  if (localStorage.getItem('trainingHQ_syncKey')) { const k = document.getElementById('syncKey'); if (k) k.placeholder = 'Passcode saved on this device'; }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) syncNow(false); });
  window.addEventListener('online', () => syncNow(false));
  setInterval(() => { if (!document.hidden) syncNow(false); }, 60000);
  setTimeout(() => syncNow(false), 1200);
})();
