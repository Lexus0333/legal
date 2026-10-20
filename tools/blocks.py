"""Блоки кода для воркфлоу публикации (04, 07, 08): защита от дублей, повторы, шифрование токенов."""
from snippets import TOKEN_CRYPTO_JS

# --- общие фрагменты ---------------------------------------------------------------------------------------------

# Метка «видео уже уходило в TikTok»: ставится сразу после init. Ключ: путь + размер + время изменения файла
# (новое видео под тем же именем получит другой ключ). Пока метка есть, видео не берут ни ручная публикация, ни расписание.
MARKERS_JS = r"""const MARKD = '/files/state/published';
const mkHash = o => { let st = null; try { st = fs.statSync(o); } catch (e) { st = null; } return require('crypto').createHash('sha1').update(o + '|' + (st ? st.size : 0) + '|' + (st ? Math.floor(st.mtimeMs / 1000) : 0)).digest('hex'); };
const markFile = o => MARKD + '/' + mkHash(o) + '.json';
const isMarked = o => { try { return fs.existsSync(markFile(o)); } catch (e) { return false; } };
const writeMark = (o, info) => { fs.mkdirSync(MARKD, { recursive: true }); fs.writeFileSync(markFile(o), JSON.stringify(Object.assign({ orig: o, at: new Date().toISOString() }, info))); };
const clearMark = o => { try { fs.unlinkSync(markFile(o)); } catch (e) { /* метки не было */ } };"""

# Блокировка аккаунта: одновременно с одним аккаунтом работает только одна публикация (ручная или по расписанию).
LOCK_JS = r"""const LOCKS = '/files/state/locks';
const lockAcct = a => {
  fs.mkdirSync(LOCKS, { recursive: true });
  const d = LOCKS + '/acct_' + a;
  try { if (Date.now() - fs.statSync(d).mtimeMs > 20 * 60000) fs.rmSync(d, { recursive: true, force: true }); } catch (e) { /* нет */ }
  try { fs.mkdirSync(d); return true; } catch (e) { return false; }
};
const unlockAcct = a => { try { fs.rmSync(LOCKS + '/acct_' + a, { recursive: true, force: true }); } catch (e) { /* ok */ } };"""

# Классификация ошибок. Системные и лимиты ставят аккаунт на паузу, временные повторяются, остальные считаются окончательными.
CLASS_JS = r"""const SYS_RE = /not connected|Refresh token expired|allowed for this account|unaudited_client|invalid_client|access_token_invalid|scope_not_authorized|invalid_grant|could not be read/i;
const DAILY_RE = /spam_risk|too_many_posts|reached_active_user_cap|daily_post|daily limit/i;
const TRANSIENT_RE = /^\[transient\]|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EAI_AGAIN|ENOTFOUND|socket hang up|timed? ?out|status code 5\d\d|HTTP 5\d\d|service_unavailable|\b429\b/i;"""

# Пауза аккаунта (читается планировщиком и панелью)
PAUSE_JS = r"""const pauseAccount = (account, reason, until) => {
  fs.mkdirSync('/files/state/paused', { recursive: true });
  fs.writeFileSync('/files/state/paused/' + account + '.json', JSON.stringify(Object.assign({ reason: String(reason).slice(0, 300), at: new Date().toISOString() }, until ? { until } : {})));
};
const bumpErrors = (account, limit) => {
  fs.mkdirSync('/files/state/errors', { recursive: true });
  const ef = '/files/state/errors/' + account + '.json'; let c = 0; try { c = JSON.parse(fs.readFileSync(ef, 'utf8')).count || 0; } catch (e) { c = 0; }
  c++; fs.writeFileSync(ef, JSON.stringify({ count: c, at: new Date().toISOString() }));
  return c >= limit ? c : 0;
};"""

