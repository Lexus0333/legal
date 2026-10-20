import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snippets import AUTH_JS, TOKEN_CRYPTO_JS, NAME_JS

TOOLS = os.path.dirname(os.path.abspath(__file__)).replace(chr(92), "/") + "/"
ROOT = os.path.dirname(TOOLS.rstrip("/")).replace(chr(92), "/") + "/"
ORIGIN = "https://lexus0333.github.io"
CORS = {"responseHeaders": {"entries": [{"name": "Access-Control-Allow-Origin", "value": ORIGIN}]}}

PRECHECK = r"""// Перед запуском публикации проверяем, что она действительно стартует, и честно говорим причину отказа.
const fs = require('fs');
const path = require('path');
const EXT = /\.(mp4|mov|m4v)$/i;
const refuse = reason => [{ json: { ok: false, reason } }];
try { const st = fs.statSync('/files/work/.lock'); if (Date.now() - st.mtimeMs < 15 * 60 * 1000) return refuse('Another publication is already running. Wait until it finishes.'); } catch (e) { /* блокировки нет */ }
const accounts = new Set($('Accounts').all().map(i => i.json).filter(r => r && r.account && r.refresh_token).map(r => String(r.account).toLowerCase()));
if (!accounts.size) return refuse('No TikTok account is connected. Connect an account first.');
// есть ли хотя бы одно видео у подключённого аккаунта (поиск останавливается на первом найденном)
let found = false;
const walk = (dir, account) => {
  if (found) return;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (found) return;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, account || e.name.toLowerCase());
    else if (EXT.test(e.name) && accounts.has(account || String($env.DEFAULT_ACCOUNT || 'account1').toLowerCase())) found = true;
  }
};
try { if (fs.existsSync('/files/inbox')) walk('/files/inbox', ''); } catch (e) { /* нет inbox */ }
if (!found) return refuse('There are no videos in the inbox for connected accounts.');
return [{ json: { ok: true } }];"""

QUEUE = r"""// Очередь = первые видео из inbox + журнал публикаций (читаем только хвост журнала, последние 2 МБ).
const fs = require('fs');
const path = require('path');
const EXT = /\.(mp4|mov|m4v)$/i;
const natural = (x, y) => String(x).localeCompare(String(y), 'ru', { numeric: true });
const LOG = '/files/posts.jsonl';
let text = '';
try {
  const size = fs.statSync(LOG).size, start = Math.max(0, size - 2 * 1024 * 1024), len = size - start, buf = Buffer.alloc(len), fd = fs.openSync(LOG, 'r');
  fs.readSync(fd, buf, 0, len, start); fs.closeSync(fd);
  text = buf.toString('utf8'); if (start > 0) text = text.slice(text.indexOf('\n') + 1);
} catch (e) { /* журнала ещё нет */ }
const byId = new Map();
for (const line of text.split('\n')) {
  if (!line.trim()) continue;
  try { const o = JSON.parse(line); byId.set(o.id, Object.assign({}, byId.get(o.id) || {}, o)); } catch (e) { /* битая строка */ }
}
const now = Date.now(), STALE = 20 * 60 * 1000;
// Видео, которое сейчас публикуется, остаётся в inbox: не показываем его второй раз как "ожидающее".
const busy = new Set();
for (const o of byId.values()) if (o.status === 'Processing' && now - Date.parse(o.at) < STALE) busy.add([o.account, o.rel || '', o.file].join('|'));
// Первые 8 ожидающих (обход по порядку с остановкой) и общее число (из кэша панели, иначе полный обход).
const first = [];
const sorted = d => fs.readdirSync(d, { withFileTypes: true }).sort((a, b) => natural(a.name, b.name));
const walk = (dir, account, rel) => {
  for (const e of sorted(dir)) {
    if (first.length >= 8) return;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, account || e.name.toLowerCase(), account ? (rel ? rel + '/' + e.name : e.name) : '');
    else if (EXT.test(e.name)) { const acc = account || String($env.DEFAULT_ACCOUNT || 'account1').toLowerCase(); if (!busy.has([acc, rel, e.name].join('|'))) first.push({ account: acc, file: e.name, rel }); }
  }
};
try { if (fs.existsSync('/files/inbox')) walk('/files/inbox', '', ''); } catch (e) { /* нет inbox */ }
let total = null;
try { const c = JSON.parse(fs.readFileSync('/files/panel_cache.json', 'utf8')); if (c.stock && now - c.stock.at < 5 * 60000) total = Object.values(c.stock.by).reduce((a, b) => a + b, 0); } catch (e) { total = null; }
if (total === null) {
  total = 0;
  const count = d => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { if (e.isDirectory()) count(path.join(d, e.name)); else if (EXT.test(e.name)) total++; } };
  try { if (fs.existsSync('/files/inbox')) count('/files/inbox'); } catch (e) { /* нет inbox */ }
}
const label = (rel, file) => (rel ? rel + ' / ' : '') + file;
const rows = first.map(w => ({ status: 'Ready', file: label(w.rel, w.file), account: w.account }));
if (total > first.length) rows.push({ status: 'Ready', file: '… and ' + (total - first.length) + ' more waiting in the inbox', account: '' });
[...byId.values()].sort((a, b) => String(b.at).localeCompare(String(a.at))).slice(0, 40).forEach(o => {
  let status = o.status, error = String(o.error || '').slice(0, 200);
  if (status === 'Processing' && now - Date.parse(o.at) > STALE) { status = 'Error'; error = 'Interrupted. The video was not published.'; }
  rows.push({ status, file: label(o.rel, o.file), account: o.account, hook: o.hook || '', caption: o.caption || '', tiktok_status: o.tiktok_status || '', privacy: o.privacy || '', error, processed_at: o.at || '', ai_used: !!o.ai_used, waiting_total: total });
});
return (rows.length ? rows : [{}]).map(r => ({ json: r }));"""

