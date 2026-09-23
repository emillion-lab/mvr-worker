#!/usr/bin/env python3
"""FT-GPS-GHOST-V1
driver:{id} изтича (300 s след последен GPS, 24 ч след СТОП). Без него
GET /gps не връщаше шофьора и фронтендът го слагаше в центъра.
Всеки с token:{телефон} без жив driver: ключ се връща офлайн на базата си
(или на разпръснатата точка). Идемпотентен."""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'src/worker.js'
src = open(path, encoding='utf-8').read()
MARK = 'FT-GPS-GHOST-V1'
if MARK in src:
    print('already applied')
    sys.exit(0)

def rep(s, old, new):
    n = s.count(old)
    if n != 1:
        sys.exit(f'anchor x{n}: {old[:60]!r}')
    return s.replace(old, new)

src = rep(src,
"""        const drivers = [];
        const now = Date.now();
        for (const key of list.keys) {""",
"""        const drivers = [];
        const seen = new Set();
        const now = Date.now();
        for (const key of list.keys) {""")

src = rep(src,
"""          const pub = await maskIfOffline(env, d);""",
"""          seen.add(String(d.driver_id));
          const pub = await maskIfOffline(env, d);""")

src = rep(src,
"""          drivers.push(pub);
        }
        return new Response(JSON.stringify({ ok: true, count: drivers.length,""",
"""          drivers.push(pub);
        }
        /* FT-GPS-GHOST-V1: driver:{id} изтича (300 s / 24 ч след СТОП).
           Без него шофьорът падаше в центъра. Всеки с token: се връща
           офлайн на базата си, или на разпръснатата точка. */
        try {
          const toks = await env.GPS_STORE.list({ prefix: 'token:' });
          for (const k of toks.keys) {
            const did = k.name.slice('token:'.length);
            if (!/^359\\d{8,9}$/.test(did) || seen.has(did)) continue;
            drivers.push(await maskIfOffline(env, { driver_id: did, online: false, updated_at: null }));
          }
        } catch (e) {}
        return new Response(JSON.stringify({ ok: true, count: drivers.length,""")

open(path, 'w', encoding='utf-8').write(src)
print('patched')
