import json, copy, runpy, sys
import os
TOOLS = os.path.dirname(os.path.abspath(__file__)).replace(chr(92), "/") + "/"
ROOT = os.path.dirname(TOOLS.rstrip("/")).replace(chr(92), "/") + "/"
SC = TOOLS
G04 = runpy.run_path(SC + "gen04.py")  # берём проверенные блоки кода воркфлоу 04
AI_COPY = G04["AI_COPY"]

ID06, ID07, ID08 = "ttScheduler000006", "ttPrepSlot000007", "ttPubSlot0000008"

PLANNER = r"""// Планировщик: строит слоты публикаций, отдаёт их на подготовку и публикацию, помечает просроченные, пишет сводку для панели.
// Состояние каждого слота лежит в отдельном файле /files/plan/<id>.json, поэтому параллельные воркфлоу не мешают друг другу.
const fs = require('fs');
const NAME = /^[A-Za-z0-9_-]{1,40}$/;
const PLAN = '/files/plan', STATE = '/files/state';
const MIN = 60000, HOUR = 3600000, DAY = 86400000;
for (const d of [PLAN, STATE + '/paused', STATE + '/first_plan', STATE + '/errors']) fs.mkdirSync(d, { recursive: true });
// Один планировщик за раз (блокировка старше 5 минут считается зависшей).
const LOCK = PLAN + '/.tick.lock';
try { if (Date.now() - fs.statSync(LOCK).mtimeMs > 5 * MIN) fs.rmSync(LOCK, { recursive: true, force: true }); } catch (e) { /* блокировки нет */ }
try { fs.mkdirSync(LOCK); } catch (e) { return []; }
try {
  const readJson = (f, d) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return d; } };
  const writeJson = (f, o) => { const t = f + '.tmp'; fs.writeFileSync(t, JSON.stringify(o)); fs.renameSync(t, f); };
  const now = Date.now();
  const emit = [];
  const warnings = [];

  // ---------- настройки ----------
  const base = {
    global: { paused: true, catchup_hours: 6, max_parallel: 2, max_prepare: 2, prepare_ahead_hours: 12, pause_after_errors: 3, min_free_gb: 5, max_prepared: 400 },
    default_profile: 'default',
    profiles: { default: { posts_per_day: 2, windows: [['10:00', '22:00']], min_gap_min: 120, days: [1, 2, 3, 4, 5, 6, 7], tz: $env.TZ || 'UTC', ramp: null, enabled: true } },
    group_profile: {}, overrides: {},
  };
  // schedule.json: при повреждении восстанавливаем из .bak; если копии нет, планировщик останавливается и файл НЕ затирается.
  let schErr = '';
  let sch = null;
  try { sch = JSON.parse(fs.readFileSync('/files/schedule.json', 'utf8')); }
  catch (e) {
    if (e.code === 'ENOENT') { sch = base; writeJson('/files/schedule.json', sch); }
    else {
      try { sch = JSON.parse(fs.readFileSync('/files/schedule.json.bak', 'utf8')); fs.copyFileSync('/files/schedule.json', '/files/schedule.json.corrupt-' + Date.now()); writeJson('/files/schedule.json', sch); schErr = 'schedule.json was damaged and restored from the backup copy.'; }
      catch (e2) { sch = Object.assign({}, base, { global: Object.assign({}, base.global, { paused: true }) }); schErr = 'schedule.json is damaged and there is no valid backup copy: the scheduler is stopped. Restore the file from your backup.'; }
    }
  }
  const G = Object.assign({}, base.global, sch.global || {});
  const profiles = (sch.profiles && Object.keys(sch.profiles).length) ? sch.profiles : base.profiles;
  const accCfg = readJson('/files/accounts.json', {});

  // ---------- время и часовые пояса (без внешних библиотек) ----------
  const tzOffset = (ts, tz) => {
    const p = {};
    for (const x of new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).formatToParts(new Date(ts))) p[x.type] = x.value;
    return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - Math.floor(ts / 1000) * 1000;
  };
  const localToUtc = (dateStr, minutes, tz) => {
    const [y, m, d] = dateStr.split('-').map(Number);
    const guess = Date.UTC(y, m - 1, d, 0, minutes);
    let t = guess - tzOffset(guess, tz);
    t = guess - tzOffset(t, tz);
    return t;
  };
  const localDate = (ts, tz) => new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ts));
  const weekday = (dateStr, tz) => ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(new Intl.DateTimeFormat('en-US', { timeZone: tz, weekday: 'short' }).format(new Date(localToUtc(dateStr, 720, tz)))) + 1;
  const addDays = (dateStr, n) => { const [y, m, d] = dateStr.split('-').map(Number); return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10); };
  const daysBetween = (a, b) => Math.round((Date.parse(b + 'T00:00:00Z') - Date.parse(a + 'T00:00:00Z')) / DAY);
  const toMin = s => { const m = /^(\d{1,2}):(\d{2})$/.exec(String(s)); return m ? Math.min(1440, +m[1] * 60 + +m[2]) : (String(s) === '24:00' ? 1440 : null); };

  // Случайные минуты внутри окон с минимальным интервалом; lo - не раньше этой минуты суток (для сегодняшнего дня).
  const genTimes = (n, windows, minGap, lo) => {
    const segs = (windows || []).map(w => { const a = toMin(w[0]); let z = toMin(w[1]); if (a == null || z == null) return null; if (z <= a) z += 1440; return [Math.max(a, lo), z]; }).filter(s => s && s[1] > s[0]);
    const total = segs.reduce((a, s) => a + (s[1] - s[0]), 0);
    if (!total || n < 1) return [];
    n = Math.min(n, Math.max(1, Math.floor(total / Math.max(1, minGap)) + 1));
    const at = x => { let r = x; for (const s of segs) { const len = s[1] - s[0]; if (r < len) return s[0] + r; r -= len; } return segs[segs.length - 1][1]; };
    for (let k = 0; k < 300; k++) {
      const pts = Array.from({ length: n }, () => at(Math.random() * total)).sort((a, b) => a - b);
      if (pts.every((v, i) => i === 0 || v - pts[i - 1] >= minGap)) return pts;
    }
    const step = total / n;
    return Array.from({ length: n }, (_, i) => at(step * i + Math.random() * step * 0.8)).sort((a, b) => a - b);
  };

  // ---------- аккаунты ----------
  const rows = {};
  for (const i of $('Accounts').all()) { const r = i.json; if (r && r.account) rows[String(r.account).toLowerCase()] = r; }
  const connected = Object.keys(rows).filter(a => NAME.test(a) && rows[a].refresh_token && Number(rows[a].refresh_expires_at) > now);
  const pausedInfo = a => {
    const f = STATE + '/paused/' + a + '.json', p = readJson(f, null);
    if (!p) return null;
    if (p.until && Date.parse(p.until) < now) { try { fs.unlinkSync(f); } catch (e) { /* уже нет */ } return null; }
    return p;
  };
  const resolve = a => {
    const cfg = accCfg[a] || {}, ov = (sch.overrides || {})[a] || {};
    const pname = ov.profile || (sch.group_profile || {})[cfg.group] || sch.default_profile || 'default';
    const prof = profiles[pname] || profiles[Object.keys(profiles)[0]];
    const e = Object.assign({}, prof);
    for (const k of ['posts_per_day', 'windows', 'min_gap_min', 'tz', 'days', 'ramp']) if (ov[k] !== undefined) e[k] = ov[k];
    e.profile = pname; e.paused = !!ov.paused;
    return e;
  };

  // ---------- слоты ----------
  const slots = [];
  for (const f of fs.readdirSync(PLAN)) {
    if (!f.endsWith('.json') || f[0] === '.') continue;
    const s = readJson(PLAN + '/' + f, null);
    if (s && s.id) slots.push(s);
  }
  const save = s => { s.updated = Date.now(); writeJson(PLAN + '/' + s.id + '.json', s); };
  const TERMINAL = ['done', 'skipped', 'failed'];
  for (const s of slots.slice()) {
    if (TERMINAL.includes(s.state) && now - (s.updated || s.at) > 2 * DAY) { try { fs.unlinkSync(PLAN + '/' + s.id + '.json'); } catch (e) { /* уже нет */ } slots.splice(slots.indexOf(s), 1); continue; }
    // зависшие состояния
    if (s.state === 'preparing' && now - (s.updated || 0) > 30 * MIN) { s.attempts = (s.attempts || 0) + 1; s.state = s.attempts >= 3 ? 'failed' : 'planned'; s.reason = s.attempts >= 3 ? 'preparation did not finish' : ''; save(s); }
    else if (s.state === 'publishing' && now - (s.updated || 0) > 20 * MIN) {
      s.state = 'failed'; s.reason = 'interrupted: check the TikTok account before publishing again'; save(s);
      try { fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: s.id, account: s.account, file: (s.video || {}).file || '', rel: (s.video || {}).rel || '', status: 'Error', error: 'Interrupted: the video may already be published. Check the TikTok account before publishing again.', kept: true, slot: s.id }) + '\n'); } catch (e) { /* не критично */ }
    }
    // слишком опоздавшие слоты пропускаем
    else if ((s.state === 'planned' || s.state === 'prepared') && now - Date.parse(s.at) > Number(G.catchup_hours) * HOUR) {
      s.state = 'skipped'; s.reason = 'missed (late by more than ' + G.catchup_hours + ' h)'; save(s);
      try { fs.rmSync('/files/prepared/' + s.id, { recursive: true, force: true }); } catch (e) { /* нет папки */ }
    }
  }

  // ---------- планирование на сегодня и завтра (по часовому поясу аккаунта) ----------
  const pd = readJson(STATE + '/plan_dates.json', {});
  if (!G.paused) {
    for (const a of connected) {
      if (pausedInfo(a)) continue;
      const e = resolve(a);
      if (e.paused || e.enabled === false) continue;
      const tz = e.tz || $env.TZ || 'UTC';
      try { new Intl.DateTimeFormat('en', { timeZone: tz }); } catch (er) { continue; }
      const today = localDate(now, tz), have = pd[a] || [];
      let first = null; try { first = fs.readFileSync(STATE + '/first_plan/' + a + '.txt', 'utf8').trim(); } catch (er) { first = null; }
      if (!first) { first = today; fs.writeFileSync(STATE + '/first_plan/' + a + '.txt', first); }
      for (const date of [today, addDays(today, 1)]) {
        if (have.includes(date)) continue;
        have.push(date);
        if (Array.isArray(e.days) && e.days.length && !e.days.includes(weekday(date, tz))) continue;
        let n = Number(e.posts_per_day) || 0;
        if (e.ramp && e.ramp.start) n = Math.min(n, Number(e.ramp.start) + Math.floor(Math.max(0, daysBetween(first, date)) / Math.max(1, Number(e.ramp.every_days) || 1)));
        const lo = date === today ? Math.max(0, Math.ceil((now - localToUtc(today, 0, tz)) / MIN) + 2) : 0;
        for (const m of genTimes(n, e.windows, Number(e.min_gap_min) || 0, lo)) {
          const at = localToUtc(date, m, tz) + Math.floor(Math.random() * 60000);
          const id = new Date(at).toISOString().slice(0, 16).replace(/[-:T]/g, '') + '_' + a + '_' + Math.random().toString(36).slice(2, 6);
          const slot = { id, account: a, at: new Date(at).toISOString(), state: 'planned', attempts: 0, date, tz, created: now };
          save(slot); slots.push(slot);
        }
      }
      pd[a] = have.filter(d => d >= addDays(today, -2));
    }
    writeJson(STATE + '/plan_dates.json', pd);
  }

  // ---------- выдача слотов в работу ----------
  const count = st => slots.filter(s => s.state === st).length;
  const busy = new Set(slots.filter(s => s.state === 'preparing' || s.state === 'publishing').map(s => s.account));
  const okAccount = a => !pausedInfo(a) && !(((sch.overrides || {})[a] || {}).paused);
  {
    let diskWarn = '';
    try { const sf = fs.statfsSync('/files'); const freeGb = sf.bavail * sf.bsize / 1073741824; if (freeGb < Number(G.min_free_gb || 5)) diskWarn = 'Low disk space (' + freeGb.toFixed(1) + ' GB free): new posts are not being prepared.'; } catch (e) { /* нет данных о диске */ }
    if (!diskWarn && count('prepared') + count('preparing') >= Number(G.max_prepared || 400)) diskWarn = 'Many prepared posts are waiting (' + (count('prepared') + count('preparing')) + '): preparation is paused until they are published.';
    if (diskWarn) warnings.push(diskWarn);
    let capPrep = diskWarn ? 0 : Number(G.max_prepare) - count('preparing');
    for (const s of slots.filter(x => x.state === 'planned' && (!G.paused || x.manual) && Date.parse(x.at) <= now + Number(G.prepare_ahead_hours) * HOUR).sort((x, y) => Date.parse(x.at) - Date.parse(y.at))) {
      if (capPrep <= 0) break;
      if (busy.has(s.account) || !okAccount(s.account) || !connected.includes(s.account)) continue;
      s.state = 'preparing'; save(s); busy.add(s.account); capPrep--; emit.push({ kind: 'prepare', slot: s });
    }
    let capPub = Number(G.max_parallel) - count('publishing');
    for (const s of slots.filter(x => x.state === 'prepared' && (!G.paused || x.manual) && Date.parse(x.at) <= now).sort((x, y) => Date.parse(x.at) - Date.parse(y.at))) {
      if (capPub <= 0) break;
      if (busy.has(s.account) || !okAccount(s.account) || !connected.includes(s.account)) continue;
      s.state = 'publishing'; save(s); busy.add(s.account); capPub--; emit.push({ kind: 'publish', slot: s });
    }
  }

  // ---------- сводка для панели ----------
  const counts = {}; for (const s of slots) counts[s.state] = (counts[s.state] || 0) + 1;
  const open = slots.filter(s => !TERMINAL.includes(s.state)).sort((x, y) => Date.parse(x.at) - Date.parse(y.at));
  const byAccount = {};
  for (const s of open) { const b = byAccount[s.account] || (byAccount[s.account] = { next_at: s.at, next_state: s.state, open: 0 }); b.open++; }
  const recent = slots.filter(s => TERMINAL.includes(s.state)).sort((x, y) => (y.updated || 0) - (x.updated || 0)).slice(0, 150);
  const paused = [];
  try { for (const f of fs.readdirSync(STATE + '/paused')) { const a = f.replace(/\.json$/, ''), p = pausedInfo(a); if (p) paused.push(Object.assign({ account: a }, p)); } } catch (e) { /* нет */ }
  writeJson('/files/plan_summary.json', {
    at: now, global: G, counts, by_account: byAccount, paused, errors: schErr ? [schErr] : [], warnings,
    upcoming: open.slice(0, 300).map(s => ({ id: s.id, account: s.account, at: s.at, state: s.state, manual: !!s.manual })),
    recent: recent.map(s => ({ id: s.id, account: s.account, at: s.at, state: s.state, reason: s.reason || s.error || '', result: s.result || '' })),
  });
  // Ежедневная уборка: старые счётчики попыток входа, билеты, завершённые приглашения (90 дней), журнал ошибок.
  const HK = STATE + '/housekeeping.json', hk = readJson(HK, { at: 0 });
  if (now - hk.at > DAY) {
    const rmOld = (dir, age) => { try { for (const f of fs.readdirSync(dir)) { const p = dir + '/' + f; try { if (now - fs.statSync(p).mtimeMs > age) fs.rmSync(p, { recursive: true, force: true }); } catch (e) { /* уже нет */ } } } catch (e) { /* нет папки */ } };
    rmOld('/files/state/auth_fail', DAY); rmOld('/files/tickets', 3600000);
    try {
      for (const f of fs.readdirSync('/files/invites')) {
        if (!f.endsWith('.json')) continue; const p = '/files/invites/' + f;
        try { const i = JSON.parse(fs.readFileSync(p, 'utf8')); const done = i.used_at || i.status === 'revoked' || Date.parse(i.expires_at) < now; const ref = Date.parse(i.used_at || i.expires_at || 0) || 0; if (done && now - ref > 90 * DAY) fs.rmSync(p, { force: true }); } catch (e) { /* битый файл */ }
      }
    } catch (e) { /* нет приглашений */ }
    try { const st = fs.statSync('/files/errors.log'); if (st.size > 5 * 1048576) fs.writeFileSync('/files/errors.log', fs.readFileSync('/files/errors.log', 'utf8').slice(-1048576)); } catch (e) { /* нет журнала */ }
    writeJson(HK, { at: now });
  }
  // Пульс для внешнего мониторинга (например healthchecks.io): если ПК, Docker или n8n остановятся, сервис пришлёт оповещение.
  const hb = String($env.HEARTBEAT_URL || '').trim();
  if (/^https?:\/\//.test(hb)) {
    await new Promise(resolve => {
      try { const rq = (hb.startsWith('https') ? require('https') : require('http')).get(hb, res => { res.resume(); res.on('end', resolve); }); rq.on('error', resolve); rq.setTimeout(5000, () => { rq.destroy(); resolve(); }); }
      catch (e) { resolve(); }
    });
  }
  return emit.map(e => ({ json: e }));
} finally { try { fs.rmSync(LOCK, { recursive: true, force: true }); } catch (e) { /* ok */ } }"""

