    // ── Generic scrape proxy (за bot-защитени сайтове; кеш 30 мин) ──
    if (path === '/scrape' && request.method === 'GET') {
      try {
        const target = url.searchParams.get('url');
        if (!target) return new Response(JSON.stringify({ error: 'missing ?url=' }), { status: 400, headers: CORS });
        // allowlist — само разрешени домейни, за да не е отворено прокси
        const ALLOW = ['eventim.bg', 'www.eventim.bg', 'public-api.eventim.com', 'ndk.bg', 'www.ndk.bg', 'bilet.bg', 'www.bilet.bg', 'api.bilet.bg', 'arenaarmeecsofia.net', 'www.arenaarmeecsofia.net', 'theatre.art.bg', 'www.theatre.art.bg', 'bgfutbol.com', 'www.bgfutbol.com', 'visitsofia.bg', 'www.visitsofia.bg', 'sofia.bg', 'www.sofia.bg'];
        let host;
        try { host = new URL(target).hostname; } catch (e) { return new Response(JSON.stringify({ error: 'bad url' }), { status: 400, headers: CORS }); }
        if (!ALLOW.includes(host)) return new Response(JSON.stringify({ error: 'host not allowed', host }), { status: 403, headers: CORS });
        const ck = 'scrape:' + target;
        const cached = await env.GPS_STORE.get(ck);
        if (cached && url.searchParams.get('fresh') !== '1') return new Response(cached, { headers: { ...CORS, 'X-Cache': 'HIT' } });
        const isApi = host === 'public-api.eventim.com' || host.startsWith('api.') || target.includes('/api/') || target.includes('graphql');
        const resp = await fetch(target, {
          headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
            'Accept': isApi ? 'application/json' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'bg-BG,bg;q=0.9,en;q=0.8',
          },
          cf: { cacheTtl: 1800, cacheEverything: true },
        });
        const body = await resp.text();
        if (resp.ok && body.length > 500) {
          try { await env.GPS_STORE.put(ck, body, { expirationTtl: 1800 }); } catch (e) {}
        }
        return new Response(body, { status: resp.status, headers: { ...CORS, 'Content-Type': (isApi ? 'application/json' : 'text/html') + '; charset=utf-8', 'X-Cache': 'MISS' } });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 502, headers: CORS });
      }
    }

