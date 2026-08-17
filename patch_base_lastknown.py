#!/usr/bin/env python3
# FT-BASE-LASTKNOWN
# Офлайн шофьор без зададена база вече не сяда на измислена точка:
# показва последната си известна позиция, но загрубена до ~1 км решетка
# с постоянно отместване по driver_id (за да не се застъпват двама).
# Шофьор със зададена base:{id} излиза точно на нея (Емил → Ring Mall).
import sys, io

path = sys.argv[1] if len(sys.argv) > 1 else 'src/worker.js'
s = io.open(path, encoding='utf-8').read()

if 'FT-BASE-LASTKNOWN' in s:
    print('SKIP: вече е приложено')
    sys.exit(0)

if 'FT-BASE-SCATTER' not in s:
    print('FAIL: липсва FT-BASE-SCATTER — пусни първо Patch Base Scatter')
    sys.exit(1)

# 1. getBase спира да лъже с фолбек — връща null, ако няма зададена база.
OLD_RET = "  return fallbackBase(did);\n}"
NEW_RET = "  return null;\n}"
if OLD_RET not in s:
    print('FAIL: липсва return fallbackBase(did) в getBase')
    sys.exit(1)
s = s.replace(OLD_RET, NEW_RET, 1)

# 2. Нова маскировка: база, иначе загрубен last known.
start = s.find('async function maskIfOffline')
if start == -1:
    print('FAIL: липсва maskIfOffline')
    sys.exit(1)
end = s.find('\n}\n', start)
if end == -1:
    print('FAIL: не намирам края на maskIfOffline')
    sys.exit(1)

NEW_MASK = """async function maskIfOffline(env, d) {
  if (d.online) return d;
  /* FT-BASE-LASTKNOWN
     1) има зададена база → точно тя;
     2) няма → последната известна точка, загрубена до ~1 км;
     3) няма и позиция → разпръснатата резервна точка. */
  const base = await getBase(env, d.driver_id);
  if (base) {
    return Object.assign({}, d, { lat: base.lat, lng: base.lng, approx: true, at_base: true });
  }
  if (typeof d.lat !== 'number' || typeof d.lng !== 'number') {
    const f = fallbackBase(d.driver_id);
    return Object.assign({}, d, { lat: f.lat, lng: f.lng, approx: true, at_base: true });
  }
  const c = coarsen(d.driver_id, d.lat, d.lng);
  return Object.assign({}, d, { lat: c.lat, lng: c.lng, approx: true, at_base: false });
}

/* ~1 км решетка + постоянно отместване ±~300 м по driver_id.
   Точният адрес не излиза през публичното API, но кварталът се вижда. */
function coarsen(did, lat, lng) {
  const h = baseHash(String(did || 'x'));
  const dy = (((h >>> 8) & 0xff) - 128) / 45000;
  const dx = (((h >>> 20) & 0xff) - 128) / 33000;
  return { lat: Math.round((Math.round(lat * 100) / 100 + dy) * 1e5) / 1e5,
           lng: Math.round((Math.round(lng * 100) / 100 + dx) * 1e5) / 1e5 };
}"""

s = s[:start] + NEW_MASK + s[end + 2:]

# 3. При СТОП вече не се презаписва позицията, освен ако има база.
OLD_STOP = """          /* СТОП: истинската точка не се запазва изобщо. */
          const base = await getBase(env, did);
          existing.lat = base.lat;
          existing.lng = base.lng;
          existing.approx = true;
          existing.at_base = true;"""
NEW_STOP = """          /* СТОП: с база — сядаме на нея. Без база — пазим последната
             точка, но навън тя излиза загрубена (maskIfOffline). */
          const base = await getBase(env, did);
          if (base) {
            existing.lat = base.lat;
            existing.lng = base.lng;
            existing.at_base = true;
          }
          existing.approx = true;"""
if OLD_STOP not in s:
    print('FAIL: липсва СТОП блокът в /status')
    sys.exit(1)
s = s.replace(OLD_STOP, NEW_STOP, 1)

# 4. GET /base вече може да върне null — това е валиден отговор.
OLD_GET = "{ ok: true, base: await getBase(env, did) }"
NEW_GET = "{ ok: true, base: await getBase(env, did), fallback: fallbackBase(did) }"
if OLD_GET in s:
    s = s.replace(OLD_GET, NEW_GET, 1)

s = s.replace("version: '2.9.0'", "version: '2.9.1'", 1)

io.open(path, 'w', encoding='utf-8').write(s)
print('OK: FT-BASE-LASTKNOWN приложен')