# Перенос папки ролика в архив (со всем содержимым); при коллизии имён метка времени ставится ПЕРЕД расширением
ARCHIVE_JS = r"""const EXT = /\.(mp4|mov|m4v)$/i;
const stamp = new Date().toISOString().replace(/[:T]/g, '-').slice(0, 19);
const base = String((r && r.file) || 'video').replace(/\.[^.]+$/, '');
const uniq = (p) => { if (!fs.existsSync(p)) return p; const x = path.extname(p); return p.slice(0, p.length - x.length) + '_' + stamp + x; };
const uniqDir = (p) => (fs.existsSync(p) ? p + '_' + stamp : p);
// Если в папке один ролик, переносится вся папка; если несколько, только этот ролик и его текст.
const archive = (destRoot) => {
  fs.mkdirSync(destRoot, { recursive: true });
  const folderDir = path.dirname(r.orig);
  const videosHere = fs.readdirSync(folderDir).filter(x => EXT.test(x)).length;
  if (r.rel !== '' && videosHere === 1) {
    const target = uniqDir(path.join(destRoot, path.basename(folderDir)));
    fs.renameSync(folderDir, target);
    return target;
  }
  const target = r.rel !== '' ? path.join(destRoot, path.basename(folderDir)) : path.join(destRoot, stamp + '_' + base);
  fs.mkdirSync(target, { recursive: true });
  fs.renameSync(r.orig, uniq(path.join(target, r.file)));
  if (r.hintOrig && fs.existsSync(r.hintOrig)) fs.renameSync(r.hintOrig, uniq(path.join(target, path.basename(r.hintOrig))));
  return target;
};"""

# --- Token logic (04 и 08) -----------------------------------------------------------------------------------

TOKEN_LOGIC = TOKEN_CRYPTO_JS + r"""
// Токены в таблице хранятся зашифрованными; если скоро истекает access-токен, обновляем его через refresh-токен.
const cfg = $('Config').first().json;
const acc = $('Pick next').first().json.account;
const row = $input.first().json;
if (!row || !row.access_token) throw new Error('Account "' + acc + '" is not connected. Connect it from the console or with an invitation link.');
const now = Date.now();
if (Number(row.refresh_expires_at) < now) throw new Error('Refresh token expired for "' + acc + '". Reconnect the account.');
let t;
try { t = { access_token: decTok(row.access_token), refresh_token: decTok(row.refresh_token), access_expires_at: Number(row.access_expires_at), refresh_expires_at: Number(row.refresh_expires_at) }; }
catch (e) { throw new Error('Account "' + acc + '" is not connected: the stored login could not be read. Reconnect the account.'); }
if (t.access_expires_at - now < 10 * 60 * 1000) {
  const body = new URLSearchParams({ client_key: cfg.client_key, client_secret: cfg.client_secret, grant_type: 'refresh_token', refresh_token: t.refresh_token }).toString();
  let r;
  try { r = await this.helpers.httpRequest({ method: 'POST', url: 'https://open.tiktokapis.com/v2/oauth/token/', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body, json: true }); }
  catch (e) { const m = String(e.message); throw new Error((/ECONN|ETIMEDOUT|EAI_AGAIN|socket|timed? ?out|status code 5\d\d|\b429\b/i.test(m) ? '[transient] ' : '') + 'Token refresh failed: ' + m.slice(0, 200)); }
  if (!r.access_token) throw new Error('Token refresh failed: ' + JSON.stringify(r).slice(0, 300));
  t = { access_token: r.access_token, refresh_token: r.refresh_token || t.refresh_token, access_expires_at: now + r.expires_in * 1000, refresh_expires_at: r.refresh_expires_in ? now + r.refresh_expires_in * 1000 : t.refresh_expires_at };
}
return [{ json: { account: acc, access_token: t.access_token, refresh_token: t.refresh_token, access_expires_at: t.access_expires_at, refresh_expires_at: t.refresh_expires_at,
  save_access_token: encTok(t.access_token), save_refresh_token: encTok(t.refresh_token) } }];"""

# --- Upload (04 и 08) -----------------------------------------------------------------------------------------

