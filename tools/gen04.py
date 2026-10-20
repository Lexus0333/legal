import json, re, copy, sys

import os
TOOLS = os.path.dirname(os.path.abspath(__file__)).replace(chr(92), "/") + "/"
ROOT = os.path.dirname(TOOLS.rstrip("/")).replace(chr(92), "/") + "/"
bound02 = json.load(open(TOOLS + "templates/02_bound.json", encoding="utf-8"))
tmpl02 = json.load(open(TOOLS + "templates/02_tmpl.json", encoding="utf-8"))
def node(d, name):
    return copy.deepcopy([n for n in d["nodes"] if n["name"] == name][0])

WF_ID = "ttPublishFolder000004"

PICK_NEXT = r"""// Берёт следующее видео из /files/inbox и КОПИРУЕТ его в рабочую папку: исходные папки остаются на месте,
// пока видео не опубликовано. Структура: inbox/<аккаунт>/[вложенные папки]/видео.mp4 (рядом могут быть картинки и .txt).
const fs = require('fs');
const path = require('path');
const INBOX = '/files/inbox', WORK = '/files/work', EXT = /\.(mp4|mov|m4v)$/i;
fs.mkdirSync(WORK, { recursive: true });
// Одна публикация за раз: блокировка создаётся атомарно. Блокировка старше 30 минут считается зависшей.
const LOCK = path.join(WORK, '.lock');
try { if (Date.now() - fs.statSync(LOCK).mtimeMs > 30 * 60 * 1000) fs.rmSync(LOCK, { recursive: true, force: true }); } catch (e) { /* блокировки нет */ }
try { fs.mkdirSync(LOCK); } catch (e) { return []; }
const release = () => { try { fs.rmSync(LOCK, { recursive: true, force: true }); } catch (e) { /* ok */ } };
try {
  const defaultAccount = $env.DEFAULT_ACCOUNT || 'account1';
  const found = [];
  const walk = (dir, account, rel) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p, account || e.name, account ? (rel ? rel + '/' + e.name : e.name) : '');
      else if (EXT.test(e.name)) found.push({ account: account || defaultAccount, file: e.name, rel, orig: p });
    }
  };
  if (fs.existsSync(INBOX)) walk(INBOX, '', '');
  // Порядок: по аккаунту и названию папки/файла с учётом чисел (Рилс 2 раньше Рилс 10).
  found.sort((a, b) => (a.account + '/' + a.rel + '/' + a.file).localeCompare(b.account + '/' + b.rel + '/' + b.file, 'ru', { numeric: true }));
  // Берём только файл, который перестал копироваться (размер не меняется 2 секунды).
  let pick = null;
  for (const f of found) {
    const s1 = fs.statSync(f.orig).size;
    await new Promise(r => setTimeout(r, 2000));
    if (fs.existsSync(f.orig) && fs.statSync(f.orig).size === s1 && s1 > 0) { pick = f; break; }
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
} catch (e) { release(); throw e; }"""

LOG_PROCESSING = r"""const fs = require('fs');
const r = $('Pick next').first().json;
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: r.rid, account: r.account, file: r.file, rel: r.rel, status: 'Processing' }) + '\n');
return [{ json: r }];"""

