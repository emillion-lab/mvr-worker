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
        // ЦЯЛО ДЕНОНОЩИЕ: AeroDataBox дава макс. 12ч на заявка → две заявки и сливане
        const WINDOWS = [ { off: -180, dur: 720 }, { off: 540, dur: 720 } ];
        const base = `https://prod.api.market/api/v1/aedbx/aerodatabox/flights/airports/iata/${iata}`;
        const tail = `&direction=Arrival&withCancelled=true&withCodeshared=false&withLocation=false`;
        const parts = await Promise.all(WINDOWS.map(w =>
          fetch(`${base}?offsetMinutes=${w.off}&durationMinutes=${w.dur}${tail}`,
                { headers: { 'accept': 'application/json', 'x-magicapi-key': API_KEY } })
            .then(r => r.ok ? r.json() : null).catch(() => null)
        ));
        if (!parts.some(Boolean)) {
          return new Response(JSON.stringify({ error: 'AeroDataBox: и двата прозореца се провалиха' }), { status: 502, headers: CORS });
        }
        const seen = new Set(), merged = [];
        parts.filter(Boolean).forEach(p => (p.arrivals || []).forEach(f => {
          const mv = f.movement || {};
          const key = (f.number || '') + '|' + ((mv.scheduledTime && mv.scheduledTime.local) || '');
          if (seen.has(key)) return;
          seen.add(key); merged.push(f);
        }));
        merged.sort((a, b) => {
          const ta = ((a.movement || {}).scheduledTime || {}).local || '';
          const tb = ((b.movement || {}).scheduledTime || {}).local || '';
          return ta < tb ? -1 : ta > tb ? 1 : 0;
        });
        const data = { arrivals: merged };
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

