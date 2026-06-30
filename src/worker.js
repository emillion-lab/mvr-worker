// fish.taxi GPS + Registration Worker
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Content-Type': 'application/json; charset=utf-8',
};

const DRIVER_TOKENS = {
  '1': 'fishtaxi_emil_2026_secret',
};

const ADMIN_PASSWORD = 'fishtaxi_admin_2026'; // Emil changes this later
const OFFLINE_AFTER_MS = 2 * 60 * 1000;

function genId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: CORS });
    const url = new URL(request.url);
    const path = url.pathname;

    // ── GPS endpoints (existing) ──────────────────────────
    if (path === '/gps' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { driver_id, token, lat, lng, online } = body;
        if (!driver_id || !token || DRIVER_TOKENS[driver_id] !== token) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const data = { driver_id, lat, lng, online: online !== false, updated_at: Date.now() };
        await env.GPS_STORE.put(`driver:${driver_id}`, JSON.stringify(data), { expirationTtl: 300 });
        return new Response(JSON.stringify({ ok: true }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    if (path === '/gps' && request.method === 'GET') {
      try {
        const list = await env.GPS_STORE.list({ prefix: 'driver:' });
        const drivers = [];
        const now = Date.now();
        for (const key of list.keys) {
          const raw = await env.GPS_STORE.get(key.name);
          if (!raw) continue;
          const d = JSON.parse(raw);
          d.online = d.online && (now - d.updated_at) < OFFLINE_AFTER_MS;
          drivers.push(d);
        }
        return new Response(JSON.stringify({ ok: true, count: drivers.length, online: drivers.filter(d => d.online).length, drivers }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    if (path === '/status' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { driver_id, token, online } = body;
        if (!driver_id || !token || DRIVER_TOKENS[driver_id] !== token) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const raw = await env.GPS_STORE.get(`driver:${driver_id}`);
        const existing = raw ? JSON.parse(raw) : { driver_id, lat: 42.6977, lng: 23.3219 };
        existing.online = !!online;
        existing.updated_at = Date.now();
        await env.GPS_STORE.put(`driver:${driver_id}`, JSON.stringify(existing), { expirationTtl: online ? 300 : 86400 });
        return new Response(JSON.stringify({ ok: true }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── NEW: Driver registration ──────────────────────────
    if (path === '/register' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { name, phone, car, plate, city, photo_self, photo_car } = body;
        if (!name || !phone || !car || !plate) {
          return new Response(JSON.stringify({ error: 'Missing required fields' }), { status: 400, headers: CORS });
        }
        const id = genId();
        const record = {
          id, name, phone, car, plate, city: city || 'sofia',
          photo_self: photo_self || null,
          photo_car: photo_car || null,
          status: 'pending',
          created_at: Date.now(),
        };
        await env.GPS_STORE.put(`pending:${id}`, JSON.stringify(record));
        return new Response(JSON.stringify({ ok: true, id }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── NEW: Admin - list pending registrations ───────────
    if (path === '/admin/pending' && request.method === 'GET') {
      const pass = url.searchParams.get('pass');
      if (pass !== ADMIN_PASSWORD) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      try {
        const list = await env.GPS_STORE.list({ prefix: 'pending:' });
        const records = [];
        for (const key of list.keys) {
          const raw = await env.GPS_STORE.get(key.name);
          if (raw) records.push(JSON.parse(raw));
        }
        records.sort((a, b) => b.created_at - a.created_at);
        return new Response(JSON.stringify({ ok: true, records }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── NEW: Admin - approve/reject ───────────────────────
    if (path === '/admin/action' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { pass, id, action } = body;
        if (pass !== ADMIN_PASSWORD) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const raw = await env.GPS_STORE.get(`pending:${id}`);
        if (!raw) return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: CORS });
        const record = JSON.parse(raw);

        if (action === 'approve') {
          record.status = 'approved';
          record.approved_at = Date.now();
          await env.GPS_STORE.put(`approved:${id}`, JSON.stringify(record));
          await env.GPS_STORE.delete(`pending:${id}`);
        } else if (action === 'reject') {
          await env.GPS_STORE.delete(`pending:${id}`);
        }
        return new Response(JSON.stringify({ ok: true }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── NEW: Admin - list approved drivers ────────────────
    if (path === '/admin/approved' && request.method === 'GET') {
      const pass = url.searchParams.get('pass');
      if (pass !== ADMIN_PASSWORD) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      try {
        const list = await env.GPS_STORE.list({ prefix: 'approved:' });
        const records = [];
        for (const key of list.keys) {
          const raw = await env.GPS_STORE.get(key.name);
          if (raw) records.push(JSON.parse(raw));
        }
        return new Response(JSON.stringify({ ok: true, records }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    if (path === '/' || path === '/health') {
      return new Response(JSON.stringify({ service: 'fish.taxi Worker', status: 'ok', version: '2.0' }), { headers: CORS });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: CORS });
  }
};