AI_COPY = r"""// Хук и подпись: ИИ по кадрам видео (если в .env заданы AI_BASE_URL, AI_API_KEY, AI_MODEL).
// Любой сбой ИИ не останавливает публикацию: берём текст из подсказки .txt или имя файла.
const fs = require('fs');
const https = require('https');
const http = require('http');
const r = $('Pick next').first().json;
const base = String($env.AI_BASE_URL || '').trim().replace(/\/+$/, '');
const key = String($env.AI_API_KEY || '').trim();
const model = String($env.AI_MODEL || '').trim();
const clean = s => String(s || '').replace(/[\u{1F000}-\u{1FFFF}\u{2600}-\u{27BF}\uFE0F\u200D]/gu, '').replace(/\s+/g, ' ').trim();

const lines = r.hint.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
let copy = {
  hook: clean(lines[0] || '').slice(0, 60),
  caption: clean(lines.slice(1).join(' ') || $env.DEFAULT_CAPTION || '').slice(0, 120),
  hashtags: String($env.DEFAULT_HASHTAGS || '').split(/[\s,]+/).map(h => h.replace(/^#/, '')).filter(Boolean).slice(0, 5),
};
let aiUsed = false, aiError = '';

if (base && key && model) {
  try {
    const frames = [1, 2, 3].map(i => r.dir + '/frames/f' + i + '.jpg').filter(p => fs.existsSync(p))
      .map(p => ({ type: 'image_url', image_url: { url: 'data:image/jpeg;base64,' + fs.readFileSync(p).toString('base64') } }));
    const lang = $env.AI_LANGUAGE || (r.hint ? 'the same language as the notes' : 'Russian');
    const prompt = 'You write copy for a short vertical TikTok video. You see 3 frames from it.' +
      (r.hint ? ' Notes from the author: ' + r.hint.slice(0, 500) + '.' : '') +
      ' Reply with JSON only: {"hook": string, "caption": string, "hashtags": [string]}. ' +
      'hook: a short attention-grabbing line shown on screen for the first seconds, max 45 characters, no emoji. ' +
      'caption: one natural sentence, max 120 characters, no hashtags, no emoji. hashtags: 3-5 relevant words without #. ' +
      'Language: ' + lang + '. Do not invent facts that are not visible or stated.';
    const body = JSON.stringify({ model, temperature: 0.8, response_format: { type: 'json_object' },
      messages: [{ role: 'user', content: [{ type: 'text', text: prompt }].concat(frames) }] });
    const m = (base + '/chat/completions').match(/^(https?):\/\/([^\/:]+)(?::(\d+))?(\/.*)$/);
    if (!m) throw new Error('bad AI_BASE_URL');
    const lib = m[1] === 'https' ? https : http;
    const text = await new Promise((resolve, reject) => {
      const req = lib.request({ method: 'POST', hostname: m[2], port: m[3] || (m[1] === 'https' ? 443 : 80), path: m[4], timeout: 60000,
        headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body), Authorization: 'Bearer ' + key } },
        res => { let b = ''; res.on('data', d => { b += d; }); res.on('end', () => (res.statusCode < 300 ? resolve(b) : reject(new Error('AI HTTP ' + res.statusCode + ' ' + b.slice(0, 200))))); });
      req.on('timeout', () => req.destroy(new Error('AI timeout')));
      req.on('error', reject);
      req.end(body);
    });
    const content = JSON.parse(text).choices[0].message.content;
    const j = JSON.parse(String(content).match(/\{[\s\S]*\}/)[0]);
    copy = {
      hook: clean(j.hook).slice(0, 60),
      caption: clean(j.caption).slice(0, 150),
      hashtags: (Array.isArray(j.hashtags) ? j.hashtags : []).map(h => clean(h).replace(/^#/, '').replace(/\s+/g, '')).filter(Boolean).slice(0, 5),
    };
    aiUsed = true;
  } catch (e) { aiError = String(e.message).slice(0, 200); }
}
// Если хука/подписи/хэштегов нет (нет .txt и ИИ не сработал), берём случайные из пулов /files/pools/*.txt.
// Списки аккаунта (/files/pools/<аккаунт>/) важнее общих (/files/pools/<язык>/). Пустой файл аккаунта означает "не использовать".
const readPool = f => { try { return fs.readFileSync(f, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(Boolean); } catch (e) { return null; } };
const pool = n => (/^[A-Za-z0-9_-]{1,40}$/.test(r.account) ? readPool('/files/pools/' + r.account + '/' + n + '.txt') : null) || readPool('/files/pools/' + ($env.POOL_LANG || 'en') + '/' + n + '.txt') || [];
const pickOne = a => a[Math.floor(Math.random() * a.length)];
if (!copy.hook) { const h = pool('hooks'); if (h.length) copy.hook = clean(pickOne(h)).slice(0, 60); }
if (!copy.caption) { const c = pool('captions'); if (c.length) copy.caption = pickOne(c).slice(0, 150); }
if (!copy.hashtags.length) {
  const tg = pool('hashtags');
  if (tg.length) copy.hashtags = tg.map(h => ({ h, k: Math.random() })).sort((a, b) => a.k - b.k).slice(0, 4).map(o => o.h.replace(/^#/, '').replace(/\s+/g, ''));
}
fs.writeFileSync(r.dir + '/hook.txt', copy.hook ? copy.hook + '\n' : '');
return [{ json: { copy, ai_used: aiUsed, ai_error: aiError } }];"""

