#!/usr/bin/env python3
# FT-BASE-SCATTER
# Офлайн шофьорите спират да се трупат в центъра на София.
# Без зададена base:{id} всеки пада на детерминирана точка от списък,
# със стабилно отместване — маркерът не подскача между заявките.
# Плюс /admin/base: админът задава база на шофьор без неговия токен.
import sys, io

path = sys.argv[1] if len(sys.argv) > 1 else 'src/worker.js'
s = io.open(path, encoding='utf-8').read()

if 'FT-BASE-SCATTER' in s:
    print('SKIP: вече е приложено')
    sys.exit(0)

OLD_CONST = "const BASE_FALLBACK = { lat: 42.6977, lng: 23.3219 };   // център на София"

NEW_CONST = """/* FT-BASE-SCATTER — без зададена база офлайн шофьорите се разпръскват.
   Точката е детерминирана по driver_id: една и съща при всяко зареждане,
   различна за различните шофьори, и не е центърът на града. */
const BASE_POINTS = [
  { lat: 42.6245, lng: 23.3521 },   // Ring Mall
  { lat: 42.6833, lng: 23.2890 },   // Лагера
  { lat: 42.6510, lng: 23.3760 },   // Младост
  { lat: 42.7180, lng: 23.2800 },   // Люлин
  { lat: 42.6690, lng: 23.2830 },   // Овча купел
  { lat: 42.7090, lng: 23.3320 },   // Централна гара
  { lat: 42.6660, lng: 23.3540 },   // Студентски град
  { lat: 42.7000, lng: 23.4030 }    // Дружба
];

function baseHash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

/* Постоянно отместване ±~160 м: двама в един квартал не се застъпват,
   но точката е една и съща при всяка заявка. */
function fallbackBase(did) {
  const h = baseHash(String(did || 'x'));
  const p = BASE_POINTS[h % BASE_POINTS.length];
  const dy = (((h >>> 8) & 0x1ff) - 256) / 170000;
  const dx = (((h >>> 20) & 0x1ff) - 256) / 130000;
  return { lat: Math.round((p.lat + dy) * 1e5) / 1e5,
           lng: Math.round((p.lng + dx) * 1e5) / 1e5 };
}"""

if OLD_CONST not in s:
    print('FAIL: липсва BASE_FALLBACK константата')
    sys.exit(1)
s = s.replace(OLD_CONST, NEW_CONST, 1)

OLD_RET = "  return BASE_FALLBACK;\n}"
NEW_RET = "  return fallbackBase(did);\n}"
if OLD_RET not in s:
    print('FAIL: липсва return BASE_FALLBACK в getBase')
    sys.exit(1)
s = s.replace(OLD_RET, NEW_RET, 1)

OLD_ST = "{ driver_id: did, lat: BASE_FALLBACK.lat, lng: BASE_FALLBACK.lng }"
NEW_ST = "Object.assign({ driver_id: did }, fallbackBase(did))"
if OLD_ST not in s:
    print('FAIL: липсва BASE_FALLBACK в /status')
    sys.exit(1)
s = s.replace(OLD_ST, NEW_ST, 1)

ANCHOR = "    // ── Admin: смяна на admin паролата ────────────────────"

ADMIN_BASE = """    // ── Admin: база на шофьор (FT-BASE-SCATTER) ───────────
    // Задава base:{id} без токена на шофьора. Без lat/lng трие базата
    // и връща шофьора на разпръснатата точка по подразбиране.
    if (path === '/admin/base' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { pass, driver_id, lat, lng } = body;
        if (!(await checkAdminPass(env, pass))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const did = normPhone(driver_id);
        if (!did) return new Response(JSON.stringify({ error: 'driver_id required' }), { status: 400, headers: CORS });
        if (lat == null && lng == null) {
          await env.GPS_STORE.delete(`base:${did}`);
          return new Response(JSON.stringify({ ok: true, cleared: true, base: fallbackBase(did) }), { headers: CORS });
        }
        if (typeof lat !== 'number' || typeof lng !== 'number') {
          return new Response(JSON.stringify({ error: 'lat and lng must be numbers' }), { status: 400, headers: CORS });
        }
        await env.GPS_STORE.put(`base:${did}`, JSON.stringify({ lat, lng }));
        return new Response(JSON.stringify({ ok: true, driver_id: did, base: { lat, lng } }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

"""

if ANCHOR not in s:
    print('FAIL: липсва котвата за /admin/base')
    sys.exit(1)
s = s.replace(ANCHOR, ADMIN_BASE + ANCHOR, 1)

s = s.replace("version: '2.8.1'", "version: '2.9.0'", 1)

io.open(path, 'w', encoding='utf-8').write(s)
print('OK: FT-BASE-SCATTER приложен')