PICK07 = r"""// Подготовка слота: берём следующее видео из папки ЭТОГО аккаунта и копируем в рабочую папку слота.
const fs = require('fs');
const path = require('path');
const EXT = /\.(mp4|mov|m4v)$/i;
const slotId = $input.first().json.slot.id;
const SF = '/files/plan/' + slotId + '.json';
const slot = JSON.parse(fs.readFileSync(SF, 'utf8'));
const saveSlot = () => { slot.updated = Date.now(); const t = SF + '.tmp'; fs.writeFileSync(t, JSON.stringify(slot)); fs.renameSync(t, SF); };
const natural = (x, y) => String(x).localeCompare(String(y), 'ru', { numeric: true });
// видео, уже занятые другими слотами этого аккаунта
const reserved = new Set();
for (const f of fs.readdirSync('/files/plan')) {
  if (!f.endsWith('.json') || f[0] === '.') continue;
  try { const s = JSON.parse(fs.readFileSync('/files/plan/' + f, 'utf8')); if (s.id !== slot.id && s.video && ['preparing', 'prepared', 'publishing'].includes(s.state)) reserved.add(s.video.orig); } catch (e) { /* битый файл */ }
}
const found = [];
const walk = (dir, rel) => {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, rel ? rel + '/' + e.name : e.name);
    else if (EXT.test(e.name) && !reserved.has(p)) found.push({ file: e.name, rel, orig: p });
  }
};
const acctDir = '/files/inbox/' + slot.account;
if (fs.existsSync(acctDir)) walk(acctDir, '');
found.sort((a, b) => natural(a.rel + '/' + a.file, b.rel + '/' + b.file));
let pick = null;
for (const f of found) {
  const s1 = fs.statSync(f.orig).size;
  await new Promise(r => setTimeout(r, 2000));
  if (fs.existsSync(f.orig) && fs.statSync(f.orig).size === s1 && s1 > 0) { pick = f; break; }
}
if (!pick) { slot.state = 'skipped'; slot.reason = 'no videos in stock'; saveSlot(); return []; }
const dirOrig = path.dirname(pick.orig);
let txt = pick.orig.replace(EXT, '.txt');
if (!fs.existsSync(txt)) {
  const txts = fs.readdirSync(dirOrig).filter(n => /\.txt$/i.test(n));
  const videosHere = found.filter(f => path.dirname(f.orig) === dirOrig).length;
  txt = (txts.length === 1 && videosHere === 1) ? path.join(dirOrig, txts[0]) : '';
}
const dir = '/files/prepared/' + slot.id;
fs.mkdirSync(dir, { recursive: true });
const ext = path.extname(pick.file).toLowerCase();
const src = path.join(dir, 'src' + ext);
fs.copyFileSync(pick.orig, src);
const hint = (txt && fs.existsSync(txt)) ? fs.readFileSync(txt, 'utf8').trim() : '';
slot.video = { orig: pick.orig, rel: pick.rel, file: pick.file, hintOrig: txt || '' };
saveSlot();
return [{ json: { rid: slot.id, account: slot.account, file: pick.file, rel: pick.rel, ext, src, dir, orig: pick.orig, hint, hintOrig: txt || '', remaining: 0, n: 0 } }];"""

