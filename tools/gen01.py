import json, copy, os, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from snippets import TOKEN_CRYPTO_JS, STATE_KEY_JS

TOOLS = os.path.dirname(os.path.abspath(__file__)).replace(chr(92), "/") + "/"
ROOT = os.path.dirname(TOOLS.rstrip("/")).replace(chr(92), "/") + "/"
SCOPES = "user.info.basic,video.publish"
SITE_URL = "https://lexus0333.github.io/legal"
CONTACT = "gu1gu2gu4@gmail.com"

PAGE_JS = r"""const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const SITE = String($env.SITE_URL || '""" + SITE_URL + r"""').replace(/\/$/, '');
const CSS = 'body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:560px;margin:48px auto;padding:0 18px;line-height:1.6;color:#1d2129;background:#fff}'
  + 'h1{font-size:24px;margin:0 0 8px}.muted{color:#667085;font-size:14px}ul{padding-left:20px}a{color:#0b57d0}'
  + '.btn{display:inline-block;background:#0b57d0;color:#fff;text-decoration:none;padding:12px 22px;border-radius:10px;font-weight:600;margin:14px 0}'
  + '.box{border:1px solid #e4e7ec;border-radius:12px;padding:14px 16px;margin:14px 0}'
  + '@media (prefers-color-scheme:dark){body{background:#101215;color:#e6e8eb}.muted{color:#9aa4b2}a{color:#7ab0ff}.btn{background:#7ab0ff;color:#0b1220}.box{border-color:#2a2f37}}';
const FOOT = '<p class="muted">EXE Agency Publisher · <a href="' + SITE + '/privacy.html">Privacy Policy</a> · <a href="' + SITE + '/terms.html">Terms of Service</a> · Questions: <a href="mailto:""" + CONTACT + r"""">""" + CONTACT + r"""</a></p>';
const page = (title, body, status) => [{ json: { _status: status, html: '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>' + esc(title) + '</title><style>' + CSS + '</style></head><body>' + body + FOOT + '</body></html>' } }];"""

CHECK_TICKET = r"""// Билет на подключение выдаёт панель (после проверки ключа); он одноразовый и живёт 2 минуты. Ключ доступа в адресе не нужен.
const fs = require('fs');
const t = String(($input.first().json.query || {}).ticket || '');
const no = [{ json: { valid: false } }];
if (!/^[a-f0-9]{32}$/.test(t)) return no;
const f = '/files/tickets/' + t + '.json';
let x; try { x = JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return no; }
try { fs.unlinkSync(f); } catch (e) { return no; }   // если файл уже забрал другой запрос, билет недействителен
if (!x.exp || x.exp < Date.now() || !/^[a-z0-9_-]{1,40}$/.test(String(x.account))) return no;
return [{ json: { valid: true, account: x.account } }];"""

MAKE_STATE = STATE_KEY_JS + r"""
// Подписанный state: подключить аккаунт под чужим именем, подставив свой state, нельзя.
const crypto = require('crypto');
const account = String($input.first().json.account || '');
const sig = crypto.createHmac('sha256', stateKey()).update('acct:' + account).digest('hex').slice(0, 32);
return [{ json: { state: account + '.' + sig } }];"""

