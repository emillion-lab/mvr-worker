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

// Normalize BG phone to digits-only international: 0888123456 → 359888123456
function normPhone(p) {
  let d = String(p || '').replace(/\D/g, '');
  if (d.startsWith('00')) d = d.slice(2);
  if (d.startsWith('0')) d = '359' + d.slice(1);
  return d;
}

function genToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return 'ft_' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

// Auth: hardcoded legacy tokens first (Emil = "1"), then KV token:{phone}
async function checkToken(env, driver_id, token) {
  if (!driver_id || !token) return false;
  if (DRIVER_TOKENS[driver_id] === token) return true;
  const stored = await env.GPS_STORE.get(`token:${normPhone(driver_id)}`);
  return stored !== null && stored === token;
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
        if (!(await checkToken(env, driver_id, token))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const did = DRIVER_TOKENS[driver_id] ? driver_id : normPhone(driver_id);
        const data = { driver_id: did, lat, lng, online: online !== false, updated_at: Date.now() };
        await env.GPS_STORE.put(`driver:${did}`, JSON.stringify(data), { expirationTtl: 300 });
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
        if (!(await checkToken(env, driver_id, token))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const did = DRIVER_TOKENS[driver_id] ? driver_id : normPhone(driver_id);
        const raw = await env.GPS_STORE.get(`driver:${did}`);
        const existing = raw ? JSON.parse(raw) : { driver_id: did, lat: 42.6977, lng: 23.3219 };
        existing.online = !!online;
        existing.updated_at = Date.now();
        await env.GPS_STORE.put(`driver:${did}`, JSON.stringify(existing), { expirationTtl: online ? 300 : 86400 });
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

    // ── Registration status + one-time token claim (за driver app) ──
    if (path === '/register/status' && request.method === 'GET') {
      const id = url.searchParams.get('id');
      if (!id) return new Response(JSON.stringify({ error: 'Missing id' }), { status: 400, headers: CORS });
      const claim = await env.GPS_STORE.get(`claim:${id}`);
      if (claim) {
        await env.GPS_STORE.delete(`claim:${id}`);
        const c = JSON.parse(claim);
        return new Response(JSON.stringify({ ok: true, status: 'approved', driver_id: c.driver_id, token: c.token }), { headers: CORS });
      }
      if (await env.GPS_STORE.get(`pending:${id}`)) {
        return new Response(JSON.stringify({ ok: true, status: 'pending' }), { headers: CORS });
      }
      if (await env.GPS_STORE.get(`approved:${id}`)) {
        return new Response(JSON.stringify({ ok: true, status: 'claimed' }), { headers: CORS });
      }
      return new Response(JSON.stringify({ ok: true, status: 'not_found' }), { headers: CORS });
    }

    // ── Admin панел (HTML) ────────────────────────────────
    if (path === '/admin' && request.method === 'GET') {
      const html = `<!DOCTYPE html><html lang="bg"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>fish.taxi Admin</title><style>
body{font-family:system-ui;background:#0B1220;color:#E6EDF3;margin:0;padding:16px;max-width:600px;margin:auto}
h1{font-size:20px}input{width:100%;padding:10px;border:1px solid #22C3A6;background:#141E33;color:#E6EDF3;border-radius:8px;box-sizing:border-box;margin-bottom:8px}
button{padding:10px 16px;border:0;border-radius:8px;font-weight:700;cursor:pointer;margin:4px 4px 4px 0}
.ok{background:#2E7D32;color:#fff}.no{background:#D32F2F;color:#fff}.load{background:#22C3A6;color:#0B1220}
.card{background:#141E33;border-radius:12px;padding:14px;margin:10px 0;border:1px solid #223}
.mu{color:#8899AA;font-size:13px}.tok{font-family:monospace;font-size:12px;background:#0B1220;padding:6px;border-radius:6px;word-break:break-all;margin-top:6px}
</style></head><body>
<h1>🐟 fish.taxi — Admin</h1>
<input id="pass" type="password" placeholder="Admin парола">
<button class="load" onclick="load()">Зареди заявки</button>
<div id="out"></div>
<h2 style="font-size:16px">Одобрени шофьори</h2><div id="appr" class="mu">—</div>
<script>
const W=location.origin;
function esc(s){return String(s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]))}
async function load(){
  const p=document.getElementById('pass').value;
  localStorage.setItem('ftp',p);
  const r=await fetch(W+'/admin/pending?pass='+encodeURIComponent(p)).then(r=>r.json());
  const out=document.getElementById('out');
  if(!r.ok){out.innerHTML='<p style="color:#D32F2F">Грешна парола</p>';return}
  out.innerHTML=r.records.length?'':'<p class="mu">Няма чакащи заявки</p>';
  for(const rec of r.records){
    const d=document.createElement('div');d.className='card';
    d.innerHTML='<b>'+esc(rec.name)+'</b> · '+esc(rec.phone)+'<br><span class="mu">'+esc(rec.car)+' · '+esc(rec.plate)+' · '+new Date(rec.created_at).toLocaleString('bg')+'</span><br>'+
      '<button class="ok" onclick="act(\''+rec.id+'\',\'approve\',this)">✓ Одобри</button>'+
      '<button class="no" onclick="act(\''+rec.id+'\',\'reject\',this)">✗ Откажи</button><div class="res"></div>';
    out.appendChild(d);
  }
  loadApproved(p);
}
async function loadApproved(p){
  const r=await fetch(W+'/admin/approved?pass='+encodeURIComponent(p)).then(r=>r.json());
  if(!r.ok)return;
  document.getElementById('appr').innerHTML=r.records.map(x=>'<div class="card"><b>'+esc(x.name)+'</b> · '+esc(x.phone)+'<br><span class="mu">'+esc(x.car)+' · '+esc(x.plate)+' · ID: '+esc(x.driver_id||'—')+'</span></div>').join('')||'—';
}
async function act(id,action,btn){
  const p=document.getElementById('pass').value;
  const r=await fetch(W+'/admin/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pass:p,id,action})}).then(r=>r.json());
  const res=btn.parentElement.querySelector('.res');
  if(r.ok&&action==='approve'){res.innerHTML='<div class="tok">✓ Одобрен. ID: '+esc(r.driver_id)+'<br>Token (резервно, app-ът си го взима сам): '+esc(r.token)+'</div>'}
  else if(r.ok){btn.parentElement.remove()}
  else{res.textContent='Грешка: '+(r.error||'?')}
}
if(localStorage.getItem('ftp')){document.getElementById('pass').value=localStorage.getItem('ftp')}
</script></body></html>`;
      return new Response(html, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    }

    // ── Admin панел (HTML) END ─────────────────────────────

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
          const phoneId = normPhone(record.phone);
          const driverToken = genToken();
          record.driver_id = phoneId;
          record.token = driverToken;
          await env.GPS_STORE.put(`token:${phoneId}`, driverToken);
          await env.GPS_STORE.put(`claim:${id}`, JSON.stringify({ driver_id: phoneId, token: driverToken }));
          await env.GPS_STORE.put(`approved:${id}`, JSON.stringify(record));
          await env.GPS_STORE.delete(`pending:${id}`);
          return new Response(JSON.stringify({ ok: true, driver_id: phoneId, token: driverToken }), { headers: CORS });
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
      return new Response(JSON.stringify({ service: 'fish.taxi Worker', status: 'ok', version: '2.2' }), { headers: CORS });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: CORS });
  }
};
