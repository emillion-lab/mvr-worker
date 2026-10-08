#!/usr/bin/env python3
"""FT-FLIGHTS-SEQ-V1 — /flights/ пита прозорците един след друг.

От 30.09.2026 вечерта API.market не приема две паралелни заявки: от
Promise.all оцеляваше само едната, а другата тихо ставаше null. Половин
денонощие изчезваше без грешка, а частичният отговор се кешираше за 60 мин
(без близки кацания TTL-ът решаваше, че „нищо не идва“) и се пазеше 24 ч
в flights:last.

Патчът:
  1. прозорците вървят последователно, пауза 1.5 с, един повторен опит
     при 429 / 5xx / мрежова грешка;
  2. отговорът носи windows: [{off, status, n}], partial, filled;
  3. частичен отговор се допълва от последния ПЪЛЕН (flights:full:{IATA})
     само за часовете на липсващия прозорец, кешира се 5 мин и никога не
     презаписва flights:full;
  4. квотата се брои само за успешните заявки.

Също така изпразва src/flights-snippet.js: deploy.yml го лепи преди /health,
но вграденият блок в worker.js е по-горе и винаги печели — снипетът е мъртъв
дубликат със същия бъг и не бива да може да възкръсне.

Идемпотентен: ако маркерът вече е вътре, не прави нищо.
"""
import sys

MARK = 'FT-FLIGHTS-SEQ-V1'
START = "    // ── Летищни пристигания (AeroDataBox през API.market, кеш 15 мин) ──\n"
END = "    // ── Generic scrape proxy"

NEW = r"""    // ── Летищни пристигания (AeroDataBox през API.market) ── FT-FLIGHTS-SEQ-V1
    // Прозорците се питат ЕДИН СЛЕД ДРУГ: от 30.09.2026 API.market не приема
    // две паралелни заявки и от Promise.all оцеляваше само едната.
    // Частичен отговор се допълва от последния пълен и не го презаписва.
    if (path.startsWith('/flights/') && request.method === 'GET') {
      try {
        const iata = (path.split('/')[2] || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3);
        if (iata.length !== 3) return new Response(JSON.stringify({ error: 'bad IATA code' }), { status: 400, headers: CORS });
        const debug = url.searchParams.get('debug') === '1';
        const fresh = url.searchParams.get('fresh') === '1';
        const ck = `flights:${iata}`;
        const lastKey = `flights:last:${iata}`;   // последно сервирано — за бюджетната спирачка
        const fullKey = `flights:full:${iata}`;   // последно ПЪЛНО — само от него се кърпи
        const DAY_BUDGET = 180;          // единици/ден (6000/мес ≈ 200/ден, с резерв)
        const dayKey = 'adb:used:' + new Date(Date.now() + 3*3600000).toISOString().slice(0,10);

        if (!debug && !fresh) {
          const cached = await env.GPS_STORE.get(ck);
          if (cached) return new Response(cached, { headers: CORS });
        }

        let usedToday = 0;
        try { usedToday = parseInt(await env.GPS_STORE.get(dayKey) || '0', 10); } catch (e) {}
        if (!fresh && usedToday >= DAY_BUDGET) {
          const last = await env.GPS_STORE.get(lastKey);
          if (last) {
            const obj = JSON.parse(last);
            obj.budgetHold = true;
            obj.adbToday = usedToday;
            return new Response(JSON.stringify(obj), { headers: CORS });
          }
        }
        const API_KEY = env.AERODATABOX_KEY || env['AERODATABOX КЕУ'] || env['AERODATABOX KEY'];
        if (!API_KEY) {
          return new Response(JSON.stringify({ error: 'AERODATABOX_KEY secret is not set on mvr-proxy' }), { status: 500, headers: CORS });
        }
        // ЦЯЛО ДЕНОНОЩИЕ: AeroDataBox дава макс. 12ч на заявка → две заявки и сливане
        const WINDOWS = [ { off: -180, dur: 720 }, { off: 540, dur: 720 } ];
        const base = `https://prod.api.market/api/v1/aedbx/aerodatabox/flights/airports/iata/${iata}`;
        const tail = `&direction=Arrival&withCancelled=true&withCodeshared=false&withLocation=false`;
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        const startMs = Date.now();
        const parts = [], windows = [];
        for (let i = 0; i < WINDOWS.length; i++) {
          const w = WINDOWS[i];
          if (i > 0) await sleep(1500);
          let st = null, body = null;
          for (let attempt = 0; attempt < 2; attempt++) {
            if (attempt > 0) await sleep(3000);
            try {
              const r = await fetch(`${base}?offsetMinutes=${w.off}&durationMinutes=${w.dur}${tail}`,
                { headers: { 'accept': 'application/json', 'x-magicapi-key': API_KEY } });
              st = r.status;
              if (r.ok) {
                body = await r.json().catch(() => null);
                if (!body) st = r.status + ':empty';
                break;                                   // 2xx: повторът няма да помогне
              }
              if (!(r.status === 429 || r.status >= 500)) break;   // 4xx: повторът няма да помогне
            } catch (e) {
              st = 'net:' + String(e && e.message || e).slice(0, 40);
            }
          }
          parts.push(body);
          windows.push({ off: w.off, status: st, n: body && body.arrivals ? body.arrivals.length : 0 });
        }
        const okCount = parts.filter(Boolean).length;
        if (!okCount) {
          return new Response(JSON.stringify({ error: 'AeroDataBox: и двата прозореца се провалиха', windows }), { status: 502, headers: CORS });
        }
        const partial = okCount < WINDOWS.length;
        const seen = new Set(), merged = [];
        parts.filter(Boolean).forEach(p => (p.arrivals || []).forEach(f => {
          const mv = f.movement || {};
          const key = (f.number || '') + '|' + ((mv.scheduledTime && mv.scheduledTime.local) || '');
          if (seen.has(key)) return;
          seen.add(key); merged.push(f);
        }));
        // debug=1 → връща суровия първи запис и статусите на прозорците
        if (debug) {
          const first = merged[0] || {};
          return new Response(JSON.stringify({ ok: true, windows, raw_first: first, keys: Object.keys(first), movement_keys: first.movement ? Object.keys(first.movement) : null }, null, 2), { headers: CORS });
        }
        const arrivals = merged.map(f => {
          const mv = f.movement || {};
          return {
            number: f.number,
            airline: f.airline && f.airline.name,
            from: mv.airport && (mv.airport.name || mv.airport.iata),
            scheduled: mv.scheduledTime && mv.scheduledTime.local,
            revised: mv.revisedTime && mv.revisedTime.local,
            terminal: mv.terminal || null,
            gate: mv.gate || null,
            baggage: mv.baggageBelt || null,
            status: f.status,
          };
        });
        const tsOf = (s) => new Date(String(s || '').replace(' ', 'T')).getTime();

        // Липсващ прозорец → неговите часове от последния ПЪЛЕН отговор.
        // Маркират се stale: разписанието е вярно, статусът може да е стар.
        let filled = 0;
        if (partial) {
          try {
            const fullRaw = await env.GPS_STORE.get(fullKey);
            if (fullRaw) {
              const full = JSON.parse(fullRaw);
              const have = new Set(arrivals.map(a => (a.number || '') + '|' + (a.scheduled || '')));
              WINDOWS.forEach((w, i) => {
                if (parts[i]) return;
                const from = startMs + w.off * 60000, to = from + w.dur * 60000;
                (full.arrivals || []).forEach(a => {
                  const ts = tsOf(a.scheduled);
                  if (!(ts >= from && ts < to)) return;
                  const k = (a.number || '') + '|' + (a.scheduled || '');
                  if (have.has(k)) return;
                  have.add(k);
                  arrivals.push(Object.assign({}, a, { stale: true }));
                  filled++;
                });
              });
            }
          } catch (e) {}
        }
        arrivals.sort((a, b) => {
          const ta = a.scheduled || '', tb = b.scheduled || '';
          return ta < tb ? -1 : ta > tb ? 1 : 0;
        });

        // Колко скоро има кацане → толкова често има смисъл да питаме
        const nowMs = Date.now();
        let nextIn = 1e9;
        arrivals.forEach(a => {
          const ts = tsOf(a.revised || a.scheduled);
          if (!isFinite(ts)) return;
          const d = ts - nowMs;
          if (d > -20*60000 && d < nextIn) nextIn = d;
        });
        const mins = nextIn / 60000;
        // Частичен отговор живее кратко: следващата заявка може да го допълни.
        // Иначе: близко кацане → пресни закъснения; мъртви часове → пестим.
        const TTL = partial      ? 300
                  : mins <= 45  ? 300     //  5 мин — полет каца скоро
                  : mins <= 120 ? 900     // 15 мин
                  : mins <= 240 ? 1800    // 30 мин
                  :               3600;   // 60 мин — нищо не идва

        // Броим само успешните заявки — отказаните не се таксуват.
        let usedNow = usedToday;
        try {
          usedNow = usedToday + okCount;
          await env.GPS_STORE.put(dayKey, String(usedNow), { expirationTtl: 40 * 86400 });
        } catch (e) {}

        const out = JSON.stringify({ ok: true, airport: iata, count: arrivals.length,
                                     updated: nowMs, adbToday: usedNow, ttl: TTL,
                                     nextInMin: Math.round(mins),
                                     partial, filled, windows, arrivals });
        try { await env.GPS_STORE.put(ck, out, { expirationTtl: TTL }); } catch (e) {}
        try { await env.GPS_STORE.put(lastKey, out, { expirationTtl: 86400 }); } catch (e) {}
        // 36 ч: далечният прозорец стига до +21 ч, кърпката трябва да го покрие
        if (!partial) {
          try { await env.GPS_STORE.put(fullKey, out, { expirationTtl: 129600 }); } catch (e) {}
        }
        return new Response(out, { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

"""