CHECK_STATE = STATE_KEY_JS + r"""
// Проверка state из TikTok: подписанное имя аккаунта (подключение из панели) или одноразовое приглашение.
const crypto = require('crypto');
const fs = require('fs');
const q = $input.first().json.query || {};
const state = String(q.state || '');
const fail = (reason, invite) => [{ json: { valid: false, reason, invite: invite || '' } }];
const NAME = /^[a-z0-9_-]{1,40}$/;
if (state.startsWith('inv.')) {
  const token = state.slice(4);
  if (!/^[a-f0-9]{48}$/.test(token)) return fail('invite');
  let inv; try { inv = JSON.parse(fs.readFileSync('/files/invites/' + token + '.json', 'utf8')); } catch (e) { return fail('invite'); }
  if (inv.status === 'revoked' || inv.used_at) return fail('invite_used');
  if (Date.parse(inv.expires_at) < Date.now()) return fail('invite_expired');
  if (!NAME.test(String(inv.account))) return fail('invite');
  if (q.error) return fail('denied', token);
  if (!q.code) return fail('nocode', token);
  return [{ json: { valid: true, account: inv.account, invite: token } }];
}
if (q.error) return fail('denied');
if (!q.code) return fail('nocode');
const i = state.lastIndexOf('.');
const account = state.slice(0, i), sig = state.slice(i + 1);
if (i < 1 || !NAME.test(account)) return fail('state');
const exp = crypto.createHmac('sha256', stateKey()).update('acct:' + account).digest('hex').slice(0, 32);
const a = Buffer.from(sig), b = Buffer.from(exp);
if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return fail('state');
return [{ json: { valid: true, account, invite: '' } }];"""

BUILD_ROW = TOKEN_CRYPTO_JS + r"""
const fs = require('fs');
const t = $('Exchange code for tokens').first().json;
if (!t.access_token) throw new Error('TikTok did not return a token.');
const account = $('Check state').first().json.account;
// Кто подключился: ник и аватар TikTok (необязательно: если запрос не удался, подключение всё равно сохраняется).
let who = {};
try { const u = $input.first().json; who = (u && u.data && u.data.user) || {}; } catch (e) { who = {}; }
const openId = String(t.open_id || who.open_id || '');
// Один и тот же TikTok-аккаунт нельзя подключить под двумя именами: иначе он получит двойные публикации.
try {
  for (const f of fs.readdirSync('/files/identity')) {
    const x = JSON.parse(fs.readFileSync('/files/identity/' + f, 'utf8'));
    if (openId && x.open_id === openId && f.slice(0, -5) !== account) throw new Error('DUPLICATE');
  }
} catch (e) { if (String(e.message) === 'DUPLICATE') throw e; }
const now = Date.now();
return [{ json: {
  account,
  open_id: openId,
  access_token: encTok(t.access_token),
  refresh_token: encTok(t.refresh_token),
  access_expires_at: now + t.expires_in * 1000,
  refresh_expires_at: now + t.refresh_expires_in * 1000,
  identity: { open_id: openId, display_name: String(who.display_name || '').slice(0, 80), avatar_url: String(who.avatar_url || '').slice(0, 300) },
}}];"""

MARK_USED = r"""// Приглашение становится использованным и сохраняется личность подключённого TikTok-аккаунта: только после успешного сохранения токенов.
const fs = require('fs');
const c = $('Check state').first().json;
const b = $('Build row').first().json;
try {
  fs.mkdirSync('/files/identity', { recursive: true });
  const f = '/files/identity/' + b.account + '.json', tmp = f + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(Object.assign({}, b.identity, { connected_at: new Date().toISOString(), via: c.invite ? 'invite' : 'panel' }))); fs.renameSync(tmp, f);
} catch (e) { /* не критично */ }
if (c.invite) {
  const f = '/files/invites/' + c.invite + '.json';
  try { const inv = JSON.parse(fs.readFileSync(f, 'utf8')); inv.status = 'used'; inv.used_at = new Date().toISOString(); const t = f + '.tmp'; fs.writeFileSync(t, JSON.stringify(inv)); fs.renameSync(t, f); } catch (e) { /* файла нет */ }
}
return [{ json: $input.first().json }];"""

RENDER_DONE = PAGE_JS + r"""
const c = $('Check state').first().json;
const b = $('Build row').first().json;
const nick = b.identity && b.identity.display_name ? ' (TikTok name: <b>' + esc(b.identity.display_name) + '</b>)' : '';
if (c.invite) {
  return page('Account connected', '<h1>Thank you, your account is connected</h1><p>The TikTok account <b>' + esc(b.account) + '</b>' + nick + ' is now connected to EXE Agency Publisher. You can close this tab.</p>'
    + '<div class="box muted">You stay in control: you can remove our access at any time in the TikTok app under Settings and privacy, Security and permissions, Apps and services.</div>', 200);
}
return page('Account connected', '<h1>Account connected</h1><p>TikTok account <b>' + esc(b.account) + '</b>' + nick + ' is now connected to EXE Agency Publisher.</p><p><a href="' + SITE + '/console.html">Back to the console</a></p>', 200);"""

