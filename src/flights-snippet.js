    // ── Летищни пристигания (AeroDataBox през API.market, кеш 15 мин) ──
    if (path.startsWith('/flights/') && request.method === 'GET') {
      try {
        const iata = (path.split('/')[2] || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3);
        if (iata.length !== 3) return new Response(JSON.stringify({ error: 'bad IATA code' }), { status: 400, headers: CORS });
        const debug = url.searchParams.get('debug') === '1';
        const ck = `flights:${iata}`;
        if (!debug) {
          const cached = await env.GPS_STORE.get(ck);
          if (cached) return new Response(cached, { headers: CORS });
        }
        const API_KEY = env.AERODATABOX_KEY || env['AERODATABOX КЕУ'] || env['AERODATABOX KEY'];
        if (!API_KEY) {
          return new Response(JSON.stringify({ error: 'AERODATABOX_KEY secret is not set on mvr-proxy' }), { status: 500, headers: CORS });
        }
        const u = `https://prod.api.market/api/v1/aedbx/aerodatabox/flights/airports/iata/${iata}?offsetMinutes=-90&durationMinutes=360&direction=Arrival&withCancelled=true&withCodeshared=false&withLocation=false`;
        const resp = await fetch(u, { headers: { 'accept': 'application/json', 'x-magicapi-key': API_KEY } });
        if (!resp.ok) {
          const txt = await resp.text();
          return new Response(JSON.stringify({ error: 'AeroDataBox HTTP ' + resp.status, detail: txt.slice(0, 300) }), { status: 502, headers: CORS });
        }
        const data = await resp.json();
        // debug=1 → връща суровия първи запис, за да видим къде е терминалът
        if (debug) {
          const first = (data.arrivals || [])[0] || {};
          return new Response(JSON.stringify({ ok: true, raw_first: first, keys: Object.keys(first), movement_keys: first.movement ? Object.keys(first.movement) : null }, null, 2), { headers: CORS });
        }
        const arrivals = (data.arrivals || []).map(f => {
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
        const out = JSON.stringify({ ok: true, airport: iata, count: arrivals.length, updated: Date.now(), arrivals });
        try { await env.GPS_STORE.put(ck, out, { expirationTtl: 900 }); } catch (e) {}
        return new Response(out, { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