UPLOAD = r"""const fs = require('fs');
const https = require('https');
""" + MARKERS_JS + r"""
const cfg = $('Config').first().json;
const tok = $('Token logic').first().json.access_token;
const row = $('Pick next').first().json;
const cap = $('AI copy').first().json.copy;
const tags = (cap.hashtags || []).map(h => '#' + String(h).replace(/^#/, '').replace(/\s+/g, '')).join(' ');
const title = (String(cap.caption || '') + ' ' + tags).trim().slice(0, 2200);
if ($env.DRY_RUN === '1') return [{ json: { publish_id: 'dry-run', tiktok_status: 'DRY_RUN', title, privacy: cfg.privacy, params: '{}' } }];

const filePath = row.dir + '/out/src_v1.mp4';
const size = fs.statSync(filePath).size;
const TRANS = /ECONN|ETIMEDOUT|EAI_AGAIN|ENOTFOUND|socket hang up|timed? ?out|status code 5\d\d|HTTP 5\d\d|\b429\b/i;
const wait = ms => new Promise(r => setTimeout(r, ms));
// Запрос к TikTok: временные сбои (сеть, 5xx, 429) повторяются с нарастающей паузой и помечаются как [transient].
const api = async (path, body, tries) => {
  const max = tries || 1; let last;
  for (let a = 1; a <= max; a++) {
    try {
      return await this.helpers.httpRequest({ method: 'POST', url: 'https://open.tiktokapis.com' + path,
        headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json; charset=UTF-8' }, body, json: true });
    } catch (e) {
      const b = (e.response && (e.response.body || e.response.data)) || (e.context && e.context.data) || e.description || '';
      const msg = path + ': ' + e.message + ' ' + (typeof b === 'string' ? b : JSON.stringify(b)).slice(0, 500);
      last = new Error((TRANS.test(msg) ? '[transient] ' : '') + msg);
      if (!TRANS.test(msg) || a === max) break;
      await wait(2000 * a * a);
    }
  }
  throw last;
};
const check = (r, what) => { if (r.error && r.error.code && r.error.code !== 'ok') throw new Error(what + ': ' + JSON.stringify(r.error)); return r; };

const info = check(await api('/v2/post/publish/creator_info/query/', {}, 3), 'creator_info');
const allowed = (info.data && info.data.privacy_level_options) || [];
const privacy = cfg.privacy;
if (allowed.length && !allowed.includes(privacy)) throw new Error('Privacy ' + privacy + ' not allowed for this account now. Allowed: ' + allowed.join(', '));
// Длительность проверяем до загрузки: TikTok задаёт максимум для аккаунта, а длительность готового ролика записана в variants.csv.
const maxSec = Number(info.data && info.data.max_video_post_duration_sec) || 0;
let dur = 0;
try { const rows = fs.readFileSync(row.dir + '/out/variants.csv', 'utf8').trim().split('\n'); dur = Number(rows[rows.length - 1].split(',').pop()) || 0; } catch (e) { dur = 0; }
if (maxSec && dur > maxSec) throw new Error('Video is too long: ' + Math.round(dur) + ' s, TikTok allows up to ' + maxSec + ' s for this account.');
// Метка «создано ИИ»: по умолчанию включена; для аккаунта отключается флагом aigc=false в настройках аккаунта, для всех: AIGC_LABEL=0.
let accCfg = {}; try { accCfg = JSON.parse(fs.readFileSync('/files/accounts.json', 'utf8'))[row.account] || {}; } catch (e) { accCfg = {}; }
const aigc = typeof accCfg.aigc === 'boolean' ? accCfg.aigc : String($env.AIGC_LABEL || '1') !== '0';

// Правила TikTok: до 64 MB - одним куском; больше - куски по 32 MB, остаток уходит в последний.
const MB = 1024 * 1024;
let chunk = size, count = 1;
if (size > 64 * MB) { chunk = 32 * MB; count = Math.floor(size / chunk); }

const init = check(await api('/v2/post/publish/video/init/', {
  post_info: { title, privacy_level: privacy, disable_duet: false, disable_comment: false, disable_stitch: false, is_aigc: aigc },
  source_info: { source: 'FILE_UPLOAD', video_size: size, chunk_size: chunk, total_chunk_count: count },
}, 2), 'init');
const { publish_id, upload_url } = init.data;
// С этого момента видео может оказаться в TikTok: помечаем исходник, чтобы при любом сбое его не выложили второй раз.
if (row.orig) writeMark(row.orig, { state: 'uploading', publish_id, account: row.account });

const putChunk = (start, end) => new Promise((resolve, reject) => {
  const m = String(upload_url).match(/^https:\/\/([^\/]+)(\/.*)$/);
  if (!m) return reject(new Error('bad upload_url'));
  const req = https.request({ method: 'PUT', hostname: m[1], path: m[2],
    headers: { 'Content-Type': 'video/mp4', 'Content-Length': end - start + 1, 'Content-Range': 'bytes ' + start + '-' + end + '/' + size } },
    res => { let b = ''; res.on('data', d => { b += d; }); res.on('end', () => (res.statusCode < 300 ? resolve() : reject(new Error('HTTP ' + res.statusCode + ' ' + b.slice(0, 300))))); });
  req.on('error', reject);
  fs.createReadStream(filePath, { start, end }).pipe(req);
});
for (let i = 0; i < count; i++) {
  const start = i * chunk;
  const end = i === count - 1 ? size - 1 : start + chunk - 1;
  let lastErr = '';
  for (let attempt = 1; attempt <= 3; attempt++) {
    try { await putChunk(start, end); lastErr = ''; break; }
    catch (e) { lastErr = 'upload chunk ' + (i + 1) + '/' + count + ' attempt ' + attempt + ': ' + e.message; await wait(5000); }
  }
  // Файл не доехал целиком: в TikTok ничего не опубликовано, метку снимаем, повтор безопасен.
  if (lastErr) { clearMark(row.orig); throw new Error('[transient] ' + lastErr); }
}

// Опрос статуса. Видео уже загружено, поэтому сбой опроса НЕ означает неудачу публикации: после 5 ошибок подряд статус остаётся «неизвестен».
let status = 'PROCESSING_UPLOAD', fail = '', errs = 0;
for (let k = 0; k < 30; k++) {
  await wait(6000);
  try {
    const s = check(await api('/v2/post/publish/status/fetch/', { publish_id }, 1), 'status');
    errs = 0; status = (s.data && s.data.status) || status;
    if (['PUBLISH_COMPLETE', 'FAILED', 'SEND_TO_USER_INBOX'].includes(status)) { fail = (s.data && s.data.fail_reason) || ''; break; }
  } catch (e) { errs++; if (errs >= 5) { status = 'UNKNOWN'; break; } }
}
if (status === 'FAILED') { clearMark(row.orig); throw new Error('TikTok FAILED: ' + fail); }
if (row.orig) writeMark(row.orig, { state: status === 'PUBLISH_COMPLETE' ? 'published' : 'unconfirmed', publish_id, account: row.account });
return [{ json: { publish_id, tiktok_status: status, title, privacy, params: JSON.stringify({ hook: cap.hook, account: row.account }) } }];"""