FINISH = r"""const fs = require('fs');
const path = require('path');
const r = $('Pick next').first().json;
const u = $input.first().json;
const ai = $('AI copy').first().json;
const EXT = /\.(mp4|mov|m4v)$/i;
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
const release = () => { try { fs.rmSync('/files/work/.lock', { recursive: true, force: true }); } catch (e) { /* ok */ } };
const st = u.tiktok_status === 'PUBLISH_COMPLETE' ? 'Posted' : (u.tiktok_status === 'DRY_RUN' ? 'DryRun' : 'Check');
let music = '';
try { music = String($('Add music').first().json.stdout || '').trim().split('\n').pop().replace(/^MUSIC /, ''); } catch (e) { music = ''; }
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: r.rid, account: r.account, file: r.file, rel: r.rel, status: st,
  hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, ai_used: ai.ai_used, ai_error: ai.ai_error, music }) + '\n');
let archived = '';
try {
  if (st !== 'DryRun') {
    // Готовое видео (то, что ушло в TikTok) и данные публикации кладём рядом с исходниками.
    const finalVideo = r.dir + '/out/src_v1.mp4';
    const target = archive(path.join('/files/done', r.account));
    archived = target;
    if (fs.existsSync(finalVideo)) fs.copyFileSync(finalVideo, uniq(path.join(target, base + '_published.mp4')));
    fs.writeFileSync(uniq(path.join(target, base + '_post.json')), JSON.stringify({ posted_at: new Date().toISOString(), account: r.account, source: r.file,
      hook: ai.copy.hook, caption: u.title, publish_id: u.publish_id, tiktok_status: u.tiktok_status, privacy: u.privacy, music }, null, 2));
  }
} finally {
  fs.rmSync(r.dir, { recursive: true, force: true });
  release();
}
return [{ json: { remaining: r.remaining, n: r.n + 1, status: st, archived } }];"""

FAIL = r"""const fs = require('fs');
const path = require('path');
const r = $('Pick next').first().json;
// Повторный вызов (ошибка пришла по двум веткам): работа уже разобрана.
if (!fs.existsSync(r.dir)) return [];
const EXT = /\.(mp4|mov|m4v)$/i;
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
const release = () => { try { fs.rmSync('/files/work/.lock', { recursive: true, force: true }); } catch (e) { /* ok */ } };
const e = $json.error;
const msg = String(typeof e === 'string' ? e : (e && e.message) || JSON.stringify($json)).slice(0, 400);
// Проблемы аккаунта или приложения: исходники остаются в очереди, она останавливается.
const systemic = /not connected|Refresh token expired|allowed for this account|unaudited_client|invalid_client|access_token_invalid|scope_not_authorized/i.test(msg);
fs.appendFileSync('/files/posts.jsonl', JSON.stringify({ at: new Date().toISOString(), id: r.rid, account: r.account, file: r.file, rel: r.rel, status: 'Error', error: msg, kept: systemic }) + '\n');
try {
  if (!systemic) {
    const target = archive(path.join('/files/failed', r.account));
    fs.writeFileSync(uniq(path.join(target, base + '_error.txt')), msg + '\n');
  }
} catch (err) { /* не критично */ } finally {
  fs.rmSync(r.dir, { recursive: true, force: true });
  release();
}
return [{ json: { error: msg, remaining: systemic ? 0 : r.remaining, n: r.n + 1, systemic, file: r.file, account: r.account } }];"""