RENDER_INVALID = PAGE_JS + r"""
const j = $input.first().json || {};
let reason = 'invite', invite = '';
if (j.valid === false) { reason = j.reason; invite = j.invite || ''; }
else {
  const msg = String((j.error && (j.error.message || j.error)) || '');
  reason = /DUPLICATE/.test(msg) ? 'duplicate' : 'exchange';
  try { invite = $('Check state').first().json.invite || ''; } catch (e) { invite = ''; }
}
const M = {
  denied: ['Access was not granted', 'You chose not to give access, so nothing was connected. If that was a mistake, you can try again.'],
  invite_used: ['This invitation was already used', 'The account behind this invitation is already connected. If you need a new link, ask the person who invited you.'],
  invite_expired: ['This invitation has expired', 'Ask the person who invited you to send a new link.'],
  exchange: ['The connection did not complete', 'TikTok did not confirm the connection. Please try again and approve access.'],
  duplicate: ['This TikTok account is already connected', 'This TikTok account is already linked to another name in our service, so it was not connected again. If this is unexpected, contact the person who invited you.'],
};
const m = M[reason] || ['This link is not valid', 'The link is incomplete, expired or was replaced by a newer one. Ask the person who invited you for a new link.'];
const retry = (invite && (reason === 'denied' || reason === 'exchange' || reason === 'nocode')) ? '<p><a class="btn" href="/webhook/tiktok-invite?t=' + esc(invite) + '">Try again</a></p>' : '';
return page(m[0], '<h1>' + esc(m[0]) + '</h1><p>' + esc(m[1]) + '</p>' + retry, 400);"""

RENDER_TICKET_DENIED = PAGE_JS + r"""
return page('This connection link is no longer valid', '<h1>This connection link is no longer valid</h1><p>Connection links from the console work once and expire after two minutes. Go back to the console and press “Connect” again.</p><p><a class="btn" href="' + SITE + '/console.html">Open the console</a></p>', 403);"""

OPEN_INVITE = PAGE_JS + r"""
const fs = require('fs');
const t = String(($input.first().json.query || {}).t || '');
const bad = (title, text, status) => page(title, '<h1>' + esc(title) + '</h1><p>' + esc(text) + '</p>', status);
if (!/^[a-f0-9]{48}$/.test(t)) return bad('This link is not valid', 'The link is incomplete or was replaced by a newer one. Ask the person who invited you for a new link.', 404);
const f = '/files/invites/' + t + '.json';
let inv; try { inv = JSON.parse(fs.readFileSync(f, 'utf8')); } catch (e) { return bad('This link is not valid', 'The link is incomplete or was replaced by a newer one. Ask the person who invited you for a new link.', 404); }
if (inv.status === 'revoked') return bad('This invitation was cancelled', 'Ask the person who invited you to send a new link.', 410);
if (inv.used_at) return bad('This invitation was already used', 'The account behind this invitation is already connected. If you need a new link, ask the person who invited you.', 410);
if (Date.parse(inv.expires_at) < Date.now()) return bad('This invitation has expired', 'Ask the person who invited you to send a new link.', 410);
// отмечаем открытие ссылки
if (!inv.opened_at) inv.opened_at = new Date().toISOString();
inv.opens = (inv.opens || 0) + 1;
try { const tmp = f + '.tmp'; fs.writeFileSync(tmp, JSON.stringify(inv)); fs.renameSync(tmp, f); } catch (e) { /* не критично */ }
const authorize = 'https://www.tiktok.com/v2/auth/authorize/?client_key=' + encodeURIComponent($env.TIKTOK_CLIENT_KEY) + '&scope=' + encodeURIComponent('""" + SCOPES + r"""') + '&response_type=code&redirect_uri=' + encodeURIComponent('https://' + $env.N8N_HOST + '/webhook/tiktok-callback') + '&state=' + encodeURIComponent('inv.' + t);
const until = new Date(inv.expires_at).toUTCString();
return page('Connect your TikTok account',
  '<h1>Connect your TikTok account</h1>'
  + '<p>You have been invited to connect the TikTok account <b>' + esc(inv.account) + '</b> to <b>EXE Agency Publisher</b>, a private tool we use to publish videos to our own and our partners\' accounts.</p>'
  + '<div class="box"><b>What happens next</b><ul><li>You sign in on TikTok and approve access. We never see your password.</li>'
  + '<li>We receive your TikTok ID and basic profile info (display name and avatar).</li>'
  + '<li>We get permission to publish videos to this account on your behalf.</li></ul></div>'
  + '<p><a class="btn" href="' + esc(authorize) + '">Continue to TikTok</a></p>'
  + '<p class="muted">You can remove our access at any time in the TikTok app under Settings and privacy, Security and permissions, Apps and services. This link works once and is valid until ' + esc(until) + '.</p>', 200);"""