FINISH07 = r"""const fs = require('fs');
const r = $('Pick next').first().json;
const ai = $('AI copy').first().json;
let music = '';
try { music = String($('Add music').first().json.stdout || '').trim().split('\n').pop().replace(/^MUSIC /, ''); } catch (e) { music = ''; }
const SF = '/files/plan/' + r.rid + '.json';
const slot = JSON.parse(fs.readFileSync(SF, 'utf8'));
slot.meta = { hook: ai.copy.hook, caption: ai.copy.caption, hashtags: ai.copy.hashtags, music, ai_used: ai.ai_used, ai_error: ai.ai_error };
slot.state = 'prepared'; slot.updated = Date.now();
const t = SF + '.tmp'; fs.writeFileSync(t, JSON.stringify(slot)); fs.renameSync(t, SF);
fs.writeFileSync(r.dir + '/meta.json', JSON.stringify(slot.meta));
// копия исходника и кадры больше не нужны: освобождаем место
fs.rmSync(r.src, { force: true });
fs.rmSync(r.dir + '/frames', { recursive: true, force: true });
return [{ json: { id: r.rid, state: 'prepared' } }];"""

FAIL07 = r"""const fs = require('fs');
const slotId = $('When called').first().json.slot.id;
const SF = '/files/plan/' + slotId + '.json';
let slot; try { slot = JSON.parse(fs.readFileSync(SF, 'utf8')); } catch (e) { return []; }
if (slot.state !== 'preparing') return [];
const e = $json.error;
const msg = String(typeof e === 'string' ? e : (e && e.message) || JSON.stringify($json)).slice(0, 300);
slot.attempts = (slot.attempts || 0) + 1;
slot.error = msg; slot.state = slot.attempts >= 2 ? 'failed' : 'planned'; slot.updated = Date.now();
const t = SF + '.tmp'; fs.writeFileSync(t, JSON.stringify(slot)); fs.renameSync(t, SF);
try { fs.rmSync('/files/prepared/' + slotId, { recursive: true, force: true }); } catch (err) { /* нет папки */ }
if (slot.state === 'failed') fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: slotId, account: slot.account, file: (slot.video || {}).file || '', rel: (slot.video || {}).rel || '', status: 'Error', error: 'preparation failed: ' + msg }) + '\n');
return [];"""