# --- 04: ручная публикация --------------------------------------------------------------------------------------

PICK_NEXT_04 = r"""// Берёт следующее видео из /files/inbox и КОПИРУЕТ его в рабочую папку: исходные папки остаются на месте,
// пока видео не опубликовано. Структура: inbox/<аккаунт>/[вложенные папки]/видео.mp4 (рядом могут быть картинки и .txt).
const fs = require('fs');
const path = require('path');
const INBOX = '/files/inbox', WORK = '/files/work', EXT = /\.(mp4|mov|m4v)$/i;
""" + MARKERS_JS + "\n" + LOCK_JS + r"""
fs.mkdirSync(WORK, { recursive: true });
// Одна ручная публикация за раз: блокировка создаётся атомарно. Блокировка старше 15 минут считается зависшей.
const LOCK = path.join(WORK, '.lock');
try { if (Date.now() - fs.statSync(LOCK).mtimeMs > 15 * 60 * 1000) fs.rmSync(LOCK, { recursive: true, force: true }); } catch (e) { /* блокировки нет */ }
try { fs.mkdirSync(LOCK); } catch (e) { return []; }
const release = () => { try { fs.rmSync(LOCK, { recursive: true, force: true }); } catch (e) { /* ok */ } };
let lockedAccount = '';
try {
  const defaultAccount = String($env.DEFAULT_ACCOUNT || 'account1').toLowerCase();
  // видео, уже подготовленные расписанием под будущие слоты, ручная публикация не трогает
  const reserved = new Set();
  try {
    for (const f of fs.readdirSync('/files/plan')) {
      if (!f.endsWith('.json') || f[0] === '.') continue;
      try { const s = JSON.parse(fs.readFileSync('/files/plan/' + f, 'utf8')); if (s.video && ['preparing', 'prepared', 'publishing'].includes(s.state)) reserved.add(s.video.orig); } catch (e) { /* битый файл */ }
    }
  } catch (e) { /* расписание ещё не создавало слоты */ }
  const found = [];
  const walk = (dir, account, rel) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p, account || e.name.toLowerCase(), account ? (rel ? rel + '/' + e.name : e.name) : '');
      else if (EXT.test(e.name)) found.push({ account: account || defaultAccount, file: e.name, rel, orig: p });
    }
  };
  if (fs.existsSync(INBOX)) walk(INBOX, '', '');
  // Порядок: по аккаунту и названию папки/файла с учётом чисел (Рилс 2 раньше Рилс 10).
  found.sort((a, b) => (a.account + '/' + a.rel + '/' + a.file).localeCompare(b.account + '/' + b.rel + '/' + b.file, 'ru', { numeric: true }));
  // Берём первый свободный файл: не занят расписанием, не отправлялся ранее, перестал копироваться, у аккаунта нет другой публикации.
  let pick = null;
  for (const f of found) {
    if (reserved.has(f.orig) || isMarked(f.orig)) continue;
    const s1 = fs.statSync(f.orig).size;
    await new Promise(r => setTimeout(r, 2000));
    if (!(fs.existsSync(f.orig) && fs.statSync(f.orig).size === s1 && s1 > 0)) continue;
    if (!lockAcct(f.account)) continue;
    pick = f; lockedAccount = f.account; break;
  }
  if (!pick) { release(); return []; }
  const dirOrig = path.dirname(pick.orig);
  // Подсказка для текста: файл с тем же именем .txt, либо единственный .txt в папке ролика.
  let txt = pick.orig.replace(EXT, '.txt');
  if (!fs.existsSync(txt)) {
    const txts = fs.readdirSync(dirOrig).filter(n => /\.txt$/i.test(n));
    const videosHere = found.filter(f => path.dirname(f.orig) === dirOrig).length;
    txt = (txts.length === 1 && videosHere === 1) ? path.join(dirOrig, txts[0]) : '';
  }
  const rid = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  const dir = path.join(WORK, rid);
  fs.mkdirSync(dir, { recursive: true });
  const ext = path.extname(pick.file).toLowerCase();
  const src = path.join(dir, 'src' + ext);
  fs.copyFileSync(pick.orig, src);
  const hint = (txt && fs.existsSync(txt)) ? fs.readFileSync(txt, 'utf8').trim() : '';
  const n = Number((($input.first() || { json: {} }).json || {}).n) || 0;
  return [{ json: { rid, account: pick.account, file: pick.file, rel: pick.rel, ext, src, dir, orig: pick.orig, hint, hintOrig: txt || '', remaining: found.length - 1, n } }];
} catch (e) { if (lockedAccount) unlockAcct(lockedAccount); release(); throw e; }"""