def build(bound):
    src = json.load(open(TOOLS + "templates/orig01_" + ("bound" if bound else "tmpl") + ".json", encoding="utf-8"))
    node = lambda name: copy.deepcopy([n for n in src["nodes"] if n["name"] == name][0])
    dt = {"__rl": True, "mode": "id", "value": "SSWsIdTjYaqpXDiV"} if bound else {"__rl": True, "mode": "name", "value": "tiktok_accounts"}

    def code(i, name, js, x, y, **extra):
        n = {"id": "c0000001-0000-4000-8000-0000000001%02x" % i, "name": name, "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [x, y], "parameters": {"jsCode": js}}
        n.update(extra); return n

    start = node("Start (GET)"); start["position"] = [0, 0]
    goto = node("Go to TikTok"); goto["position"] = [880, -60]
    goto["parameters"]["redirectURL"] = "={{ 'https://www.tiktok.com/v2/auth/authorize/?client_key=' + $env.TIKTOK_CLIENT_KEY + '&scope=' + encodeURIComponent('" + SCOPES + "') + '&response_type=code&redirect_uri=' + encodeURIComponent('https://' + $env.N8N_HOST + '/webhook/tiktok-callback') + '&state=' + encodeURIComponent($json.state) }}"
    cb = node("Callback (GET)"); cb["position"] = [0, 400]
    ex = node("Exchange code for tokens"); ex["position"] = [440, 400]; ex["onError"] = "continueErrorOutput"
    for p in ex["parameters"]["bodyParameters"]["parameters"]:
        if p["name"] == "code": p["value"] = "={{ $('Callback (GET)').first().json.query.code }}"
    save = node("Save account (upsert)"); save["position"] = [1100, 400]; save["parameters"]["dataTableId"] = dt
    save["parameters"]["columns"] = {"mappingMode": "defineBelow", "matchingColumns": [], "schema": [], "value": {
        "account": "={{ $json.account }}", "open_id": "={{ $json.open_id }}", "access_token": "={{ $json.access_token }}", "refresh_token": "={{ $json.refresh_token }}",
        "access_expires_at": "={{ $json.access_expires_at }}", "refresh_expires_at": "={{ $json.refresh_expires_at }}"}}
    userinfo = {"id": "c0000001-0000-4000-8000-0000000001e0", "name": "Get user info", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [660, 400], "onError": "continueRegularOutput",
                "parameters": {"method": "GET", "url": "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,avatar_url", "sendHeaders": True,
                               "headerParameters": {"parameters": [{"name": "Authorization", "value": "={{ 'Bearer ' + $('Exchange code for tokens').first().json.access_token }}"}]}, "options": {"timeout": 15000}}}
    inv = {"id": "c0000001-0000-4000-8000-0000000001f0", "name": "Invite (GET)", "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 700],
           "parameters": {"httpMethod": "GET", "path": "tiktok-invite", "responseMode": "responseNode", "options": {}}, "webhookId": "c0000001-0000-4000-8000-0000000001a1"}
    state_ok = {"id": "c0000001-0000-4000-8000-0000000001f1", "name": "State ok?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [220, 400],
                "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
                    {"id": "s1", "operator": {"type": "boolean", "operation": "true", "singleValue": True}, "leftValue": "={{ $json.valid }}", "rightValue": ""}]}, "options": {}}}
    ticket_ok = {"id": "c0000001-0000-4000-8000-0000000001f3", "name": "Ticket ok?", "type": "n8n-nodes-base.if", "typeVersion": 2.2, "position": [440, 0],
                 "parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict"}, "combinator": "and", "conditions": [
                     {"id": "t1", "operator": {"type": "boolean", "operation": "true", "singleValue": True}, "leftValue": "={{ $json.valid }}", "rightValue": ""}]}, "options": {}}}
    page_node = {"id": "c0000001-0000-4000-8000-0000000001f2", "name": "Page", "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": [1760, 400],
                 "parameters": {"respondWith": "text", "responseBody": "={{ $json.html }}", "options": {"responseCode": "={{ $json._status }}", "responseHeaders": {"entries": [
                     {"name": "Content-Type", "value": "text/html; charset=utf-8"}, {"name": "Referrer-Policy", "value": "no-referrer"},
                     {"name": "X-Robots-Tag", "value": "noindex, nofollow"}, {"name": "Cache-Control", "value": "no-store"}]}}}}

    nodes = [start, code(8, "Check ticket", CHECK_TICKET, 220, 0), ticket_ok, code(9, "Render ticket denied", RENDER_TICKET_DENIED, 660, 160),
             code(1, "Make state", MAKE_STATE, 660, -60), goto,
             cb, code(2, "Check state", CHECK_STATE, 110, 400), state_ok, ex, userinfo,
             code(3, "Build row", BUILD_ROW, 880, 400, onError="continueErrorOutput"), save,
             code(4, "Mark invite used", MARK_USED, 1320, 400), code(5, "Render done", RENDER_DONE, 1540, 400),
             code(6, "Render invalid", RENDER_INVALID, 1100, 620), inv, code(7, "Open invite", OPEN_INVITE, 220, 700), page_node]
    nd = lambda n: [{"node": n, "type": "main", "index": 0}]
    c = lambda n: {"main": [nd(n)]}
    conn = {
        "Start (GET)": c("Check ticket"), "Check ticket": c("Ticket ok?"), "Ticket ok?": {"main": [nd("Make state"), nd("Render ticket denied")]},
        "Make state": c("Go to TikTok"), "Render ticket denied": c("Page"),
        "Callback (GET)": c("Check state"), "Check state": c("State ok?"), "State ok?": {"main": [nd("Exchange code for tokens"), nd("Render invalid")]},
        "Exchange code for tokens": {"main": [nd("Get user info"), nd("Render invalid")]}, "Get user info": c("Build row"),
        "Build row": {"main": [nd("Save account (upsert)"), nd("Render invalid")]},
        "Save account (upsert)": c("Mark invite used"), "Mark invite used": c("Render done"), "Render done": c("Page"), "Render invalid": c("Page"),
        "Invite (GET)": c("Open invite"), "Open invite": c("Page"),
    }
    return {"id": "ttConnect000001", "name": "01 TikTok - Connect account", "active": False, "settings": {"executionOrder": "v1"}, "pinData": {}, "nodes": nodes, "connections": conn}


for bound in (False, True):
    base = ROOT + ("infra/files/workflows/" if bound else "workflows/")
    json.dump(build(bound), open(base + "01_tiktok_connect.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("ok", len(build(True)["nodes"]), "nodes")