BUILD = r"""// Только безопасные поля: токены и open_id наружу не отдаём.
const now = Date.now();
const accounts = $('Accounts').all().map(i => i.json).filter(r => r.account).map(r => ({
  account: r.account,
  connected: !!r.refresh_token,
  access_valid: Number(r.access_expires_at) > now,
  refresh_expires_at: Number(r.refresh_expires_at) || null,
}));
const queue = $('Queue').all().map(i => i.json).filter(r => r.status).slice(0, 60);
return [{ json: { accounts, queue, max_per_run: Number($env.MAX_POSTS_PER_RUN || 5), dry_run: $env.DRY_RUN === '1', ai_configured: !!($env.AI_BASE_URL && $env.AI_API_KEY && $env.AI_MODEL), server_time: new Date().toISOString() } }];"""

REVOKE = TOKEN_CRYPTO_JS + r"""
// Сначала отзываем доступ приложения на стороне TikTok, затем токены удаляются из таблицы.
const fs = require('fs');
const acc = $('Get account').first().json;
const out = { disconnected: true, revoked: false };
let token = ''; try { token = acc && acc.access_token ? decTok(acc.access_token) : ''; } catch (e) { out.revoke_error = 'Stored token could not be read.'; }
if (token) {
  const body = 'client_key=' + encodeURIComponent($env.TIKTOK_CLIENT_KEY) + '&client_secret=' + encodeURIComponent($env.TIKTOK_CLIENT_SECRET) + '&token=' + encodeURIComponent(token);
  try {
    await this.helpers.httpRequest({ method: 'POST', url: 'https://open.tiktokapis.com/v2/oauth/revoke/', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body, json: false });
    out.revoked = true;
  } catch (e) { out.revoke_error = String(e.message).slice(0, 200); }
}
// запись о личности подключённого TikTok-аккаунта тоже удаляем
try { const name = String($('Console API (GET)').first().json.query.account || '').toLowerCase(); if (/^[a-z0-9_-]{1,40}$/.test(name)) fs.rmSync('/files/identity/' + name + '.json', { force: true }); } catch (e) { /* не критично */ }
return [{ json: out }];"""


