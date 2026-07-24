# -*- coding: utf-8 -*-
"""Добавя /traffic ендпойнт в worker.js — TomTom Flow Segment Data.
Ключът НЕ е в кода: чете се от env.TOMTOM_KEY (Worker secret).
Кеш 3 минути в KV, за да пестим от безплатната квота (2500/ден)."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()

if "path === '/traffic'" in src:
    print('SKIP /traffic вече съществува')
    sys.exit(0)

anchor = "    if (path === '/scrape' && request.method === 'GET') {"
if src.count(anchor) != 1:
    # по-хлабав опит
    m = re.search(r"\n(\s*)if \(path === '/scrape'", src)
    if not m:
        print('FAIL котвата /scrape не е намерена')
        sys.exit(1)
    anchor = m.group(0)[1:]

BLOCK = """    // ── TomTom трафик по отсечки (кеш 3 мин; ключът е Worker secret) ──
    if (path === '/traffic' && request.method === 'GET') {
      try {
        if (!env.TOMTOM_KEY) {
          return new Response(JSON.stringify({ error: 'TOMTOM_KEY не е зададен в worker-а' }),
            { status: 503, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        const pts = url.searchParams.get('pts');
        if (!pts) {
          return new Response(JSON.stringify({ error: 'missing ?pts=lat,lng;lat,lng' }),
            { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        const list = pts.split(';').slice(0, 12);
        const out = [];
        for (const p of list) {
          const parts = p.split(',');
          const la = parseFloat(parts[0]), ln = parseFloat(parts[1]);
          if (!isFinite(la) || !isFinite(ln)) { out.push(null); continue; }
          const ck = 'tt:' + la.toFixed(4) + ',' + ln.toFixed(4);
          const cached = await env.GPS_STORE.get(ck);
          if (cached && url.searchParams.get('fresh') !== '1') {
            try { out.push(JSON.parse(cached)); continue; } catch (e) {}
          }
          const tu = 'https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json'
                   + '?key=' + env.TOMTOM_KEY + '&point=' + la + ',' + ln + '&unit=KMPH';
          let item;
          try {
            const r = await fetch(tu, { cf: { cacheTtl: 120, cacheEverything: true } });
            if (!r.ok) { item = { err: r.status }; }
            else {
              const d = await r.json();
              const f = (d && d.flowSegmentData) || {};
              const cur = f.currentSpeed, free = f.freeFlowSpeed;
              item = {
                cur: cur, free: free,
                curT: f.currentTravelTime, freeT: f.freeFlowTravelTime,
                conf: f.confidence, closed: !!f.roadClosure,
                ratio: (free ? Math.round((cur / free) * 100) / 100 : null)
              };
            }
          } catch (e) { item = { err: String(e).slice(0, 60) }; }
          if (!item.err) {
            try { await env.GPS_STORE.put(ck, JSON.stringify(item), { expirationTtl: 180 }); } catch (e) {}
          }
          out.push(item);
        }
        return new Response(JSON.stringify({ updated: new Date().toISOString(), data: out }),
          { headers: { ...CORS, 'Content-Type': 'application/json' } });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }),
          { status: 502, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }
    }

"""

src = src.replace(anchor, BLOCK + anchor, 1)
open(path, 'w', encoding='utf-8').write(src)
print('OK /traffic добавен преди /scrape')