PICK08 = r"""// Публикация слота: загружаем данные слота и подготовленного видео в том же виде, что в воркфлоу 04.
const fs = require('fs');
const slotId = $input.first().json.slot.id;
const slot = JSON.parse(fs.readFileSync('/files/plan/' + slotId + '.json', 'utf8'));
const dir = '/files/prepared/' + slotId;
if (!fs.existsSync(dir + '/out/src_v1.mp4')) throw new Error('Prepared video not found for slot ' + slotId);
const v = slot.video || {};
return [{ json: { rid: slotId, account: slot.account, file: v.file || '', rel: v.rel || '', ext: '.mp4', src: '', dir, orig: v.orig || '', hint: '', hintOrig: v.hintOrig || '', remaining: 0, n: 0 } }];"""

AICOPY08 = r"""const fs = require('fs');
const r = $('Pick next').first().json;
const meta = JSON.parse(fs.readFileSync(r.dir + '/meta.json', 'utf8'));
return [{ json: { copy: { hook: meta.hook || '', caption: meta.caption || '', hashtags: meta.hashtags || [] }, ai_used: !!meta.ai_used, ai_error: meta.ai_error || '' } }];"""

ARCH = r"""const EXT = /\.(mp4|mov|m4v)$/i;
const stamp = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
const base = r.file.replace(/\.[^.]+$/, '');
const uniq = (p) => (fs.existsSync(p) ? p + '_' + stamp : p);
// Переносит папку ролика целиком (со всем содержимым) в архив. Если в папке несколько видео,
// переносится только это видео и его текст, остальные остаются в очереди.
const archive = (destRoot) => {
  fs.mkdirSync(destRoot, { recursive: true });
  const folderDir = path.dirname(r.orig);
  const videosHere = fs.readdirSync(folderDir).filter(x => EXT.test(x)).length;
  if (r.rel !== '' && videosHere === 1) {
    const target = uniq(path.join(destRoot, path.basename(folderDir)));
    fs.renameSync(folderDir, target);
    return target;
  }
  const target = r.rel !== '' ? path.join(destRoot, path.basename(folderDir)) : path.join(destRoot, stamp + '_' + base);
  fs.mkdirSync(target, { recursive: true });
  fs.renameSync(r.orig, uniq(path.join(target, r.file)));
  if (r.hintOrig && fs.existsSync(r.hintOrig)) fs.renameSync(r.hintOrig, uniq(path.join(target, path.basename(r.hintOrig))));
  return target;
};
const writeSlot = (s) => { s.updated = Date.now(); const f = '/files/plan/' + s.id + '.json', t = f + '.tmp'; fs.writeFileSync(t, JSON.stringify(s)); fs.renameSync(t, f); };"""

