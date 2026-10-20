"""Общие фрагменты JS для узлов Code разных воркфлоу."""

# Функция проверки ключа доступа: ключ только в заголовке Authorization, сравнение за постоянное время,
# блокировка адреса на 15 минут после 10 неудачных попыток за 10 минут. Возвращает { ok, status }.
AUTH_FN_JS = r"""const authCheck = (headers) => {
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
};"""

# Отдельный узел Code: на вход приходит элемент вебхука (headers в $input.first().json)
AUTH_JS = AUTH_FN_JS + "\nreturn [{ json: authCheck($input.first().json.headers || {}) }];"

# Шифрование токенов TikTok в таблице (AES-256-GCM, ключ из N8N_ENCRYPTION_KEY). Старые открытые значения читаются как есть.
TOKEN_CRYPTO_JS = r"""const crypto = require('crypto');
const tkey = () => crypto.scryptSync(String($env.N8N_ENCRYPTION_KEY || $env.CONNECT_SECRET || ''), 'tt-tokens-v1', 32);
const encTok = s => {
  if (!s) return s;
  const iv = crypto.randomBytes(12), c = crypto.createCipheriv('aes-256-gcm', tkey(), iv);
  const d = Buffer.concat([c.update(String(s), 'utf8'), c.final()]);
  return 'enc:' + iv.toString('base64') + ':' + c.getAuthTag().toString('base64') + ':' + d.toString('base64');
};
const decTok = s => {
  if (!s || !String(s).startsWith('enc:')) return s;
  const p = String(s).split(':'), k = crypto.createDecipheriv('aes-256-gcm', tkey(), Buffer.from(p[1], 'base64'));
  k.setAuthTag(Buffer.from(p[2], 'base64'));
  return Buffer.concat([k.update(Buffer.from(p[3], 'base64')), k.final()]).toString('utf8');
};"""

# Имя аккаунта: приводится к нижнему регистру (на Windows папки не различают регистр) и не должно быть зарезервированным именем устройства.
NAME_JS = r"""const NAME = /^[a-z0-9_-]{1,40}$/;
const RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/;
const normName = s => String(s == null ? '' : s).trim().toLowerCase();
const validName = s => NAME.test(s) && !RESERVED.test(s);"""

# Ключ подписи state для подключения аккаунта: производный от CONNECT_SECRET (отдельное назначение ключа).
STATE_KEY_JS = r"""const stateKey = () => require('crypto').createHmac('sha256', String($env.CONNECT_SECRET)).update('state-v1').digest();"""