FINISH_04 = r"""const fs = require('fs');
const path = require('path');
const r = $('Pick next').first().json;
const u = $input.first().json;
const ai = $('AI copy').first().json;
""" + MARKERS_JS + "\n" + LOCK_JS + "\n" + ARCHIVE_JS + r"""
const release = () => { try { fs.rmSync('/files/work/.lock', { recursive: true, force: true }); } catch (e) { /* ok */ } };
const st = u.tiktok_status === 'PUBLISH_COMPLETE' ? 'Posted' : (u.tiktok_status === 'DRY_RUN' ? 'DryRun' : 'Check');
let music = '';
try { music = String($('Add music').first().json.stdout || '').trim().split('\n').pop().replace(/^MUSIC /, ''); } catch (e) { music = ''; }
let archErr = '';
try {
  if (st !== 'DryRun') {
    // Видео уже в TikTok (метка поставлена при загрузке): сбой переноса папки не приведёт к повторной публикации.
    const finalVideo = r.dir + '/out/src_v1.mp4';
    const target = archive(path.join('/files/done', r.account));
    if (fs.existsSync(finalVideo)) fs.copyFileSync(finalVideo, uniq(path.join(target, base + '_published.mp4')));
    fs.writeFileSync(uniq(path.join(target, base + '_post.json')), JSON.stringify({ posted_at: new Date().toISOString(), account: r.account, source: r.file,
      hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, music }, null, 2));
  }
} catch (e) { archErr = String(e.message).slice(0, 200); }
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: r.rid, account: r.account, file: r.file, rel: r.rel, status: st,
  hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, ai_used: ai.ai_used, ai_error: ai.ai_error, music, archive_error: archErr }) + '\n');
fs.rmSync(r.dir, { recursive: true, force: true });
unlockAcct(r.account); release();
return [{ json: { remaining: r.remaining, n: r.n + 1, status: st } }];"""

