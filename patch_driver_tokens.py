# -*- coding: utf-8 -*-
# mvr-proxy · драйвър токените излизат от кода.
#
# Защо: repo-то е ПУБЛИЧНО, а DRIVER_TOKENS държеше жив токен като константа.
# Всеки, който отвори src/worker.js, може да праща GPS от името на шофьор 1.
# Единственият източник остава KV: token:{normPhone(driver_id)}.
#
# ПРЕДПОСТАВКА: KV ключът token:1 вече съществува. Без него шофьор 1 остава вън.
# Идемпотентен: втори пуск не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'DRIVER_TOKENS' not in s:
    print('SKIP: driver tokens patch already applied'); sys.exit(0)

def rep(old, new, tag, expect=1):
    global s
    if s.count(old) != expect:
        print('FAIL anchor (%d hits, expected %d): %s' % (s.count(old), expect, tag))
        sys.exit(1)
    s = s.replace(old, new)
    print(' -', tag)

# 1) Самата константа отпада
rep(
    "const DRIVER_TOKENS = {\n  '1': 'fishtaxi_emil_2026_secret',\n};\n\n",
    "// DRIVER_TOKENS е премахната: константа в публично repo не е тайна.\n"
    "// Единственият източник е KV: token:{normPhone(driver_id)}.\n\n",
    'hardcoded DRIVER_TOKENS removed'
)

# 2) checkToken: само KV, с timing-safe сравнение
rep(
    """async function checkToken(env, driver_id, token) {
  if (!driver_id || !token) return false;
  if (DRIVER_TOKENS[driver_id] === token) return true;
  const stored = await env.GPS_STORE.get(`token:${normPhone(driver_id)}`);
  return stored !== null && stored === token;
}""",
    """async function checkToken(env, driver_id, token) {
  if (!driver_id || !token) return false;
  const stored = await env.GPS_STORE.get(`token:${normPhone(driver_id)}`);
  if (stored === null) return false;
  return adminSafeEq(stored, token);
}""",
    'checkToken -> KV only + timing-safe'
)

# 3) Двете места, които решаваха id-то през константата
rep(
    "const did = DRIVER_TOKENS[driver_id] ? driver_id : normPhone(driver_id);",
    "const did = normPhone(driver_id);",
    'did resolution (2x)', expect=2
)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK  %d -> %d chars' % (n0, len(s)))
