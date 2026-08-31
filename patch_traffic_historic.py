# -*- coding: utf-8 -*-
"""Нов ендпойнт /traffic-historic — TomTom Routing API (calculateRoute) с
departAt + computeTravelTimeFor=all, за historicTrafficTravelTimeInSeconds.
Различен продукт от /traffic (Flow Segment Data) — дава изгладен "типична
седмица" профил, не изисква собствено събиране на живо.
Дели дневната TomTom квота (tt:count:{ден}, таван 2400) с /traffic.
"""
import sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()

if "'/traffic-historic'" in src:
    print('SKIP /traffic-historic вече е добавен')
    sys.exit(0)

ANCHOR = "    if (path === '/gps' && request.method === 'POST') {"
if ANCHOR not in src:
    print('FAIL котвата за /gps не е намерена')
    sys.exit(1)

BLOCK = """    if (path === '/traffic-historic' && request.method === 'GET') {
      try {
        let TT = env.TOMTOM_KEY || TT_KEY_CACHE;
        if (!TT && env.CONFIG_DB) {
          try {
            const row = await env.CONFIG_DB
              .prepare('SELECT v FROM secrets WHERE k = ?')
              .bind('TOMTOM_KEY').first();
            if (row && row.v) TT = row.v;
          } catch (e) {}
        }
        if (!TT) {
          try { TT = await env.GPS_STORE.get('TOMTOM_KEY'); } catch (e) {}
        }
        if (TT) TT_KEY_CACHE = TT;
        if (!TT) {
          return new Response(JSON.stringify({
              error: 'TOMTOM_KEY липсва',
              hint: 'очаква се в D1 CONFIG_DB.secrets, KV или Worker secret'
            }),
            { status: 503, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        const from = url.searchParams.get('from');
        const to = url.searchParams.get('to');
        const departAt = url.searchParams.get('departAt');
        if (!from || !to || !departAt) {
          return new Response(JSON.stringify({ error: 'missing ?from=lat,lng&to=lat,lng&departAt=ISO8601' }),
            { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        const fp = from.split(','), tp = to.split(',');
        const fla = parseFloat(fp[0]), fln = parseFloat(fp[1]);
        const tla = parseFloat(tp[0]), tln = parseFloat(tp[1]);
        if (!isFinite(fla) || !isFinite(fln) || !isFinite(tla) || !isFinite(tln)) {
          return new Response(JSON.stringify({ error: 'invalid from/to coordinates' }),
            { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        // Кеш по час, не по минута — историческият профил не се мени вътре в часа
        const hourKey = departAt.slice(0, 13);
        const ck = 'tth:' + fla.toFixed(4) + ',' + fln.toFixed(4) + '>' +
                   tla.toFixed(4) + ',' + tln.toFixed(4) + '@' + hourKey;
        const cached = await env.GPS_STORE.get(ck);
        if (cached && url.searchParams.get('fresh') !== '1') {
          return new Response(cached, { headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        // Споделя дневната квота с /traffic — общ таван 2400/ден за TomTom
        const TT_DAILY_CAP = 2400;
        const dayKey = 'tt:count:' + new Date().toISOString().slice(0, 10);
        let used = 0;
        try { used = parseInt((await env.GPS_STORE.get(dayKey)) || '0', 10) || 0; } catch (e) {}
        if (used >= TT_DAILY_CAP) {
          return new Response(JSON.stringify({ err: 'quota', used: used }),
            { status: 429, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        const ru = 'https://api.tomtom.com/routing/1/calculateRoute/'
                 + fla + ',' + fln + ':' + tla + ',' + tln + '/json'
                 + '?key=' + TT + '&traffic=true&routeType=fastest&travelMode=car'
                 + '&computeTravelTimeFor=all&departAt=' + encodeURIComponent(departAt);
        let item;
        try {
          const r = await fetch(ru, { cf: { cacheTtl: 3600, cacheEverything: true } });
          if (!r.ok) { item = { err: r.status }; }
          else {
            const d = await r.json();
            const s = (d.routes && d.routes[0] && d.routes[0].summary) || {};
            item = {
              departAt: departAt,
              travel_s: s.travelTimeInSeconds,
              free_s: s.noTrafficTravelTimeInSeconds,
              hist_s: (s.historicTrafficTravelTimeInSeconds != null) ? s.historicTrafficTravelTimeInSeconds : null,
              length_m: s.lengthInMeters,
            };
          }
        } catch (e) { item = { err: String(e).slice(0, 60) }; }
        if (!item.err) {
          try { await env.GPS_STORE.put(ck, JSON.stringify(item), { expirationTtl: 604800 }); } catch (e) {}
          try { await env.GPS_STORE.put(dayKey, String(used + 1), { expirationTtl: 172800 }); } catch (e) {}
        }
        return new Response(JSON.stringify(item),
          { headers: { ...CORS, 'Content-Type': 'application/json' } });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }),
          { status: 502, headers: { ...CORS, 'Content-Type': 'application/json' } });
      }
    }

"""

src = src.replace(ANCHOR, BLOCK + ANCHOR)
open(path, 'w', encoding='utf-8').write(src)
print('OK /traffic-historic добавен (KRES — Routing API departAt/hist_s)')