FAIL_04 = r"""const fs = require('fs');
const path = require('path');
const r = $('Pick next').first().json;
// Повторный вызов (ошибка пришла по двум веткам): работа уже разобрана.
if (!fs.existsSync(r.dir)) return [];
""" + MARKERS_JS + "\n" + LOCK_JS + "\n" + CLASS_JS + "\n" + PAUSE_JS + "\n" + ARCHIVE_JS + r"""
const release = () => { try { fs.rmSync('/files/work/.lock', { recursive: true, force: true }); } catch (e) { /* ok */ } };
const e = $json.error;
const msg = String(typeof e === 'string' ? e : (e && e.message) || JSON.stringify($json)).slice(0, 400);
const systemic = SYS_RE.test(msg);
const daily = !systemic && DAILY_RE.test(msg);
const transient = !systemic && !daily && TRANSIENT_RE.test(msg);
let sch = {}; try { sch = JSON.parse(fs.readFileSync('/files/schedule.json', 'utf8')); } catch (er) { sch = {}; }
if (systemic) pauseAccount(r.account, msg);
else if (daily) pauseAccount(r.account, 'TikTok daily limit: ' + msg, new Date(Date.now() + 6 * 3600000).toISOString());
const keep = systemic || daily || transient || isMarked(r.orig);   // исходник остаётся в очереди, если сбой временный, системный или видео уже могло уйти в TikTok
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: r.rid, account: r.account, file: r.file, rel: r.rel, status: 'Error', error: msg, kept: keep }) + '\n');
try {
  if (!keep) {
    const target = archive(path.join('/files/failed', r.account));
    fs.writeFileSync(uniq(path.join(target, base + '_error.txt')), msg + '\n');
  }
} catch (err) { /* не критично */ }
fs.rmSync(r.dir, { recursive: true, force: true });
unlockAcct(r.account); release();
// Временные сбои, ошибки аккаунта и лимиты останавливают очередь: остальные видео остаются в inbox.
return [{ json: { error: msg, remaining: keep ? 0 : r.remaining, n: r.n + 1, systemic: systemic || daily, transient, file: r.file, account: r.account } }];"""