sys.path.insert(0, TOOLS)
import blocks
PICK_NEXT = blocks.PICK_NEXT_04
FINISH = blocks.FINISH_04
FAIL = blocks.FAIL_04

def build(bound):
    src = bound02 if bound else tmpl02
    nodes = []
    pos = lambda i, row=0: [i * 240, row * 200]

    def add(n, i, row=0):
        n["position"] = pos(i, row)
        nodes.append(n)
        return n

    # триггеры
    add({"id": "c0000004-0000-4000-8000-000000000001", "name": "When called", "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1, "parameters": {"inputSource": "passthrough"}}, 0, 0)
    add({"id": "c0000004-0000-4000-8000-000000000002", "name": "Manual start", "type": "n8n-nodes-base.manualTrigger", "typeVersion": 1, "parameters": {}}, 0, 1)
    add({"id": "c0000004-0000-4000-8000-000000000003", "name": "Pick next", "type": "n8n-nodes-base.code", "typeVersion": 2, "parameters": {"jsCode": PICK_NEXT}}, 1)
    cfg = node(src, "Config"); cfg["id"] = "c0000004-0000-4000-8000-000000000004"; add(cfg, 2)
    add({"id": "c0000004-0000-4000-8000-000000000005", "name": "Log processing", "type": "n8n-nodes-base.code", "typeVersion": 2, "parameters": {"jsCode": LOG_PROCESSING}}, 3)
    add({"id": "c0000004-0000-4000-8000-000000000006", "name": "Extract frames", "type": "n8n-nodes-base.executeCommand", "typeVersion": 1, "onError": "continueErrorOutput",
         "parameters": {"command": "=timeout 180 sh /files/scripts/extract_frames.sh {{ $('Pick next').first().json.src }} {{ $('Pick next').first().json.dir }}/frames"}}, 4)
    add({"id": "c0000004-0000-4000-8000-000000000007", "name": "AI copy", "type": "n8n-nodes-base.code", "typeVersion": 2, "parameters": {"jsCode": AI_COPY}}, 5)
    add({"id": "c0000004-0000-4000-8000-000000000008", "name": "ffmpeg variant", "type": "n8n-nodes-base.executeCommand", "typeVersion": 1, "onError": "continueErrorOutput",
         "parameters": {"command": "=timeout 900 sh /files/scripts/make_variants.sh {{ $('Pick next').first().json.src }} {{ $('Pick next').first().json.dir }}/out {{ $('AI copy').first().json.copy.hook ? $('Pick next').first().json.dir + '/hook.txt' : '-' }} 0 0"}}, 6)
    add({"id": "c0000004-0000-4000-8000-000000000013", "name": "Add music", "type": "n8n-nodes-base.executeCommand", "typeVersion": 1, "onError": "continueErrorOutput",
         "parameters": {"command": "=timeout 900 sh /files/scripts/add_music.sh {{ $('Pick next').first().json.dir }}/out/src_v1.mp4 /files/music {{ $env.MUSIC_MODE || 'silent' }} {{ $env.MUSIC_VOLUME || '1' }}"}}, 6, 1)
    gt = node(src, "Get tokens"); gt["id"] = "c0000004-0000-4000-8000-000000000009"; add(gt, 7)
    tl = node(src, "Token logic"); tl["id"] = "c0000004-0000-4000-8000-00000000000a"; add(tl, 8)
    st = node(src, "Save tokens"); st["id"] = "c0000004-0000-4000-8000-00000000000b"; add(st, 9)
    tl["parameters"]["jsCode"] = blocks.TOKEN_LOGIC
    st["parameters"]["columns"]["value"].update({"access_token": "={{ $json.save_access_token }}", "refresh_token": "={{ $json.save_refresh_token }}"})

    up = node(src, "Upload to TikTok"); up["id"] = "c0000004-0000-4000-8000-00000000000c"
    up["parameters"]["jsCode"] = blocks.UPLOAD
    add(up, 10)

    add({"id": "c0000004-0000-4000-8000-00000000000d", "name": "Finish", "type": "n8n-nodes-base.code", "typeVersion": 2, "parameters": {"jsCode": FINISH}}, 11)
    add({"id": "c0000004-0000-4000-8000-00000000000e", "name": "Fail", "type": "n8n-nodes-base.code", "typeVersion": 2, "parameters": {"jsCode": FAIL}}, 11, 2)
    tg = node(src, "Telegram alert"); tg["id"] = "c0000004-0000-4000-8000-00000000000f"
    tg["parameters"]["text"] = "={{ 'TikTok: error for ' + $json.account + ' (' + $json.file + '): ' + $json.error + ($json.systemic ? ' [stopped, file kept in inbox]' : ($json.transient ? ' [temporary problem, file kept in inbox]' : ' [file moved to failed]')) }}"
    add(tg, 12, 3)
    add({"id": "c0000004-0000-4000-8000-000000000010", "name": "More videos?", "type": "n8n-nodes-base.if", "typeVersion": 2.2,
         "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
             {"id": "m1", "operator": {"type": "number", "operation": "gt"}, "leftValue": "={{ ($json.remaining > 0 && Number($json.n) < Number($env.MAX_POSTS_PER_RUN || 5)) ? 1 : 0 }}", "rightValue": 0}]}, "options": {}}}, 13, 1)
    add({"id": "c0000004-0000-4000-8000-000000000011", "name": "Pause between posts", "type": "n8n-nodes-base.wait", "typeVersion": 1.1,
         "parameters": {"resume": "timeInterval", "amount": "={{ (() => { const a = Number($env.POST_PAUSE_MIN_SEC || 300), b = Number($env.POST_PAUSE_MAX_SEC || 900); return Math.floor(a + Math.random() * Math.max(0, b - a)); })() }}", "unit": "seconds"}}, 14, 1)
    add({"id": "c0000004-0000-4000-8000-000000000012", "name": "Start next video", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2,
         "parameters": {"source": "database", "workflowId": {"__rl": True, "mode": "id", "value": WF_ID},
                        "workflowInputs": {"mappingMode": "defineBelow", "value": {}, "matchingColumns": [], "schema": [], "attemptToConvertTypes": False, "convertFieldsToString": True},
                        "mode": "once", "options": {"waitForSubWorkflow": False}}}, 15, 1)

    c = lambda *names: {"main": [[{"node": n, "type": "main", "index": 0} for n in names]]}
    fail = [{"node": "Fail", "type": "main", "index": 0}]
    ok = lambda n: [{"node": n, "type": "main", "index": 0}]
    conn = {
        "When called": c("Pick next"), "Manual start": c("Pick next"), "Pick next": c("Config"), "Config": {"main": [ok("Log processing"), fail]},
        "Log processing": {"main": [ok("Extract frames"), fail]},
        "Extract frames": {"main": [ok("AI copy"), fail]},
        "AI copy": {"main": [ok("ffmpeg variant"), fail]},
        "ffmpeg variant": {"main": [ok("Add music"), fail]},
        "Add music": {"main": [ok("Get tokens"), fail]},
        "Get tokens": {"main": [ok("Token logic"), fail]},
        "Token logic": {"main": [ok("Save tokens"), fail]},
        "Save tokens": {"main": [ok("Upload to TikTok"), fail]},
        "Upload to TikTok": {"main": [ok("Finish"), fail]},
        "Finish": c("More videos?"),
        "Fail": c("Telegram alert", "More videos?"),
        "More videos?": {"main": [ok("Pause between posts"), []]},
        "Pause between posts": c("Start next video"),
    }
    for n in nodes:
        if n["name"] in ("Config", "Log processing", "AI copy", "Save tokens"): n["onError"] = "continueErrorOutput"
    return {"id": WF_ID, "name": "04 Publish from folder", "active": False, "settings": {"executionOrder": "v1", "executionTimeout": 7200}, "pinData": {}, "nodes": nodes, "connections": conn}

json.dump(build(False), open(ROOT + "workflows/04_publish_from_folder.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(build(True), open(ROOT + "infra/files/workflows/04_publish_from_folder.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("ok, nodes:", len(build(True)["nodes"]))
