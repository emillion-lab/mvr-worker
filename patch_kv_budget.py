#!/usr/bin/env python3
"""FT-KV-BUDGET-V1 (10.11.2026) — mvr-proxy пести KV операции.

Безплатният план: 1000 записа и 1000 list на ден, нулиране 00:00 UTC.
Преди: /gps GET правеше 2 list-а на всяка заявка, а fish.taxi пита на 15 сек
→ един отворен таб изяждаше list квотата за ~2 часа и картата изпразваше.
/presence и /track пишеха в KV на всяка заявка без никакъв лимит.

Сега:
  1. /gps GET чете шофьорите по списък от token: ключове. Всеки driver:{id}
     има token:{id} (checkToken го изисква), значи нищо не се губи. Списъкът
     се пази 2 мин в паметта и 30 мин в KV (idx:tokens) → най-много ~48
     list-а и ~48 записа на ден от този път, вместо хиляди list-ове.
     Отговорът се пази 5 сек в паметта — много зрители = една сметка.
     Разлика: отнет шофьор (няма token:) вече не излиза дори ако driver:
     ключът му още не е изтекъл.
  2. Одобрение, добавяне и отнемане на шофьор трият idx:tokens → новият
     се вижда до 2 мин.
  3. /presence POST и /track: лимит на IP и на инстанция в паметта.
     Над лимита отговорът е {ok:true, skipped:true}, без запис в KV.
  4. Съобщението за изчерпан лимит казва вярното време (00:00 UTC).

Идемпотентен: ако маркерът е вътре — нищо не прави. Всяка котва се
проверява да се среща точно толкова пъти, колкото се очаква; иначе exit 1
и деплоят спира, без да качи нищо.
"""
import sys

P = 'src/worker.js'
MARK = 'FT-KV-BUDGET-V1'
s = open(P, encoding='utf-8').read()
if MARK in s:
    print('FT-KV-BUDGET-V1: вече е приложен — SKIP')
    sys.exit(0)


def once(old, new, count=1):
    global s
    n = s.count(old)
    if n != count:
        print(f'КОТВАТА НЕ Е НАМЕРЕНА {count} път(и), а {n}:\n{old[:120]}')
        sys.exit(1)
    s = s.replace(old, new)


# ── 1. помощни функции преди export default ─────────────────────────────
once("export default {\n  async fetch(request, env) {",
'''/* ═══ FT-KV-BUDGET-V1 (10.11.2026) ═══
   Безплатният KV: 1000 записа и 1000 list на ден. Виж patch_kv_budget.py. */
const TOK_MEM_MS = 2 * 60 * 1000;      // списъкът с шофьори в паметта
const TOK_KV_MS  = 30 * 60 * 1000;     // и в KV (idx:tokens)
const GPS_MEM_MS = 5 * 1000;           // готовият /gps отговор в паметта
let _tokIds = null, _tokAt = 0;
let _gpsBody = null, _gpsAt = 0;

async function tokenIds(env) {
  const now = Date.now();
  if (_tokIds && now - _tokAt < TOK_MEM_MS) return _tokIds;
  try {
    const raw = await env.GPS_STORE.get('idx:tokens');
    if (raw) {
      const j = JSON.parse(raw);
      if (j && Array.isArray(j.ids) && now - (j.at || 0) < TOK_KV_MS) {
        _tokIds = j.ids; _tokAt = now;
        return _tokIds;
      }
    }
  } catch (e) {}
  const ids = [];
  let cursor;
  do {
    const r = await env.GPS_STORE.list({ prefix: 'token:', cursor });
    for (const k of r.keys) ids.push(k.name.slice('token:'.length));
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  _tokIds = ids; _tokAt = now;
  try { await env.GPS_STORE.put('idx:tokens', JSON.stringify({ at: now, ids })); } catch (e) {}
  return ids;
}

async function dropTokenIdx(env) {
  _tokIds = null; _gpsBody = null;
  try { await env.GPS_STORE.delete('idx:tokens'); } catch (e) {}
}

/* Лимит в паметта на инстанцията: не е глобален, но спира повторения
   от един адрес и случайни вълни, без да харчи KV. */
const _rl = new Map();
function overLimit(request, bucket, perIp, perInstance, windowMs) {
  const now = Date.now();
  const ip = request.headers.get('CF-Connecting-IP') || 'x';
  if (_rl.size > 5000) _rl.clear();
  let over = false;
  for (const [k, max] of [[bucket + '|' + ip, perIp], [bucket + '|*', perInstance]]) {
    let e = _rl.get(k);
    if (!e || now - e.t > windowMs) { e = { t: now, n: 0 }; _rl.set(k, e); }
    e.n++;
    if (e.n > max) over = true;
  }
  return over;
}

export default {
  async fetch(request, env) {''')