# --- 07: подготовка слота -------------------------------------------------------------------------------------

PICK07 = r"""// Подготовка слота: берём следующее видео из папки ЭТОГО аккаунта и копируем в рабочую папку слота.
const fs = require('fs');
const path = require('path');
const EXT = /\.(mp4|mov|m4v)$/i;
""" + MARKERS_JS + r"""
const slotId = $input.first().json.slot.id;
const SF = '/files/plan/' + slotId + '.json';
const slot = JSON.parse(fs.readFileSync(SF, 'utf8'));
const saveSlot = () => { slot.updated = Date.now(); const t = SF + '.tmp'; fs.writeFileSync(t, JSON.stringify(slot)); fs.renameSync(t, SF); };
const natural = (x, y) => String(x).localeCompare(String(y), 'ru', { numeric: true });
// видео, уже занятые другими слотами
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
  if (isMarked(f.orig)) continue;
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

# --- 08: публикация слота -----------------------------------------------------------------------------------------

PICK08 = r"""// Публикация слота: загружаем данные слота и подготовленного видео в том же виде, что в воркфлоу 04.
const fs = require('fs');
""" + LOCK_JS + r"""
const slotId = $input.first().json.slot.id;
const SF = '/files/plan/' + slotId + '.json';
const slot = JSON.parse(fs.readFileSync(SF, 'utf8'));
const dir = '/files/prepared/' + slotId;
if (!fs.existsSync(dir + '/out/src_v1.mp4')) throw new Error('Prepared video not found for slot ' + slotId);
// С аккаунтом одновременно работает только одна публикация (ручная или по расписанию): если занят, повторяем через 2 минуты.
if (!lockAcct(slot.account)) {
  slot.state = 'prepared'; slot.at = new Date(Date.now() + 2 * 60000).toISOString(); slot.updated = Date.now();
  const t = SF + '.tmp'; fs.writeFileSync(t, JSON.stringify(slot)); fs.renameSync(t, SF);
  return [];
}
const v = slot.video || {};
return [{ json: { rid: slotId, account: slot.account, file: v.file || '', rel: v.rel || '', ext: '.mp4', src: '', dir, orig: v.orig || '', hint: '', hintOrig: v.hintOrig || '', remaining: 0, n: 0 } }];"""

FINISH08 = r"""const fs = require('fs');
const path = require('path');
const r = $('Pick next').first().json;
const u = $input.first().json;
const ai = $('AI copy').first().json;
const slot = JSON.parse(fs.readFileSync('/files/plan/' + r.rid + '.json', 'utf8'));
""" + LOCK_JS + "\n" + ARCHIVE_JS + r"""
const writeSlot = (s) => { s.updated = Date.now(); const f = '/files/plan/' + s.id + '.json', t = f + '.tmp'; fs.writeFileSync(t, JSON.stringify(s)); fs.renameSync(t, f); };
const st = u.tiktok_status === 'PUBLISH_COMPLETE' ? 'Posted' : (u.tiktok_status === 'DRY_RUN' ? 'DryRun' : 'Check');
const music = (slot.meta && slot.meta.music) || '';
let archErr = '';
try {
  if (st !== 'DryRun') {
    // Видео уже в TikTok (метка поставлена при загрузке): сбой переноса папки не приведёт к повторной публикации.
    const target = archive(path.join('/files/done', r.account));
    const finalVideo = r.dir + '/out/src_v1.mp4';
    if (fs.existsSync(finalVideo)) fs.copyFileSync(finalVideo, uniq(path.join(target, base + '_published.mp4')));
    fs.writeFileSync(uniq(path.join(target, base + '_post.json')), JSON.stringify({ posted_at: new Date().toISOString(), account: r.account, source: r.file,
      hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, music, slot: r.rid }, null, 2));
  }
} catch (e) { archErr = String(e.message).slice(0, 200); slot.archive_error = archErr; }
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: r.rid, account: r.account, file: r.file, rel: r.rel, status: st,
  hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, ai_used: ai.ai_used, ai_error: ai.ai_error, music, slot: r.rid, archive_error: archErr }) + '\n');