FINISH08 = r"""const fs = require('fs');
const path = require('path');
const r = $('Pick next').first().json;
const u = $input.first().json;
const ai = $('AI copy').first().json;
const slot = JSON.parse(fs.readFileSync('/files/plan/' + r.rid + '.json', 'utf8'));
""" + ARCH + r"""
const st = u.tiktok_status === 'PUBLISH_COMPLETE' ? 'Posted' : (u.tiktok_status === 'DRY_RUN' ? 'DryRun' : 'Check');
const music = (slot.meta && slot.meta.music) || '';
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: r.rid, account: r.account, file: r.file, rel: r.rel, status: st,
  hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, ai_used: ai.ai_used, ai_error: ai.ai_error, music, slot: r.rid }) + '\n');
try {
  if (st !== 'DryRun') {
    const target = archive(path.join('/files/done', r.account));
    const finalVideo = r.dir + '/out/src_v1.mp4';
    if (fs.existsSync(finalVideo)) fs.copyFileSync(finalVideo, uniq(path.join(target, base + '_published.mp4')));
    fs.writeFileSync(uniq(path.join(target, base + '_post.json')), JSON.stringify({ posted_at: new Date().toISOString(), account: r.account, source: r.file,
      hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, music, slot: r.rid }, null, 2));
  }
} catch (e) { slot.archive_error = String(e.message).slice(0, 200); }
fs.rmSync(r.dir, { recursive: true, force: true });
slot.state = 'done'; slot.result = st; slot.published_at = new Date().toISOString(); writeSlot(slot);
try { fs.unlinkSync('/files/state/errors/' + r.account + '.json'); } catch (e) { /* счётчика не было */ }
return [{ json: { status: st } }];"""