# ── 2. /gps GET без list на всяка заявка ────────────────────────────────
old_get_head = """    if (path === '/gps' && request.method === 'GET') {
      try {
        const list = await env.GPS_STORE.list({ prefix: 'driver:' });"""
start = s.find(old_get_head)
end_marker = "    /* Задаване на собствената база. Изисква драйвър токен. */"
end = s.find(end_marker, start)
if start < 0 or end < 0 or s.count(old_get_head) != 1 or s.count(end_marker) != 1:
    print('КОТВАТА за /gps GET не е намерена точно веднъж')
    sys.exit(1)
old_block = s[start:end]
# пазим се: старият блок трябва да е този, който познаваме
for must in ["list({ prefix: 'token:' })", 'maskIfOffline(env, d)',
             "drivers.filter(d => d.online).length"]:
    if must not in old_block:
        print('Старият /gps GET е различен от очаквания — липсва:', must)
        sys.exit(1)
new_block = """    if (path === '/gps' && request.method === 'GET') {
      try {
        /* FT-KV-BUDGET-V1: шофьорите по token: списъка (кеширан), без list
           на всяка заявка. Онлайн/запис първи, после призраците — както преди. */
        const nowMs = Date.now();
        if (_gpsBody && nowMs - _gpsAt < GPS_MEM_MS) {
          return new Response(_gpsBody, { headers: { ...CORS, 'X-Cache': 'MEM' } });
        }
        const ids = await tokenIds(env);
        const drivers = [], ghosts = [];
        for (const id of ids) {
          const raw = await env.GPS_STORE.get(`driver:${id}`);
          if (raw) {
            const d = JSON.parse(raw);
            d.online = d.online && (nowMs - d.updated_at) < OFFLINE_AFTER_MS;
            drivers.push(await maskIfOffline(env, d));
          } else if (/^359\\d{8,9}$/.test(id)) {
            ghosts.push(await maskIfOffline(env, { driver_id: id, online: false, updated_at: null }));
          }
        }
        const all = drivers.concat(ghosts);
        const body = JSON.stringify({ ok: true, count: all.length, online: all.filter(d => d.online).length, drivers: all });
        _gpsBody = body; _gpsAt = nowMs;
        return new Response(body, { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

"""
s = s[:start] + new_block + s[end:]

# ── 3. нов/отнет шофьор → списъкът се изчиства ──────────────────────────
once("await env.GPS_STORE.put(`token:${phoneId}`, driverToken);",
     "await env.GPS_STORE.put(`token:${phoneId}`, driverToken); await dropTokenIdx(env);",
     count=3)
once("await env.GPS_STORE.delete(`token:${phoneId}`);",
     "await env.GPS_STORE.delete(`token:${phoneId}`); await dropTokenIdx(env);")

# собствената позиция на шофьора да се види веднага, не след 5 сек
once("""          await env.GPS_STORE.put(`driver:${did}`, JSON.stringify(data), { expirationTtl: 300 });""",
     """          await env.GPS_STORE.put(`driver:${did}`, JSON.stringify(data), { expirationTtl: 300 });
          _gpsBody = null;""")

# ── 4. /presence POST и /track с лимит ──────────────────────────────────
once("""    if (path === '/track' && request.method === 'POST') {
      try {""",
"""    if (path === '/track' && request.method === 'POST') {
      try {
        if (overLimit(request, 'track', 30, 300, 10 * 60 * 1000)) {
          return new Response(JSON.stringify({ ok: true, skipped: true }), { headers: CORS });
        }""")
once("""    if (path === '/presence' && request.method === 'POST') {
      try {""",
"""    if (path === '/presence' && request.method === 'POST') {
      try {
        if (overLimit(request, 'presence', 3, 120, 10 * 60 * 1000)) {
          return new Response(JSON.stringify({ ok: true, skipped: true }), { headers: CORS });
        }""")

# ── 5. вярното време на нулиране ────────────────────────────────────────
once("Работи отново след 03:00 ч. българско време",
     "Работи отново след 00:00 UTC (02:00 зимно / 03:00 лятно българско време)")

open(P, 'w', encoding='utf-8').write(s)
print('FT-KV-BUDGET-V1: приложен')
