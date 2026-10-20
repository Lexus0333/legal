import json

import os
TOOLS = os.path.dirname(os.path.abspath(__file__)).replace(chr(92), "/") + "/"
ROOT = os.path.dirname(TOOLS.rstrip("/")).replace(chr(92), "/") + "/"
ORIGIN = "https://lexus0333.github.io"
CORS = {"responseHeaders": {"entries": [{"name": "Access-Control-Allow-Origin", "value": ORIGIN}]}}

HANDLE = r"""// API панели. Рассчитано на ~1000 аккаунтов: постраничная выдача, поиск, фильтры, кэш статистики, массовые операции.
const fs = require('fs');
const path = require('path');
const EXT = /\.(mp4|mov|m4v)$/i;
const AUD = /\.(mp3|m4a|wav|ogg|aac|flac)$/i;
const NAME = /^[a-z0-9_-]{1,40}$/;
const RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/;
const normName = s => String(s == null ? '' : s).trim().toLowerCase();
const validName = s => NAME.test(s) && !RESERVED.test(s);
const TYPES = ['hooks', 'captions', 'hashtags'];
const LIMITS = { hooks: 120, captions: 300, hashtags: 60 };
const EMOJI = /[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\uFE0F\u200D]/gu;
const MAX_BULK = 1000;

let isPost = false;
try { isPost = $('Panel POST').isExecuted; } catch (e) { isPost = false; }
const req = isPost ? $('Panel POST').first().json : $('Panel GET').first().json;
const b = req.body || {};
const p = isPost ? b : (req.query || {});
const out = (body, status) => [{ json: { _status: status || 200, body } }];
const logErr = (w, e) => { try { fs.appendFileSync('/files/errors.log', new Date().toISOString() + ' [panel] ' + w + ': ' + String((e && e.message) || e).slice(0, 300) + '\n'); } catch (x) { /* журнал недоступен */ } };
const authCheck = (headers) => {
  const crypto = require('crypto');
  const fs = require('fs');
  const a = String((headers || {}).authorization || '');
  const given = a.startsWith('Bearer ') ? a.slice(7).trim() : '';
  const sha = s => crypto.createHash('sha256').update(String(s)).digest();
  // Адрес клиента: самый правый непубличный адрес из X-Forwarded-For (подмена слева не помогает).
  const PRIV = /^(10\.|127\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|fc|fd|fe80)/i;
  const ip = String((headers || {})['x-forwarded-for'] || (headers || {})['x-real-ip'] || 'unknown').split(',').map(s => s.trim()).filter(Boolean).reverse().find(x => !PRIV.test(x)) || 'unknown';
  const dir = '/files/state/auth_fail';
  fs.mkdirSync(dir, { recursive: true });
  const ff = dir + '/' + crypto.createHash('sha1').update(ip).digest('hex') + '.json';
  let st = {}; try { st = JSON.parse(fs.readFileSync(ff, 'utf8')); } catch (e) { st = {}; }
  const ts = Date.now();
  if (st.blocked_until && st.blocked_until > ts) return { ok: false, status: 429 };
  const secret = String($env.CONNECT_SECRET || '');
  const good = !!given && !!secret && crypto.timingSafeEqual(sha(given), sha(secret));
  if (good) { if (st.count) { try { fs.unlinkSync(ff); } catch (e) { /* уже нет */ } } return { ok: true, status: 200 }; }
  if (!st.first_at || ts - st.first_at > 10 * 60000) st = { count: 0, first_at: ts };
  st.count++;
  if (st.count >= 10) st.blocked_until = ts + 15 * 60000;
  fs.writeFileSync(ff, JSON.stringify(st));
  return { ok: false, status: 403 };
};
const authRes = authCheck(req.headers || {});
if (!authRes.ok) return out({ error: authRes.status === 429 ? 'Too many attempts. Try again in 15 minutes.' : 'forbidden' }, authRes.status);
const action = String(p.action || '');
// Все изменения состояния выполняются по одному (общая блокировка), иначе параллельные запросы затирают друг друга.
const LOCKD = '/files/state/locks/panel_write';
let __locked = false;
if (isPost) {
  fs.mkdirSync('/files/state/locks', { recursive: true });
  const t0 = Date.now();
  while (!__locked && Date.now() - t0 < 8000) {
    try { fs.mkdirSync(LOCKD); __locked = true; }
    catch (e) { try { if (Date.now() - fs.statSync(LOCKD).mtimeMs > 30000) fs.rmSync(LOCKD, { recursive: true, force: true }); } catch (x) { /* ok */ } }
    if (!__locked) { const end = Date.now() + 40; while (Date.now() < end) { /* короткое ожидание */ } }
  }
  if (!__locked) return out({ error: 'The server is busy. Try again in a moment.' }, 503);
}
const __release = () => { if (__locked) { try { fs.rmSync(LOCKD, { recursive: true, force: true }); } catch (e) { /* ok */ } } };
const __run = () => {
const lang = $env.POOL_LANG || 'en';
const natural = (x, y) => String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: 'base' });
const intOr = (v, d, lo, hi) => { const n = parseInt(v, 10); return isNaN(n) ? d : Math.min(hi, Math.max(lo, n)); };

// ---------- хранилище ----------
const readLines = f => { try { return fs.readFileSync(f, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(Boolean); } catch (e) { return null; } };
const poolFile = (account, type) => '/files/pools/' + (account || lang) + '/' + type + '.txt';
const effective = (account, type) => {
  if (account) { const own = readLines(poolFile(account, type)); if (own !== null) return { items: own, own: true }; }
  return { items: readLines(poolFile('', type)) || [], own: false };
};
const ACC_FILE = '/files/accounts.json';
const safeParse = f => { try { return { ok: true, data: JSON.parse(fs.readFileSync(f, 'utf8')) }; } catch (e) { return { ok: false, missing: e.code === 'ENOENT' }; } };
// Запись: прежняя исправная версия сохраняется как .bak, сама запись атомарная.
const writeSafe = (f, obj) => {
  if (safeParse(f).ok) { try { fs.copyFileSync(f, f + '.bak'); } catch (e) { logErr('backup ' + f, e); } }
  const tmp = f + '.tmp'; fs.writeFileSync(tmp, JSON.stringify(obj)); fs.renameSync(tmp, f);
};
// Чтение: повреждённый файл восстанавливается из .bak, а если и копии нет, работа останавливается с понятной ошибкой (файл не затирается).
const readRecover = (f, label) => {
  const r = safeParse(f);
  if (r.ok) return r.data;
  if (r.missing) return null;
  const bk = safeParse(f + '.bak');
  if (bk.ok) { try { fs.copyFileSync(f, f + '.corrupt-' + Date.now()); } catch (e) { /* ok */ } fs.writeFileSync(f, JSON.stringify(bk.data)); logErr(label + ' was damaged and restored from the backup copy', 'restored'); return bk.data; }
  throw new Error(label + ' is damaged and there is no valid backup copy. Restore it from your backup before making changes.');
};
const saveAccounts = m => writeSafe(ACC_FILE, m);
const loadAccounts = () => {
  const cur = readRecover(ACC_FILE, 'accounts.json');
  if (cur) return cur;
  // первый запуск: переносим старые файлы настроек
  const m = {};
  try {
    for (const f of fs.readdirSync('/files/accounts')) {
      if (f.endsWith('.json')) { try { m[f.slice(0, -5).toLowerCase()] = JSON.parse(fs.readFileSync('/files/accounts/' + f, 'utf8')); } catch (e) { /* битый файл */ } }
    }
  } catch (e) { /* старых файлов нет */ }
  if (Object.keys(m).length) saveAccounts(m);
  return m;
};

// ---------- кэш: статистика журнала считается инкрементально, запас видео обновляется раз в 30 секунд ----------
const CACHE = '/files/panel_cache.json';
const LOG = '/files/posts.jsonl';
let cache = {};
try { cache = JSON.parse(fs.readFileSync(CACHE, 'utf8')); } catch (e) { cache = {}; }
let dirtyCache = false;
const logSize = (() => { try { return fs.statSync(LOG).size; } catch (e) { return 0; } })();
if (!cache.agg || (cache.offset || 0) > logSize) { cache.agg = {}; cache.offset = 0; dirtyCache = true; }
if (logSize > cache.offset) {
  const len = logSize - cache.offset, buf = Buffer.alloc(len), fd = fs.openSync(LOG, 'r');
  fs.readSync(fd, buf, 0, len, cache.offset); fs.closeSync(fd);
  const text = buf.toString('utf8'), cut = text.lastIndexOf('\n');
  const chunk = cut >= 0 ? text.slice(0, cut + 1) : '';
  cache.offset += Buffer.byteLength(chunk);
  for (const line of chunk.split('\n')) {
    if (!line.trim()) continue;
    let o; try { o = JSON.parse(line); } catch (e) { continue; }
    if (!o.account) continue;
    const a = cache.agg[o.account] || (cache.agg[o.account] = { posted: 0, failed: 0, first: '', last: '', recent: [] });
    if (o.status === 'Posted' || o.status === 'Check') {
      a.posted++; if (!a.first || o.at < a.first) a.first = o.at; if (!a.last || o.at > a.last) a.last = o.at;
      a.recent.push(o.at); if (a.recent.length > 300) a.recent = a.recent.slice(-300);
    } else if (o.status === 'Error' && !o.kept) a.failed++;
  }
  dirtyCache = true;
}
const now = Date.now(), DAY = 86400000;
if (!cache.stock || now - cache.stock.at > 30000) {
  const by = {};
  const walk = (dir, account) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const f = path.join(dir, e.name);
      if (e.isDirectory()) walk(f, account || e.name.toLowerCase());
      else if (EXT.test(e.name)) { const a = account || String($env.DEFAULT_ACCOUNT || 'account1').toLowerCase(); by[a] = (by[a] || 0) + 1; }
    }
  };
  try { if (fs.existsSync('/files/inbox')) walk('/files/inbox', ''); } catch (e) { /* нет inbox */ }
  cache.stock = { at: now, by }; dirtyCache = true;
}
const flushCache = () => { if (dirtyCache) { try { const t = CACHE + '.tmp'; fs.writeFileSync(t, JSON.stringify(cache)); fs.renameSync(t, CACHE); } catch (e) { /* не критично */ } } };

const tableRows = () => { const t = {}; for (const i of $('Accounts').all()) { const r = i.json; if (r && r.account) t[String(r.account).toLowerCase()] = r; } return t; };
let stats = {};
try { stats = JSON.parse(fs.readFileSync('/files/stats.json', 'utf8')); } catch (e) { stats = {}; }
const statsOn = $env.STATS_ENABLED === '1';

// ---------- расписание: настройки и сводка ----------
const SCHED_FILE = '/files/schedule.json';
const defaultSched = () => ({
  global: { paused: true, catchup_hours: 6, max_parallel: 2, max_prepare: 2, prepare_ahead_hours: 12, pause_after_errors: 3 },
  default_profile: 'default',
  profiles: { default: { posts_per_day: 2, windows: [['10:00', '22:00']], min_gap_min: 120, days: [1, 2, 3, 4, 5, 6, 7], tz: $env.TZ || 'UTC', ramp: null, enabled: true } },
  group_profile: {}, overrides: {},
});
const loadSched = () => {
  const s = readRecover(SCHED_FILE, 'schedule.json');
  const d = defaultSched(); if (!s) return d;
  s.global = Object.assign({}, d.global, s.global || {});
  s.profiles = (s.profiles && Object.keys(s.profiles).length) ? s.profiles : d.profiles;
  s.default_profile = s.profiles[s.default_profile] ? s.default_profile : Object.keys(s.profiles)[0];
  s.group_profile = s.group_profile || {}; s.overrides = s.overrides || {};
  return s;
};
const saveSched = s => writeSafe(SCHED_FILE, s);
let planSummary = null; try { planSummary = JSON.parse(fs.readFileSync('/files/plan_summary.json', 'utf8')); } catch (e) { planSummary = null; }
const pausedMap = {};
try {
  for (const f of fs.readdirSync('/files/state/paused')) {
    if (!f.endsWith('.json')) continue;
    try { const x = JSON.parse(fs.readFileSync('/files/state/paused/' + f, 'utf8')); if (x.until && Date.parse(x.until) < Date.now()) continue; pausedMap[f.slice(0, -5)] = Object.assign({ account: f.slice(0, -5) }, x); } catch (e) { /* битый файл */ }
  }
} catch (e) { /* папки ещё нет */ }
const schedByAccount = (planSummary && planSummary.by_account) || {};
const schedOverrides = (() => { try { return JSON.parse(fs.readFileSync(SCHED_FILE, 'utf8')).overrides || {}; } catch (e) { return {}; } })();

// ---------- приглашения владельцам аккаунтов ----------
const crypto = require('crypto');
const INV_DIR = '/files/invites';
const baseUrl = () => String($env.WEBHOOK_URL || ('https://' + $env.N8N_HOST + '/')).replace(/\/?$/, '/');
const invLink = tk => baseUrl() + 'webhook/tiktok-invite?t=' + tk;
const invStatus = i => i.status === 'revoked' ? 'revoked' : (i.used_at ? 'connected' : (Date.parse(i.expires_at) < Date.now() ? 'expired' : (i.opened_at ? 'opened' : 'pending')));
const writeInv = i => { fs.mkdirSync(INV_DIR, { recursive: true }); const f = INV_DIR + '/' + i.token + '.json', tmp = f + '.tmp'; fs.writeFileSync(tmp, JSON.stringify(i)); fs.renameSync(tmp, f); };
let _inv = null, _invMap = null;
const loadInvites = () => {
  if (_inv) return _inv;
  _inv = [];
  try { for (const f of fs.readdirSync(INV_DIR)) { if (!f.endsWith('.json')) continue; try { const i = JSON.parse(fs.readFileSync(INV_DIR + '/' + f, 'utf8')); if (i.token && i.account) _inv.push(i); } catch (e) { /* битый файл */ } } } catch (e) { /* папки ещё нет */ }
  return _inv;
};
const inviteMap = () => {
  if (_invMap) return _invMap;
  _invMap = {};
  for (const i of loadInvites().sort((x, y) => String(x.created_at).localeCompare(String(y.created_at)))) _invMap[i.account] = i;
  return _invMap;
};

// ---------- строка аккаунта ----------
const identOf = a => { try { return JSON.parse(fs.readFileSync('/files/identity/' + a + '.json', 'utf8')); } catch (e) { return {}; } };
const buildRow = (a, table, cfgs) => {
  const row = table[a] || {}, cfg = cfgs[a] || {}, g = cache.agg[a] || {};
  const connected = !!row.refresh_token;
  const refreshAt = Number(row.refresh_expires_at) || null;
  const stock = cache.stock.by[a] || 0;
  const published7 = (g.recent || []).filter(t => now - Date.parse(t) < 7 * DAY).length;
  const failed = g.failed || 0;
  const isPaused = !!pausedMap[a] || !!(schedOverrides[a] || {}).paused;
  const flags = [];
  if (isPaused) flags.push('paused');
  if (!connected && stock > 0) flags.push('not_connected_stock');
  if (connected && refreshAt) { const days = (refreshAt - now) / DAY; if (days < 0) flags.push('refresh_expired'); else if (days < 30) flags.push('refresh_soon'); }
  if (connected && stock === 0) flags.push('no_stock'); else if (connected && stock < 5) flags.push('low_stock');
  if (failed > 0) flags.push('failed');
  return {
    account: a, group: cfg.group || '', connected, access_valid: Number(row.access_expires_at) > now, refresh_expires_at: refreshAt,
    created_at: cfg.created_at || '', connected_at: row.createdAt || '', token_refreshed_at: row.updatedAt || '',
    first_post_at: g.first || '', last_post_at: g.last || '', stock, published: g.posted || 0, published_7d: published7, failed,
    bio_link: cfg.bio_link || '', bio_link_set: !!cfg.bio_link_set, aigc: cfg.aigc !== false, nick: connected ? String(identOf(a).display_name || '') : '', flags,
    next_post_at: (schedByAccount[a] || {}).next_at || '', next_state: (schedByAccount[a] || {}).next_state || '',
    paused: isPaused, paused_reason: (pausedMap[a] || {}).reason || '',
    override: schedOverrides[a] || null,
    invite: (() => { const iv = inviteMap()[a]; return iv ? { status: invStatus(iv), created_at: iv.created_at, opened_at: iv.opened_at || '', used_at: iv.used_at || '', expires_at: iv.expires_at, note: iv.note || '', token: iv.token } : null; })(),
  };
};
const matchesFilter = (r, f) => {
  switch (f) {
    case 'attention': return r.flags.length > 0;
    case 'not_connected': return !r.connected;
    case 'no_stock': return r.connected && r.stock === 0;
    case 'low_stock': return r.connected && r.stock > 0 && r.stock < 5;
    case 'active': return r.published_7d > 0;
    case 'inactive': return r.connected && r.published_7d === 0;
    case 'failed': return r.failed > 0;
    case 'paused': return r.paused;
    case 'invited': return !!r.invite && (r.invite.status === 'pending' || r.invite.status === 'opened');
    default: return true;
  }
};

if (action === 'overview') {
  const table = tableRows(), cfgs = loadAccounts();
  const names = [...new Set([...Object.keys(table), ...Object.keys(cfgs), ...Object.keys(cache.stock.by), ...Object.keys(cache.agg)])].filter(a => a && !(fs.existsSync('/files/state/removed/' + a) && !cfgs[a] && !(table[a] && table[a].refresh_token) && !(cache.stock.by[a] > 0)));
  const all = names.map(a => buildRow(a, table, cfgs));
  const sum = { total: all.length, paused: 0, invited: 0, connected: 0, not_connected: 0, attention: 0, no_stock: 0, low_stock: 0, active: 0, inactive: 0, failed: 0, stock_total: 0, published_7d: 0, published_total: 0 };
  const groups = {};
  for (const r of all) {
    sum.stock_total += r.stock; sum.published_7d += r.published_7d; sum.published_total += r.published;
    for (const k of ['not_connected', 'attention', 'no_stock', 'low_stock', 'active', 'inactive', 'failed', 'paused', 'invited']) if (matchesFilter(r, k)) sum[k]++;
    if (r.connected) sum.connected++;
    if (r.group) groups[r.group] = (groups[r.group] || 0) + 1;
  }
  const q = String(p.q || '').trim().toLowerCase(), f = String(p.filter || ''), grp = String(p.group || '');
  let rows = all.filter(r => matchesFilter(r, f) && (!grp || (grp === '_none' ? !r.group : r.group === grp)) && (!q || r.account.toLowerCase().includes(q) || r.group.toLowerCase().includes(q)));
  const sort = String(p.sort || 'name'), dir = String(p.dir) === 'desc' ? -1 : 1;
  const key = { name: r => r.account, stock: r => r.stock, published_7d: r => r.published_7d, published: r => r.published, failed: r => r.failed, last_post: r => r.last_post_at || '', created: r => r.created_at || '', group: r => r.group }[sort] || (r => r.account);
  rows.sort((x, y) => { const a = key(x), c = key(y); const d = typeof a === 'number' ? a - c : natural(a, c); return (d || natural(x.account, y.account)) * dir; });
  if (String(p.names_only) === '1') { flushCache(); return out({ names: rows.map(r => r.account).slice(0, MAX_BULK), total: rows.length }); }
  const size = intOr(p.size, 50, 10, 200), pages = Math.max(1, Math.ceil(rows.length / size)), page = intOr(p.page, 1, 1, pages);
  flushCache();
  return out({
    alerts: planSummary ? [].concat(planSummary.errors || [], planSummary.warnings || []).slice(0, 5) : [],
    summary: sum, groups, total_matching: rows.length, page, pages, size, accounts: rows.slice((page - 1) * size, page * size),
    music: (() => { const m = {}; try { for (const e of fs.readdirSync('/files/music', { withFileTypes: true })) if (e.isDirectory()) m[e.name] = fs.readdirSync('/files/music/' + e.name).filter(x => AUD.test(x)).length; } catch (e) { /* нет папки */ } return { mode: $env.MUSIC_MODE || 'silent', moods: m }; })(),
    max_per_run: Number($env.MAX_POSTS_PER_RUN || 5), dry_run: $env.DRY_RUN === '1', stats_enabled: statsOn, pool_lang: lang, server_time: new Date().toISOString(),
  });
}

if (action === 'names') {
  const q = String(p.q || '').trim().toLowerCase();
  const table = tableRows(), cfgs = loadAccounts();
  const names = [...new Set([...Object.keys(table), ...Object.keys(cfgs), ...Object.keys(cache.stock.by)])].filter(n => validName(n) && (!q || n.toLowerCase().includes(q))).sort(natural);
  flushCache();
  return out({ names: names.slice(0, 30), total: names.length });
}

if (action === 'posts') {
  // читаем только хвост журнала (последние ~6 МБ): этого хватает для списка последних публикаций
  const MAXB = 6 * 1024 * 1024, start = Math.max(0, logSize - MAXB);
  let text = '';
  if (logSize) { const len = logSize - start, buf = Buffer.alloc(len), fd = fs.openSync(LOG, 'r'); fs.readSync(fd, buf, 0, len, start); fs.closeSync(fd); text = buf.toString('utf8'); if (start > 0) text = text.slice(text.indexOf('\n') + 1); }
  const byId = new Map();
  for (const line of text.split('\n')) { if (!line.trim()) continue; try { const o = JSON.parse(line); byId.set(o.id, Object.assign({}, byId.get(o.id) || {}, o)); } catch (e) { /* битая строка */ } }
  const fa = normName(p.account), fs2 = String(p.status || ''), q = String(p.q || '').trim().toLowerCase();
  let rows = [...byId.values()].filter(o => o.status && o.status !== 'DryRun' && (!fa || o.account === fa) && (!fs2 || o.status === fs2)
    && (!q || String(o.account).toLowerCase().includes(q) || String(o.file).toLowerCase().includes(q) || String(o.caption || '').toLowerCase().includes(q)));
  rows.sort((x, y) => String(y.at).localeCompare(String(x.at)));
  const size = intOr(p.size, 50, 10, 200), pages = Math.max(1, Math.ceil(rows.length / size)), page = intOr(p.page, 1, 1, pages);
  flushCache();
  return out({
    total: rows.length, page, pages, size, stats_enabled: statsOn,
    posts: rows.slice((page - 1) * size, page * size).map(o => ({
      id: o.id, at: o.at, account: o.account, file: o.file, rel: o.rel || '', status: o.status, hook: o.hook || '', caption: o.caption || '', music: o.music || '',
      publish_id: o.publish_id || '', tiktok_status: o.tiktok_status || '', privacy: o.privacy || '', error: String(o.error || '').slice(0, 200),
      metrics: statsOn && o.publish_id && stats[o.publish_id] ? stats[o.publish_id] : null,
    })),
  });
}

if (action === 'pools') {
  const account = normName(p.account);
  if (account && !validName(account)) return out({ error: 'bad account' }, 400);
  const lists = {};
  for (const t of TYPES) lists[t] = effective(account, t);
  return out({ account, lang, lists });
}

// ---------- запись ----------
const cleanItems = (type, raw) => {
  let items = (Array.isArray(raw) ? raw : []).map(s => String(s).replace(/[\r\n\t]+/g, ' ').trim());
  if (type === 'hashtags') items = items.map(s => s.replace(/^#+/, '').replace(/\s+/g, ''));
  if (type === 'hooks') items = items.map(s => s.replace(EMOJI, '').replace(/\s+/g, ' ').trim());
  const valid = items.filter(s => s && s.length <= LIMITS[type] && (type !== 'hashtags' || /^[\p{L}\p{N}_]+$/u.test(s)));
  const seen = new Set();
  const uniq = valid.filter(s => { const k = s.toLowerCase(); if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 500);
  return { uniq, rejected: items.filter(Boolean).length - uniq.length };
};
const writePool = (account, type, uniq) => {
  const file = poolFile(account, type);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (fs.existsSync(file)) fs.copyFileSync(file, file + '.bak');
  fs.writeFileSync(file, uniq.join('\n') + (uniq.length ? '\n' : ''));
};
const accountList = raw => [...new Set((Array.isArray(raw) ? raw : []).map(normName).filter(Boolean))];

if (action === 'savePools') {
  const account = normName(b.account), type = String(b.type || '');
  if (account && !validName(account)) return out({ error: 'bad account' }, 400);
  if (!TYPES.includes(type)) return out({ error: 'bad type' }, 400);
  const { uniq, rejected } = cleanItems(type, b.items);
  writePool(account, type, uniq);
  return out({ ok: true, saved: uniq.length, rejected });
}

if (action === 'resetPools') {
  const account = normName(b.account), type = String(b.type || '');
  if (!validName(account) || !TYPES.includes(type)) return out({ error: 'bad request' }, 400);
  try { fs.unlinkSync(poolFile(account, type)); } catch (e) { /* уже нет */ }
  return out({ ok: true });
}

if (action === 'copyPools') {
  // копирует списки текстов одного аккаунта (или общие, если from пусто) на выбранные аккаунты
  const from = normName(b.from);
  if (from && !validName(from)) return out({ error: 'bad source account' }, 400);
  const targets = accountList(b.accounts);
  if (!targets.length || targets.length > MAX_BULK) return out({ error: 'Select from 1 to ' + MAX_BULK + ' accounts.' }, 400);
  const types = (Array.isArray(b.types) && b.types.length ? b.types : TYPES).filter(t => TYPES.includes(t));
  let copied = 0, skipped = 0;
  for (const t of targets) {
    if (!validName(t) || t === from) { skipped++; continue; }
    for (const type of types) writePool(t, type, effective(from, type).items);
    copied++;
  }
  return out({ ok: true, copied, skipped });
}

if (action === 'addAccounts') {
  const names = accountList(b.names);
  if (!names.length || names.length > MAX_BULK) return out({ error: 'Provide from 1 to ' + MAX_BULK + ' names.' }, 400);
  const cfgs = loadAccounts(), added = [], existing = [], invalid = [];
  const stamp = new Date().toISOString();
  for (const n of names) {
    if (!validName(n)) { invalid.push(n); continue; }
    if (cfgs[n]) { existing.push(n); continue; }
    cfgs[n] = { created_at: stamp }; if (typeof b.group === 'string' && b.group.trim()) cfgs[n].group = b.group.trim().slice(0, 40);
    try { fs.mkdirSync('/files/inbox/' + n, { recursive: true }); } catch (e) { /* не критично */ }
    added.push(n);
  }
  if (added.length) saveAccounts(cfgs);
  cache.stock = null; dirtyCache = true;
  return out({ ok: added.length > 0 || existing.length > 0, added: added.length, existing: existing.length, invalid: invalid.slice(0, 20), invalid_count: invalid.length });
}

if (action === 'addAccount') {
  const account = normName(b.account);
  if (!validName(account)) return out({ error: 'Use 1-40 letters, digits, "_" or "-" for the account name.' }, 400);
  const cfgs = loadAccounts();
  if (!cfgs[account]) cfgs[account] = { created_at: new Date().toISOString() };
  saveAccounts(cfgs);
  try { fs.mkdirSync('/files/inbox/' + account, { recursive: true }); } catch (e) { /* не критично */ }
  return out({ ok: true });
}

if (action === 'saveAccount') {
  const account = normName(b.account);
  if (!validName(account)) return out({ error: 'bad account' }, 400);
  const cfgs = loadAccounts(), cfg = cfgs[account] || (cfgs[account] = {});
  if (typeof b.bio_link === 'string') {
    const link = b.bio_link.trim();
    if (link && !/^https?:\/\/[^\s]{3,290}$/.test(link)) return out({ error: 'The link must start with http:// or https://' }, 400);
    if (link) cfg.bio_link = link; else delete cfg.bio_link;
  }
  if (typeof b.bio_link_set === 'boolean') cfg.bio_link_set = b.bio_link_set;
  if (typeof b.aigc === 'boolean') cfg.aigc = b.aigc;
  if (typeof b.group === 'string') { const g = b.group.trim().slice(0, 40); if (g) cfg.group = g; else delete cfg.group; }
  if (!cfg.created_at) cfg.created_at = new Date().toISOString();
  saveAccounts(cfgs);
  return out({ ok: true });
}

if (action === 'setGroup') {
  const targets = accountList(b.accounts);
  if (!targets.length || targets.length > MAX_BULK) return out({ error: 'Select from 1 to ' + MAX_BULK + ' accounts.' }, 400);
  const g = String(b.group || '').trim().slice(0, 40);
  const cfgs = loadAccounts(); let n = 0;
  for (const t of targets) {
    if (!validName(t)) continue;
    const cfg = cfgs[t] || (cfgs[t] = { created_at: new Date().toISOString() });
    if (g) cfg.group = g; else delete cfg.group; n++;
  }
  saveAccounts(cfgs);
  return out({ ok: true, updated: n });
}

// ---------- расписание: чтение ----------
if (action === 'schedule') {
  const s = loadSched();
  flushCache();
  return out({
    config: s,
    summary: planSummary ? { at: planSummary.at, counts: planSummary.counts || {}, upcoming: planSummary.upcoming || [], recent: planSummary.recent || [], paused: Object.values(pausedMap) } : { at: 0, counts: {}, upcoming: [], recent: [], paused: Object.values(pausedMap) },
    groups: (() => { const g = {}; for (const c of Object.values(loadAccounts())) if (c.group) g[c.group] = 1; return Object.keys(g).sort(natural); })(),
    server_time: new Date().toISOString(),
  });
}

// ---------- расписание: запись ----------
const HM = /^([01]?\d|2[0-3]):[0-5]\d$/;
const pad2 = t => { const [h, m] = t.split(':'); return String(h).padStart(2, '0') + ':' + m; };
const mmOf = t => { const [h, m] = t.split(':').map(Number); return h * 60 + m; };
const cleanProfile = (name, p) => {
  const o = {};
  o.posts_per_day = intOr(p.posts_per_day, 1, 0, 50);
  o.windows = (Array.isArray(p.windows) ? p.windows : []).slice(0, 6).filter(w => Array.isArray(w) && HM.test(String(w[0])) && (HM.test(String(w[1])) || String(w[1]) === '24:00') && mmOf(String(w[1])) !== mmOf(String(w[0]))).map(w => [pad2(String(w[0])), pad2(String(w[1]))]);
  if (!o.windows.length) throw new Error('Profile "' + name + '": add at least one valid time window (an end earlier than the start means the window continues past midnight).');
  o.min_gap_min = intOr(p.min_gap_min, 60, 0, 1440);
  o.days = (Array.isArray(p.days) ? p.days : []).map(Number).filter(d => d >= 1 && d <= 7);
  if (!o.days.length) o.days = [1, 2, 3, 4, 5, 6, 7];
  try { new Intl.DateTimeFormat('en', { timeZone: String(p.tz) }); o.tz = String(p.tz); } catch (e) { throw new Error('Profile "' + name + '": unknown time zone "' + p.tz + '". Example: Europe/Warsaw.'); }
  o.ramp = (p.ramp && Number(p.ramp.start) > 0) ? { start: intOr(p.ramp.start, 1, 1, 50), every_days: intOr(p.ramp.every_days, 1, 1, 60) } : null;
  o.enabled = p.enabled !== false;
  return o;
};

if (action === 'saveSchedule') {
  const s = loadSched();
  try {
    if (b.global && typeof b.global === 'object') {
      const g = b.global, G = s.global;
      G.catchup_hours = intOr(g.catchup_hours, G.catchup_hours, 0, 72); G.max_parallel = intOr(g.max_parallel, G.max_parallel, 1, 8);
      G.max_prepare = intOr(g.max_prepare, G.max_prepare, 1, 4); G.prepare_ahead_hours = intOr(g.prepare_ahead_hours, G.prepare_ahead_hours, 1, 48);
      G.pause_after_errors = intOr(g.pause_after_errors, G.pause_after_errors, 1, 20);
    }
    if (b.profiles && typeof b.profiles === 'object') {
      const names = Object.keys(b.profiles);
      if (!names.length || names.length > 50) throw new Error('Keep from 1 to 50 profiles.');
      const np = {};
      for (const n of names) { if (!/^[A-Za-z0-9_ -]{1,40}$/.test(n)) throw new Error('Profile name "' + n + '": use 1-40 letters, digits, spaces, "_" or "-".'); np[n] = cleanProfile(n, b.profiles[n] || {}); }
      s.profiles = np;
    }
    if (typeof b.default_profile === 'string') s.default_profile = b.default_profile;
    if (b.group_profile && typeof b.group_profile === 'object') { const gp = {}; for (const k of Object.keys(b.group_profile)) if (b.group_profile[k]) gp[String(k).slice(0, 40)] = String(b.group_profile[k]); s.group_profile = gp; }
    if (!s.profiles[s.default_profile]) s.default_profile = Object.keys(s.profiles)[0];
    for (const g of Object.keys(s.group_profile)) if (!s.profiles[s.group_profile[g]]) delete s.group_profile[g];
    for (const a of Object.keys(s.overrides)) if (s.overrides[a].profile && !s.profiles[s.overrides[a].profile]) delete s.overrides[a].profile;
  } catch (e) { return out({ error: e.message }, 400); }
  saveSched(s);
  return out({ ok: true });
}

if (action === 'pauseAll' || action === 'resumeAll') {
  const s = loadSched(); s.global.paused = action === 'pauseAll'; saveSched(s);
  return out({ ok: true, paused: s.global.paused });
}

if (action === 'setOverride') {
  const targets = accountList(b.accounts);
  if (!targets.length || targets.length > MAX_BULK) return out({ error: 'Select from 1 to ' + MAX_BULK + ' accounts.' }, 400);
  const s = loadSched();
  if (b.profile !== undefined && b.profile !== '' && !s.profiles[b.profile]) return out({ error: 'Unknown profile.' }, 400);
  let n = 0;
  for (const a of targets) {
    if (!validName(a)) continue;
    const o = s.overrides[a] || (s.overrides[a] = {});
    if (b.profile !== undefined) { if (b.profile === '') delete o.profile; else o.profile = b.profile; }
    if (b.posts_per_day !== undefined) { if (b.posts_per_day === null || b.posts_per_day === '') delete o.posts_per_day; else o.posts_per_day = intOr(b.posts_per_day, 1, 0, 50); }
    if (!Object.keys(o).length) delete s.overrides[a];
    n++;
  }
  saveSched(s);
  return out({ ok: true, updated: n });
}

if (action === 'pauseAccounts') {
  const targets = accountList(b.accounts);
  if (!targets.length || targets.length > MAX_BULK) return out({ error: 'Select from 1 to ' + MAX_BULK + ' accounts.' }, 400);
  const paused = b.paused === true;
  fs.mkdirSync('/files/state/paused', { recursive: true });
  const s = loadSched(); let n = 0;
  for (const a of targets) {
    if (!validName(a)) continue;
    const mf = '/files/state/paused/' + a + '.json';
    if (paused) { fs.writeFileSync(mf, JSON.stringify({ reason: 'paused manually', at: new Date().toISOString() })); }
    else {
      try { fs.unlinkSync(mf); } catch (e) { /* не было */ }
      try { fs.unlinkSync('/files/state/errors/' + a + '.json'); } catch (e) { /* не было */ }
      if (s.overrides[a]) { delete s.overrides[a].paused; if (!Object.keys(s.overrides[a]).length) delete s.overrides[a]; }
    }
    n++;
  }
  saveSched(s);
  return out({ ok: true, updated: n });
}

if (action === 'skipSlot') {
  const id = String(b.id || '');
  if (!/^[0-9]{12}_[A-Za-z0-9_-]{1,40}_[a-z0-9]{4}$/.test(id)) return out({ error: 'bad slot id' }, 400);
  const f = '/files/plan/' + id + '.json';
  let slot; try { slot = JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return out({ error: 'Slot not found.' }, 404); }
  if (slot.state !== 'planned' && slot.state !== 'prepared') return out({ error: 'Only waiting slots can be skipped.' }, 400);
  slot.state = 'skipped'; slot.reason = 'skipped manually'; slot.updated = Date.now();
  const t = f + '.tmp'; fs.writeFileSync(t, JSON.stringify(slot)); fs.renameSync(t, f);
  try { fs.rmSync('/files/prepared/' + id, { recursive: true, force: true }); } catch (e) { /* нет папки */ }
  return out({ ok: true });
}

if (action === 'publishNow') {
  const targets = accountList(b.accounts);
  if (!targets.length || targets.length > 100) return out({ error: 'Select from 1 to 100 accounts.' }, 400);
  const table = tableRows(); let created = 0; const skipped = [];
  fs.mkdirSync('/files/plan', { recursive: true });
  const open = new Set();
  for (const f of fs.readdirSync('/files/plan')) { if (!f.endsWith('.json') || f[0] === '.') continue; try { const x = JSON.parse(fs.readFileSync('/files/plan/' + f, 'utf8')); if (x.manual && ['planned', 'preparing', 'prepared', 'publishing'].includes(x.state)) open.add(x.account); } catch (e) { /* битый файл */ } }
  for (const a of targets) {
    if (!validName(a) || !(table[a] && table[a].refresh_token) || open.has(a)) { skipped.push(a); continue; }
    const at = Date.now() - 1000;
    const id = new Date(at).toISOString().slice(0, 16).replace(/[-:T]/g, '') + '_' + a + '_' + Math.random().toString(36).slice(2, 6);
    const slot = { id, account: a, at: new Date(at).toISOString(), state: 'planned', attempts: 0, manual: true, created: at, updated: at };
    fs.writeFileSync('/files/plan/' + id + '.json', JSON.stringify(slot)); created++;
  }
  return out({ ok: created > 0, created, skipped: skipped.slice(0, 20), skipped_count: skipped.length });
}

// ---------- приглашения: чтение и запись ----------
if (action === 'invites') {
  const all = loadInvites().map(i => Object.assign({}, i, { st: invStatus(i) }));
  const counts = {}; for (const i of all) counts[i.st] = (counts[i.st] || 0) + 1;
  const fst = String(p.status || ''), q = String(p.q || '').trim().toLowerCase();
  const rows = all.filter(i => (!fst || i.st === fst) && (!q || String(i.account).toLowerCase().includes(q) || String(i.note || '').toLowerCase().includes(q)))
    .sort((x, y) => String(y.created_at).localeCompare(String(x.created_at)));
  const size = intOr(p.size, 50, 10, 200), pages = Math.max(1, Math.ceil(rows.length / size)), page = intOr(p.page, 1, 1, pages);
  return out({
    total: rows.length, page, pages, size, counts,
    invites: rows.slice((page - 1) * size, page * size).map(i => ({
      token: i.token, account: i.account, note: i.note || '', status: i.st, created_at: i.created_at, opened_at: i.opened_at || '', opens: i.opens || 0,
      used_at: i.used_at || '', expires_at: i.expires_at, link: (i.st === 'pending' || i.st === 'opened') ? invLink(i.token) : '',
    })),
  });
}

if (action === 'createInvites') {
  const targets = accountList(b.accounts);
  if (!targets.length || targets.length > 200) return out({ error: 'Select from 1 to 200 accounts.' }, 400);
  const days = intOr(b.days, 7, 1, 30);
  const note = String(b.note || '').replace(/[\r\n\t]+/g, ' ').trim().slice(0, 80);
  const cfgs = loadAccounts(), all = loadInvites(), created = [], invalid = [], t0 = Date.now();
  for (const a of targets) {
    if (!validName(a)) { invalid.push(a); continue; }
    // прежние неиспользованные приглашения этого аккаунта отзываем: действует только последняя ссылка
    for (const old of all) if (old.account === a && !old.used_at && old.status !== 'revoked') { old.status = 'revoked'; writeInv(old); }
    const token = crypto.randomBytes(24).toString('hex');
    const inv = { token, account: a, note, created_at: new Date(t0).toISOString(), expires_at: new Date(t0 + days * 86400000).toISOString(), status: 'pending' };
    writeInv(inv); all.push(inv); _invMap = null;
    created.push({ account: a, link: invLink(token), expires_at: inv.expires_at });
    if (!cfgs[a]) cfgs[a] = { created_at: inv.created_at };
    try { fs.mkdirSync('/files/inbox/' + a, { recursive: true }); } catch (e) { /* не критично */ }
  }
  if (created.length) saveAccounts(cfgs);
  cache.stock = null; dirtyCache = true; flushCache();
  return out({ ok: created.length > 0, created, invalid: invalid.slice(0, 20), invalid_count: invalid.length });
}

if (action === 'revokeInvite') {
  const tk = String(b.token || '');
  if (!/^[a-f0-9]{48}$/.test(tk)) return out({ error: 'bad token' }, 400);
  let inv; try { inv = JSON.parse(fs.readFileSync(INV_DIR + '/' + tk + '.json', 'utf8')); } catch (e) { return out({ error: 'Invitation not found.' }, 404); }
  if (inv.used_at) return out({ error: 'This invitation was already used: the account is connected.' }, 400);
  inv.status = 'revoked'; writeInv(inv);
  return out({ ok: true });
}

if (action === 'deleteAccount') {
  const a = normName(b.account);
  if (!validName(a)) return out({ error: 'bad account' }, 400);
  const table = tableRows();
  if (table[a] && table[a].refresh_token) return out({ error: 'The account is still connected. Disconnect it first.' }, 400);
  const cfgs = loadAccounts(); delete cfgs[a]; saveAccounts(cfgs);
  const sch = loadSched(); delete sch.overrides[a]; saveSched(sch);
  // Файлы аккаунта не удаляются, а переносятся в /files/removed/
  try {
    fs.mkdirSync('/files/removed', { recursive: true });
    if (fs.existsSync('/files/inbox/' + a)) fs.renameSync('/files/inbox/' + a, '/files/removed/' + a + '-' + Date.now());
  } catch (e) { logErr('deleteAccount move inbox', e); }
  try { fs.mkdirSync('/files/state/removed', { recursive: true }); fs.writeFileSync('/files/state/removed/' + a, '1'); } catch (e) { logErr('deleteAccount marker', e); }
  for (const f of [ '/files/identity/' + a + '.json', '/files/state/paused/' + a + '.json' ]) { try { fs.rmSync(f, { force: true }); } catch (e) { /* нет файла */ } }
  for (const i of loadInvites()) { if (i.account === a && !i.used_at && i.status !== 'revoked') { i.status = 'revoked'; writeInv(i); } }
  _inv = null; _invMap = null; cache.stock = null; dirtyCache = true; flushCache();
  return out({ ok: true });
}

if (action === 'connectTicket') {
  const account = normName(b.account);
  if (!validName(account)) return out({ error: 'Use 1-40 lowercase letters, digits, "_" or "-" for the account name.' }, 400);
  fs.mkdirSync('/files/tickets', { recursive: true });
  try { for (const f of fs.readdirSync('/files/tickets')) { try { if (JSON.parse(fs.readFileSync('/files/tickets/' + f, 'utf8')).exp < Date.now()) fs.rmSync('/files/tickets/' + f, { force: true }); } catch (e) { fs.rmSync('/files/tickets/' + f, { force: true }); } } } catch (e) { /* нет билетов */ }
  const id = crypto.randomBytes(16).toString('hex');
  fs.writeFileSync('/files/tickets/' + id + '.json', JSON.stringify({ account, exp: Date.now() + 120000 }));
  return out({ ok: true, url: baseUrl() + 'webhook/tiktok-start?ticket=' + id });
}

return out({ error: 'unknown action' }, 400);
};
try { return __run(); }
catch (e) { logErr('action ' + action, e); return out({ error: String((e && e.message) || 'Internal error').slice(0, 300) }, 500); }
finally { __release(); }"""


