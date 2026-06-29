// fish.taxi GPS Worker
// Endpoints:
//   POST /gps          — шофьорът праща локация
//   GET  /gps          — fish.taxi чете всички активни шофьори
//   POST /status       — шофьорът се включва/изключва (online/offline)
//   GET  /mvr          — стария MVR proxy (запазен)

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Content-Type': 'application/json; charset=utf-8',
};

// Secret tokens за всеки шофьор — само те могат да пращат GPS
// Format: "driver_id:token"
const DRIVER_TOKENS = {
  '1': 'fishtaxi_emil_2026_secret',  // Emil M.
};

// Шофьор се счита offline ако не е пратил GPS > 2 минути
const OFFLINE_AFTER_MS = 2 * 60 * 1000;

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    // ── POST /gps ── шофьорът праща локация ─────────────────
    if (path === '/gps' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { driver_id, token, lat, lng, online } = body;

        // Verify token
        if (!driver_id || !token || DRIVER_TOKENS[driver_id] !== token) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), {
            status: 401, headers: CORS
          });
        }

        // Validate coords
        if (typeof lat !== 'number' || typeof lng !== 'number') {
          return new Response(JSON.stringify({ error: 'Invalid coordinates' }), {
            status: 400, headers: CORS
          });
        }

        // Save to KV
        const data = {
          driver_id,
          lat,
          lng,
          online: online !== false,
          updated_at: Date.now(),
        };

        await env.GPS_STORE.put(`driver:${driver_id}`, JSON.stringify(data), {
          expirationTtl: 300  // auto-expire after 5 min if no updates
        });

        return new Response(JSON.stringify({ ok: true, updated_at: data.updated_at }), {
          headers: CORS
        });

      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: CORS
        });
      }
    }

    // ── GET /gps ── fish.taxi чете активните шофьори ─────────
    if (path === '/gps' && request.method === 'GET') {
      try {
        const list = await env.GPS_STORE.list({ prefix: 'driver:' });
        const drivers = [];
        const now = Date.now();

        for (const key of list.keys) {
          const raw = await env.GPS_STORE.get(key.name);
          if (!raw) continue;
          const d = JSON.parse(raw);
          // Mark as offline if no update for 2 min
          d.online = d.online && (now - d.updated_at) < OFFLINE_AFTER_MS;
          d.seconds_ago = Math.round((now - d.updated_at) / 1000);
          drivers.push(d);
        }

        return new Response(JSON.stringify({
          ok: true,
          count: drivers.length,
          online: drivers.filter(d => d.online).length,
          drivers,
          fetched_at: now,
        }), { headers: CORS });

      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: CORS
        });
      }
    }

    // ── POST /status ── online/offline toggle ─────────────────
    if (path === '/status' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { driver_id, token, online } = body;

        if (!driver_id || !token || DRIVER_TOKENS[driver_id] !== token) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), {
            status: 401, headers: CORS
          });
        }

        const raw = await env.GPS_STORE.get(`driver:${driver_id}`);
        const existing = raw ? JSON.parse(raw) : { driver_id, lat: 42.6977, lng: 23.3219 };
        existing.online = !!online;
        existing.updated_at = Date.now();

        await env.GPS_STORE.put(`driver:${driver_id}`, JSON.stringify(existing), {
          expirationTtl: online ? 300 : 86400
        });

        return new Response(JSON.stringify({
          ok: true,
          status: online ? 'online' : 'offline'
        }), { headers: CORS });

      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), {
          status: 500, headers: CORS
        });
      }
    }

    // ── GET / ── Health check ─────────────────────────────────
    if (path === '/' || path === '/health') {
      return new Response(JSON.stringify({
        service: 'fish.taxi GPS Worker',
        status: 'ok',
        version: '1.0',
        endpoints: ['GET /gps', 'POST /gps', 'POST /status'],
        time: new Date().toISOString(),
      }), { headers: CORS });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404, headers: CORS
    });
  }
};