def build(bound):
    dt = {"__rl": True, "mode": "id", "value": "SSWsIdTjYaqpXDiV"} if bound else {"__rl": True, "mode": "name", "value": "tiktok_accounts"}
    q = "$('Console API (GET)').first().json.query"
    nodes = [
        {"id": "c0000003-0000-4000-8000-000000000001", "name": "Console API (GET)", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0],
         "parameters": {"httpMethod": "GET", "path": "console-api", "responseMode": "responseNode", "options": {"allowedOrigins": ORIGIN}}, "webhookId": "c0000003-0000-4000-8000-0000000000a1"},
        {"id": "c0000003-0000-4000-8000-000000000002", "name": "Auth", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [220, 0], "parameters": {"jsCode": AUTH_JS}},
        {"id": "c0000003-0000-4000-8000-000000000003", "name": "Key ok?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [440, 0],
         "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
             {"id": "k1", "operator": {"type": "boolean", "operation": "true", "singleValue": True}, "leftValue": "={{ $json.ok }}", "rightValue": ""}]}, "options": {}}},
        {"id": "c0000003-0000-4000-8000-000000000004", "name": "Denied", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [660, 200],
         "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify({ error: $json.status === 429 ? 'too many attempts' : 'forbidden' }) }}", "options": {"responseCode": "={{ $json.status }}", **CORS}}},
        {"id": "c0000003-0000-4000-8000-000000000005", "name": "Accounts", "type": "n8n-nodes-base.dataTable", "typeVersion": 1, "position": [660, 0],
         "parameters": {"operation": "get", "dataTableId": dt, "returnAll": True}, "alwaysOutputData": True},
        {"id": "c0000003-0000-4000-8000-000000000006", "name": "Run requested?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [880, 0],
         "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
             {"id": "r1", "operator": {"type": "string", "operation": "equals"}, "leftValue": "={{ " + q + ".action }}", "rightValue": "run"}]}, "options": {}}},
        {"id": "c0000003-0000-4000-8000-000000000007", "name": "Precheck run", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1100, -140], "parameters": {"jsCode": PRECHECK}},
        {"id": "c0000003-0000-4000-8000-000000000008", "name": "Can run?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [1320, -140],
         "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
             {"id": "c1", "operator": {"type": "boolean", "operation": "true", "singleValue": True}, "leftValue": "={{ $json.ok }}", "rightValue": ""}]}, "options": {}}},
        {"id": "c0000003-0000-4000-8000-000000000009", "name": "Start posting workflow", "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2, "position": [1540, -220],
         "parameters": {"source": "database", "workflowId": {"__rl": True, "mode": "id", "value": "ttPublishFolder000004"},
                        "workflowInputs": {"mappingMode": "defineBelow", "value": {}, "matchingColumns": [], "schema": [], "attemptToConvertTypes": False, "convertFieldsToString": True},
                        "mode": "once", "options": {"waitForSubWorkflow": False}}},
        {"id": "c0000003-0000-4000-8000-00000000000a", "name": "Respond run", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [1760, -220],
         "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify({ started: true }) }}", "options": {**CORS}}},
        {"id": "c0000003-0000-4000-8000-00000000000b", "name": "Respond refused", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [1540, -60],
         "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify({ started: false, reason: $json.reason }) }}", "options": {**CORS}}},
        {"id": "c0000003-0000-4000-8000-00000000000c", "name": "Disconnect requested?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [1100, 200],
         "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
             {"id": "d1", "operator": {"type": "string", "operation": "equals"}, "leftValue": "={{ " + q + ".action }}", "rightValue": "disconnect"},
             {"id": "d2", "operator": {"type": "string", "operation": "regex"}, "leftValue": "={{ String(" + q + ".account || '').toLowerCase() }}", "rightValue": "^[a-z0-9_-]{1,40}$"}]}, "options": {}}},
        {"id": "c0000003-0000-4000-8000-00000000000d", "name": "Get account", "type": "n8n-nodes-base.dataTable", "typeVersion": 1, "position": [1320, 120],
         "parameters": {"operation": "get", "dataTableId": dt, "filters": {"conditions": [{"keyName": "account", "condition": "eq", "keyValue": "={{ String(" + q + ".account).toLowerCase() }}"}]}, "returnAll": False, "limit": 1}, "alwaysOutputData": True},
        {"id": "c0000003-0000-4000-8000-00000000000e", "name": "Revoke access", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1540, 120], "parameters": {"jsCode": REVOKE}},
        {"id": "c0000003-0000-4000-8000-00000000000f", "name": "Delete account", "type": "n8n-nodes-base.dataTable", "typeVersion": 1, "position": [1760, 120],
         "parameters": {"operation": "deleteRows", "dataTableId": dt, "filters": {"conditions": [{"keyName": "account", "condition": "eq", "keyValue": "={{ String(" + q + ".account).toLowerCase() }}"}]}}, "alwaysOutputData": True},
        {"id": "c0000003-0000-4000-8000-000000000010", "name": "Respond disconnect", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [1980, 120],
         "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($('Revoke access').first().json) }}", "options": {**CORS}}},
        {"id": "c0000003-0000-4000-8000-000000000011", "name": "Queue", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1320, 360], "parameters": {"jsCode": QUEUE}, "alwaysOutputData": True},
        {"id": "c0000003-0000-4000-8000-000000000012", "name": "Build status", "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1540, 360], "parameters": {"jsCode": BUILD}},
        {"id": "c0000003-0000-4000-8000-000000000013", "name": "Respond status", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [1760, 360],
         "parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}", "options": {**CORS}}},
    ]
    nd = lambda n: [{"node": n, "type": "main", "index": 0}]
    c = lambda n: {"main": [nd(n)]}
    conn = {
        "Console API (GET)": c("Auth"), "Auth": c("Key ok?"), "Key ok?": {"main": [nd("Accounts"), nd("Denied")]},
        "Accounts": c("Run requested?"), "Run requested?": {"main": [nd("Precheck run"), nd("Disconnect requested?")]},
        "Precheck run": c("Can run?"), "Can run?": {"main": [nd("Start posting workflow"), nd("Respond refused")]}, "Start posting workflow": c("Respond run"),
        "Disconnect requested?": {"main": [nd("Get account"), nd("Queue")]}, "Get account": c("Revoke access"), "Revoke access": c("Delete account"), "Delete account": c("Respond disconnect"),
        "Queue": c("Build status"), "Build status": c("Respond status"),
    }
    return {"id": "ttConsole000003", "name": "03 Console API", "active": False, "settings": {"executionOrder": "v1"}, "pinData": {}, "nodes": nodes, "connections": conn}


for bound in (False, True):
    base = ROOT + ("infra/files/workflows/" if bound else "workflows/")
    json.dump(build(bound), open(base + "03_console_api.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("ok", len(build(True)["nodes"]), "nodes")
