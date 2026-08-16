# -*- coding: utf-8 -*-
# mvr-proxy · домашният адрес спира да изтича
#
# ПРОБЛЕМЪТ (истински, не хипотетичен):
#   Апът праща GPS на всеки 30 секунди, докато си ONLINE. Натиснеш ли СТОП
#   вкъщи, /status запазва ПОСЛЕДНИТЕ ТИ КООРДИНАТИ и ги държи 86400 секунди
#   — цяло денонощие. /gps GET ги раздава публично на всеки, без никаква
#   автентикация. Тоест адресът, от който си тръгнал сутринта, стои отворен
#   за четене от всеки, който отвори един URL.
#
# РЕШЕНИЕТО:
#   Офлайн вече не се публикува истинска точка. Показва се „база" —
#   точка, която шофьорът сам избира (паркинг, търговски център, каквото
#   реши). Ако не е избрал, пада на центъра на София.
#   Точната позиция съществува само докато си ONLINE, и то с TTL 300s.
#
#   Маскирането е на ДВЕ места нарочно:
#     1. при /status offline — записът се презаписва още при заявката
#     2. при /gps GET — за всеки, който е изтекъл в офлайн сам (без СТОП)
#   Второто хваща случая „забравил си да натиснеш СТОП".
#
#   Нов ендпойнт /base (с драйвър токен) — шофьорът си задава базата сам.
#
# Идемпотентен.
import io, sys

p = sys.argv[1] if len(sys.argv) > 1 else 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'FT-PRIVACY-BASE' in s:
    print('SKIP: privacy patch already applied'); sys.exit(0)

def rep(old, new, tag, expect=1):
    global s
    if s.count(old) != expect:
        print('FAIL anchor (%d hits, expected %d): %s' % (s.count(old), expect, tag))
        sys.exit(1)
    s = s.replace(old, new)
    print(' -', tag)

# ── 1. Помощните функции ───────────────────────────────────────────
rep(
    "async function checkToken(env, driver_id, token) {",
    """/* ─── FT-PRIVACY-BASE ───
   Офлайн шофьор не показва къде наистина е. Показва базата си.
   Домашният адрес не бива да се извежда от публично API. */
const BASE_FALLBACK = { lat: 42.6977, lng: 23.3219 };   // център на София

async function getBase(env, did) {
  try {
    const raw = await env.GPS_STORE.get(`base:${did}`);
    if (raw) {
      const b = JSON.parse(raw);
      if (typeof b.lat === 'number' && typeof b.lng === 'number') return b;
    }
  } catch (e) {}
  return BASE_FALLBACK;
}

/* Връща копие на записа с подменени координати, ако е офлайн. */
async function maskIfOffline(env, d) {
  if (d.online) return d;
  const base = await getBase(env, d.driver_id);
  return Object.assign({}, d, {
    lat: base.lat,
    lng: base.lng,
    approx: true,          // за интерфейса: това е база, не жива позиция
    at_base: true
  });
}

async function checkToken(env, driver_id, token) {""",
    'помощни функции за базата'
)

# ── 2. /status: офлайн презаписва точката веднага ──────────────────
rep(
    """        const did = normPhone(driver_id);
        const raw = await env.GPS_STORE.get(`driver:${did}`);
        const existing = raw ? JSON.parse(raw) : { driver_id: did, lat: 42.6977, lng: 23.3219 };
        existing.online = !!online;
        existing.updated_at = Date.now();
        await env.GPS_STORE.put(`driver:${did}`, JSON.stringify(existing), { expirationTtl: online ? 300 : 86400 });""",
    """        const did = normPhone(driver_id);
        const raw = await env.GPS_STORE.get(`driver:${did}`);
        const existing = raw ? JSON.parse(raw) : { driver_id: did, lat: BASE_FALLBACK.lat, lng: BASE_FALLBACK.lng };
        existing.online = !!online;
        existing.updated_at = Date.now();
        if (!existing.online) {
          /* СТОП: истинската точка не се запазва изобщо. */
          const base = await getBase(env, did);
          existing.lat = base.lat;
          existing.lng = base.lng;
          existing.approx = true;
          existing.at_base = true;
        } else {
          delete existing.approx;
          delete existing.at_base;
        }
        await env.GPS_STORE.put(`driver:${did}`, JSON.stringify(existing), { expirationTtl: online ? 300 : 86400 });""",
    '/status маскира при офлайн'
)

# ── 3. /gps GET: хваща и тихо изтеклите в офлайн ───────────────────
rep(
    """          const d = JSON.parse(raw);
          d.online = d.online && (now - d.updated_at) < OFFLINE_AFTER_MS;
          drivers.push(d);""",
    """          const d = JSON.parse(raw);
          d.online = d.online && (now - d.updated_at) < OFFLINE_AFTER_MS;
          /* дори да не е натиснат СТОП — щом е офлайн, точката се маскира */
          drivers.push(await maskIfOffline(env, d));""",
    '/gps маскира при офлайн'
)

# ── 4. /base: шофьорът си задава базата ────────────────────────────
rep(
    "    if (path === '/status' && request.method === 'POST') {",
    """    /* Задаване на собствената база. Изисква драйвър токен. */
    if (path === '/base' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { driver_id, token, lat, lng } = body;
        if (!(await checkToken(env, driver_id, token))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        if (typeof lat !== 'number' || typeof lng !== 'number') {
          return new Response(JSON.stringify({ error: 'lat and lng must be numbers' }), { status: 400, headers: CORS });
        }
        const did = normPhone(driver_id);
        await env.GPS_STORE.put(`base:${did}`, JSON.stringify({ lat, lng }));
        return new Response(JSON.stringify({ ok: true, base: { lat, lng } }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    if (path === '/base' && request.method === 'GET') {
      try {
        const did = normPhone(url.searchParams.get('driver_id') || '');
        if (!did) return new Response(JSON.stringify({ error: 'driver_id required' }), { status: 400, headers: CORS });
        return new Response(JSON.stringify({ ok: true, base: await getBase(env, did) }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    if (path === '/status' && request.method === 'POST') {""",
    'ендпойнт /base'
)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK  %d -> %d chars' % (n0, len(s)))