FAIL08 = r"""const fs = require('fs');
const path = require('path');
const slotId = $('When called').first().json.slot.id;
let r = null; try { r = $('Pick next').first().json; } catch (e) { r = null; }
let slot; try { slot = JSON.parse(fs.readFileSync('/files/plan/' + slotId + '.json', 'utf8')); } catch (e) { return []; }
if (slot.state !== 'publishing') return [];
""" + ARCH.replace("const base = r.file.replace(/\\.[^.]+$/, '');", "const base = ((r && r.file) || 'video').replace(/\\.[^.]+$/, '');") + r"""
const e = $json.error;
const msg = String(typeof e === 'string' ? e : (e && e.message) || JSON.stringify($json)).slice(0, 400);
// Проблема аккаунта или приложения: исходники остаются в очереди, аккаунт ставится на паузу.
const systemic = /not connected|Refresh token expired|allowed for this account|unaudited_client|invalid_client|access_token_invalid|scope_not_authorized/i.test(msg);
// Дневные лимиты TikTok: пауза аккаунта на несколько часов, без повторных попыток.
const daily = !systemic && /spam_risk|too_many_posts|reached_active_user_cap|daily_post|rate_limit/i.test(msg);
fs.mkdirSync('/files/state/paused', { recursive: true }); fs.mkdirSync('/files/state/errors', { recursive: true });
const pauseFile = '/files/state/paused/' + slot.account + '.json';
const pause = (reason, until) => fs.writeFileSync(pauseFile, JSON.stringify(Object.assign({ reason, at: new Date().toISOString() }, until ? { until } : {})));
let sch = {}; try { sch = JSON.parse(fs.readFileSync('/files/schedule.json', 'utf8')); } catch (er) { sch = {}; }
const limit = Number(((sch.global || {}).pause_after_errors)) || 3;
if (systemic) pause(msg);
else if (daily) pause('TikTok daily limit: ' + msg, new Date(Date.now() + 6 * 3600000).toISOString());
else {
  const ef = '/files/state/errors/' + slot.account + '.json'; let c = 0; try { c = JSON.parse(fs.readFileSync(ef, 'utf8')).count || 0; } catch (er) { c = 0; }
  c++; fs.writeFileSync(ef, JSON.stringify({ count: c, at: new Date().toISOString() }));
  if (c >= limit) pause(c + ' errors in a row. Last: ' + msg);
}
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: slotId, account: slot.account, file: (r && r.file) || '', rel: (r && r.rel) || '', status: 'Error', error: msg, kept: systemic || daily, slot: slotId }) + '\n');
try {
  if (r && !systemic && !daily && r.orig && fs.existsSync(r.orig)) {
    const target = archive(path.join('/files/failed', r.account));
    fs.writeFileSync(uniq(path.join(target, base + '_error.txt')), msg + '\n');
  }
} catch (er) { /* не критично */ }
try { fs.rmSync('/files/prepared/' + slotId, { recursive: true, force: true }); } catch (er) { /* нет папки */ }
slot.state = 'failed'; slot.error = msg; writeSlot(slot);
return [{ json: { error: msg, systemic: systemic || daily, file: (r && r.file) || '', account: slot.account } }];"""