def build(bound):
    dt = {"__rl": True, "mode": "id", "value": "SSWsIdTjYaqpXDiV"} if bound else {"__rl": True, "mode": "name", "value": "tiktok_accounts"}
    nodes = [
        {"id": "c0000005-0000-4000-8000-000000000001", "name": "Panel GET", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0],
         "parameters": {"httpMethod": "GET", "path": "panel-api", "responseMode": "responseNode", "options": {"allowedOrigins": ORIGIN}},
         "webhookId": "c0000005-0000-4000-8000-0000000000a1"},
        {"id": "c0000005-0000-4000-8000-000000000002", "name": "Panel POST", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 200],
         "parameters": {"httpMethod": "POST", "path": "panel-save", "responseMode": "responseNode", "options": {"allowedOrigins": ORIGIN}},
         "webhookId": "c0000005-0000-4000-8000-0000000000a2"},
        {"id": "c0000005-0000-4000-8000-000000000003", "name": "Accounts", "type": "n8n-nodes-base.dataTable", "typeVersion": 1, "position": [240, 100],
         "parameters": {"operation": "get", "dataTableId": dt, "returnAll": True}, "alwaysOutputData": True},
        {"id": "c0000005-0000-4000-8000-000000000004", "name": "Handle", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [480, 100],
         "parameters": {"jsCode": HANDLE}},
        {"id": "c0000005-0000-4000-8000-000000000005", "name": "Respond", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [720, 100],
         "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($json.body) }}",
                        "options": {"responseCode": "={{ $json._status }}", **CORS}}},
    ]
    c = lambda n: {"main": [[{"node": n, "type": "main", "index": 0}]]}
    conn = {"Panel GET": c("Accounts"), "Panel POST": c("Accounts"), "Accounts": c("Handle"), "Handle": c("Respond")}
    return {"id": "ttPanel0000005", "name": "05 Panel API", "active": False, "settings": {"executionOrder": "v1"}, "pinData": {}, "nodes": nodes, "connections": conn}


json.dump(build(False), open(ROOT + "workflows/05_panel_api.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(build(True), open(ROOT + "infra/files/workflows/05_panel_api.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("ok")