fs.rmSync(r.dir, { recursive: true, force: true });
slot.state = 'done'; slot.result = st; slot.published_at = new Date().toISOString(); writeSlot(slot);
try { fs.unlinkSync('/files/state/errors/' + r.account + '.json'); } catch (e) { /* счётчика не было */ }
unlockAcct(r.account);
return [{ json: { status: st } }];"""

FAIL08 = r"""const fs = require('fs');
const path = require('path');
const slotId = $('When called').first().json.slot.id;
let r = null; try { r = $('Pick next').first().json; } catch (e) { r = null; }
let slot; try { slot = JSON.parse(fs.readFileSync('/files/plan/' + slotId + '.json', 'utf8')); } catch (e) { return []; }
if (slot.state !== 'publishing') return [];
""" + MARKERS_JS + "\n" + LOCK_JS + "\n" + CLASS_JS + "\n" + PAUSE_JS + "\n" + ARCHIVE_JS + r"""
const writeSlot = (s) => { s.updated = Date.now(); const f = '/files/plan/' + s.id + '.json', t = f + '.tmp'; fs.writeFileSync(t, JSON.stringify(s)); fs.renameSync(t, f); };
const e = $json.error;
const msg = String(typeof e === 'string' ? e : (e && e.message) || JSON.stringify($json)).slice(0, 400);
const systemic = SYS_RE.test(msg);
const daily = !systemic && DAILY_RE.test(msg);
const transient = !systemic && !daily && TRANSIENT_RE.test(msg);
let sch = {}; try { sch = JSON.parse(fs.readFileSync('/files/schedule.json', 'utf8')); } catch (er) { sch = {}; }
const limit = Number(((sch.global || {}).pause_after_errors)) || 3;
const marked = !!(r && r.orig && isMarked(r.orig));
// Временный сбой: слот повторяется позже (до 4 раз), видео остаётся на месте, уведомления не шлём.
if (transient && !marked) {
  slot.pub_attempts = (slot.pub_attempts || 0) + 1;
  if (slot.pub_attempts < 4) {
    slot.state = 'prepared'; slot.error = msg; slot.at = new Date(Date.now() + Math.min(30, 5 * slot.pub_attempts) * 60000).toISOString();
    writeSlot(slot); unlockAcct(slot.account);
    fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: slotId, account: slot.account, file: (r && r.file) || '', rel: (r && r.rel) || '', status: 'Error', error: 'Temporary problem, will retry: ' + msg, kept: true, slot: slotId }) + '\n');
    return [];
  }
}
if (systemic) pauseAccount(slot.account, msg);
else if (daily) pauseAccount(slot.account, 'TikTok daily limit: ' + msg, new Date(Date.now() + 6 * 3600000).toISOString());
else { const c = bumpErrors(slot.account, limit); if (c) pauseAccount(slot.account, c + ' errors in a row. Last: ' + msg); }
const keep = systemic || daily || transient || marked;
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: slotId, account: slot.account, file: (r && r.file) || '', rel: (r && r.rel) || '', status: 'Error', error: msg, kept: keep, slot: slotId }) + '\n');
try {
  if (r && !keep && r.orig && fs.existsSync(r.orig)) {
    const target = archive(path.join('/files/failed', r.account));
    fs.writeFileSync(uniq(path.join(target, base + '_error.txt')), msg + '\n');
  }
} catch (er) { /* не критично */ }
try { fs.rmSync('/files/prepared/' + slotId, { recursive: true, force: true }); } catch (er) { /* нет папки */ }
slot.state = 'failed'; slot.error = msg; writeSlot(slot);
unlockAcct(slot.account);
return [{ json: { error: msg, systemic: systemic || daily, file: (r && r.file) || '', account: slot.account } }];"""