sys.path.insert(0, TOOLS)
import blocks
PICK07 = blocks.PICK07
PICK08 = blocks.PICK08
FINISH08 = blocks.FINISH08
FAIL08 = blocks.FAIL08

def build(bound):
    src = json.load(open(ROOT + ("infra/files/workflows/" if bound else "workflows/") + "04_publish_from_folder.json", encoding="utf-8"))
    def node(name):
        return copy.deepcopy([n for n in src["nodes"] if n["name"] == name][0])
    dt = {"__rl": True, "mode": "id", "value": "SSWsIdTjYaqpXDiV"} if bound else {"__rl": True, "mode": "name", "value": "tiktok_accounts"}
    def code(i, name, js, x, y, **extra):
        n = {"id": "c00000%s-0000-4000-8000-0000000000%02x" % (i[0], i[1]), "name": name, "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [x, y], "parameters": {"jsCode": js}}
        n.update(extra); return n
    def reid(n, i):
        n["id"] = "c00000%s-0000-4000-8000-0000000000%02x" % (i[0], i[1]); return n
    c = lambda *ns: {"main": [[{"node": n, "type": "main", "index": 0} for n in ns]]}
    nd = lambda n: [{"node": n, "type": "main", "index": 0}]

    # ---------- 06 Scheduler tick ----------
    n06 = [
        {"id": "c0000006-0000-4000-8000-000000000001", "name": "Tick (every minute)", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 0],
         "parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}}},
        {"id": "c0000006-0000-4000-8000-000000000002", "name": "Manual start", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "position": [0, 160], "parameters": {}},
        {"id": "c0000006-0000-4000-8000-000000000003", "name": "When called", "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1, "position": [0, 320], "parameters": {"inputSource": "passthrough"}},
        {"id": "c0000006-0000-4000-8000-000000000004", "name": "Accounts", "type": "n8n-nodes-base.dataTable", "typeVersion": 1, "position": [240, 160],
         "parameters": {"operation": "get", "dataTableId": dt, "returnAll": True}, "alwaysOutputData": True},
        code((6, 5), "Plan and dispatch", PLANNER, 480, 160),
        {"id": "c0000006-0000-4000-8000-000000000006", "name": "Is prepare?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [720, 160],
         "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
             {"id": "k1", "operator": {"type": "string", "operation": "equals"}, "leftValue": "={{ $json.kind }}", "rightValue": "prepare"}]}, "options": {}}},
        {"id": "c0000006-0000-4000-8000-000000000007", "name": "Run prepare", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2, "position": [960, 80],
         "parameters": {"source": "database", "workflowId": {"__rl": True, "mode": "id", "value": ID07},
                        "workflowInputs": {"mappingMode": "defineBelow", "value": {}, "matchingColumns": [], "schema": [], "attemptToConvertTypes": False, "convertFieldsToString": True},
                        "mode": "each", "options": {"waitForSubWorkflow": False}}},
        {"id": "c0000006-0000-4000-8000-000000000008", "name": "Run publish", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2, "position": [960, 240],
         "parameters": {"source": "database", "workflowId": {"__rl": True, "mode": "id", "value": ID08},
                        "workflowInputs": {"mappingMode": "defineBelow", "value": {}, "matchingColumns": [], "schema": [], "attemptToConvertTypes": False, "convertFieldsToString": True},
                        "mode": "each", "options": {"waitForSubWorkflow": False}}},
    ]
    c06 = {"Tick (every minute)": c("Accounts"), "Manual start": c("Accounts"), "When called": c("Accounts"), "Accounts": c("Plan and dispatch"),
           "Plan and dispatch": c("Is prepare?"), "Is prepare?": {"main": [nd("Run prepare"), nd("Run publish")]}}
    w06 = {"id": ID06, "name": "06 Scheduler tick", "active": False, "settings": {"executionOrder": "v1", "executionTimeout": 300}, "pinData": {}, "nodes": n06, "connections": c06}

    # ---------- 07 Prepare slot ----------
    n07 = [
        {"id": "c0000007-0000-4000-8000-000000000001", "name": "When called", "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1, "position": [0, 0], "parameters": {"inputSource": "passthrough"}},
        code((7, 2), "Pick next", PICK07, 240, 0, onError="continueErrorOutput"),
        reid(node("Extract frames"), (7, 3)), reid(node("AI copy"), (7, 4)), reid(node("ffmpeg variant"), (7, 5)), reid(node("Add music"), (7, 6)),
        code((7, 7), "Finish prepare", FINISH07, 1440, 0),
        code((7, 8), "Fail prepare", FAIL07, 720, 240),
    ]
    for i, n in enumerate(n07):
        n["position"] = [i * 240 if n["name"] != "Fail prepare" else 720, 0 if n["name"] != "Fail prepare" else 240]
    fail07 = nd("Fail prepare")
    c07 = {"When called": c("Pick next"), "Pick next": {"main": [nd("Extract frames"), fail07]}, "Extract frames": {"main": [nd("AI copy"), fail07]}, "AI copy": {"main": [nd("ffmpeg variant"), fail07]},
           "ffmpeg variant": {"main": [nd("Add music"), fail07]}, "Add music": {"main": [nd("Finish prepare"), fail07]}}
    w07 = {"id": ID07, "name": "07 Prepare slot", "active": False, "settings": {"executionOrder": "v1", "executionTimeout": 1800}, "pinData": {}, "nodes": n07, "connections": c07}

    # ---------- 08 Publish slot ----------
    tg = reid(node("Telegram alert"), (8, 0xb))
    tg["parameters"]["text"] = "={{ 'TikTok scheduler: error for ' + $json.account + ' (' + $json.file + '): ' + $json.error + ($json.systemic ? ' [account paused]' : '') }}"
    n08 = [
        {"id": "c0000008-0000-4000-8000-000000000001", "name": "When called", "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1, "position": [0, 0], "parameters": {"inputSource": "passthrough"}},
        code((8, 2), "Pick next", PICK08, 240, 0, onError="continueErrorOutput"),
        reid(node("Config"), (8, 3)), code((8, 4), "AI copy", AICOPY08, 720, 0),
        reid(node("Get tokens"), (8, 5)), reid(node("Token logic"), (8, 6)), reid(node("Save tokens"), (8, 7)), reid(node("Upload to TikTok"), (8, 8)),
        code((8, 9), "Finish", FINISH08, 1920, 0), code((8, 10), "Fail", FAIL08, 1200, 240), tg,
    ]
    for i, n in enumerate(n08):
        n["position"] = [i * 240 if n["name"] not in ("Fail", "Telegram alert") else (1200 if n["name"] == "Fail" else 1440), 0 if n["name"] not in ("Fail", "Telegram alert") else 240]
    f08 = nd("Fail")
    c08 = {"When called": c("Pick next"), "Pick next": {"main": [nd("Config"), f08]}, "Config": {"main": [nd("AI copy"), f08]}, "AI copy": c("Get tokens"),
           "Get tokens": {"main": [nd("Token logic"), f08]}, "Token logic": {"main": [nd("Save tokens"), f08]}, "Save tokens": {"main": [nd("Upload to TikTok"), f08]},
           "Upload to TikTok": {"main": [nd("Finish"), f08]}, "Fail": c("Telegram alert")}
    w08 = {"id": ID08, "name": "08 Publish slot", "active": False, "settings": {"executionOrder": "v1", "executionTimeout": 1800}, "pinData": {}, "nodes": n08, "connections": c08}
    return w06, w07, w08


for bound in (False, True):
    w06, w07, w08 = build(bound)
    base = ROOT + ("infra/files/workflows/" if bound else "workflows/")
    for name, w in (("06_scheduler_tick.json", w06), ("07_prepare_slot.json", w07), ("08_publish_slot.json", w08)):
        json.dump(w, open(base + name, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("ok", [len(w["nodes"]) for w in build(True)])
