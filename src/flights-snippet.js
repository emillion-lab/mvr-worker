    // ── Летищни пристигания (AeroDataBox през API.market, кеш 15 мин) ──
    if (path.startsWith('/flights/') && request.method === 'GET') {
      try {
        const iata = (path.split('/')[2] || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3);
        if (iata.length !== 3) return new Response(JSON.stringify({ error: 'bad IATA code' }), { status: 400, headers: CORS });
        const ck = `flights:${iata}`;
        const cached = await env.GPS_STORE.get(ck);
        if (cached) return new Response(cached, { headers: CORS });
        // Приема и грешно именуван secret с кирилица/интервал ("AERODATABOX КЕУ")
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
        const arrivals = (data.arrivals || []).map(f => ({
          number: f.number,
          airline: f.airline && f.airline.name,
          from: f.movement && f.movement.airport && (f.movement.airport.name || f.movement.airport.iata),
          scheduled: f.movement && f.movement.scheduledTime && f.movement.scheduledTime.local,
          revised: f.movement && f.movement.revisedTime && f.movement.revisedTime.local,
          status: f.status,
        }));
        const out = JSON.stringify({ ok: true, airport: iata, count: arrivals.length, updated: Date.now(), arrivals });
        try { await env.GPS_STORE.put(ck, out, { expirationTtl: 900 }); } catch (e) {}
        return new Response(out, { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