SNIPPET_STUB = (
    "    // flights-snippet.js е изпразнен с FT-FLIGHTS-SEQ-V1 (08.10.2026).\n"
    "    // Живият /flights/ е вграден в src/worker.js и стои преди тази точка,\n"
    "    // така че оттук никога не е стигал до заявка — беше мъртъв дубликат.\n"
)


def main(path):
    src = open(path, encoding='utf-8').read()
    if MARK in src:
        print('already patched')
    else:
        assert src.count(START) == 1, 'start anchor: %d' % src.count(START)
        assert src.count(END) == 1, 'end anchor: %d' % src.count(END)
        a = src.index(START)
        b = src.index(END)
        assert a < b, 'anchors out of order'
        old = src[a:b]
        assert "Promise.all(WINDOWS.map" in old, 'old block not what we expect'
        src = src[:a] + NEW + src[b:]
        assert src.count("path.startsWith('/flights/')") == 1
        open(path, 'w', encoding='utf-8').write(src)
        print('patched /flights/ (%d → %d bytes)' % (len(old), len(NEW)))

    snip = path.replace('worker.js', 'flights-snippet.js')
    try:
        cur = open(snip, encoding='utf-8').read()
        if cur != SNIPPET_STUB:
            open(snip, 'w', encoding='utf-8').write(SNIPPET_STUB)
            print('flights-snippet.js изпразнен')
    except FileNotFoundError:
        open(snip, 'w', encoding='utf-8').write(SNIPPET_STUB)
        print('flights-snippet.js създаден като празен')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'src/worker.js')
