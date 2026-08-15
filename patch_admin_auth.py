# -*- coding: utf-8 -*-
# mvr-proxy · админ достъпът минава на Worker secret.
#
# Защо: repo-то е ПУБЛИЧНО, а паролата стоеше като константа в кода.
# Всеки, който отвори src/worker.js, я вижда. Константата отпада напълно —
# истинската тайна живее като Worker secret ADMIN_TOKEN, а KV admin:token
# остава само като преходен канал, докато секретът се разнесе.
#
# Идемпотентен: втори пуск не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'ADMIN_TOKEN' in s:
    print('SKIP: admin auth patch already applied'); sys.exit(0)

def rep(old, new, tag):
    global s
    if s.count(old) != 1:
        print('FAIL anchor (%d hits): %s' % (s.count(old), tag)); sys.exit(1)
    s = s.replace(old, new)
    print(' -', tag)

# 1) Публичната константа отпада
rep(
    "const ADMIN_PASSWORD = 'fishtaxi_admin_2026'; // Emil changes this later",
    "// ADMIN_PASSWORD е премахната: константа в публично repo не е тайна.\n"
    "// Админ достъпът се чете от Worker secret ADMIN_TOKEN (виж checkAdminPass).",
    'hardcoded ADMIN_PASSWORD removed'
)

# 2) Нова проверка: Worker secret първо, KV като преход, без трета опция
rep(
    """// Auth: hardcoded legacy tokens first (Emil = "1"), then KV token:{phone}
// Ако има admin:token в KV — ВАЖИ САМО ТОЙ (паролите са пенсионирани).
// Иначе: legacy режим (admin:password от KV или константата).
async function checkAdminPass(env, pass) {
  if (!pass) return false;
  const token = await env.GPS_STORE.get('admin:token');
  if (token) return pass === token;
  const stored = await env.GPS_STORE.get('admin:password');
  return pass === (stored || ADMIN_PASSWORD);
}""",
    """// Сравнение в постоянно време — за да не изтича дължина/съвпадение по време.
function adminSafeEq(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

// Ред на проверка:
//   1. Worker secret ADMIN_TOKEN — каноничният източник.
//   2. KV admin:token — преходно, докато секретът се разнесе навсякъде.
// Трета опция няма. Ако и двете липсват, админът е затворен — това е
// нарочно: по-добре заключена врата, отколкото врата с публичен ключ.
async function checkAdminPass(env, pass) {
  if (!pass) return false;
  if (env.ADMIN_TOKEN && adminSafeEq(pass, env.ADMIN_TOKEN)) return true;
  const token = await env.GPS_STORE.get('admin:token');
  if (token && adminSafeEq(pass, token)) return true;
  return false;
}""",
    'checkAdminPass -> Worker secret + timing-safe compare'
)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK  %d -> %d chars' % (n0, len(s)))
