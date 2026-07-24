// fish.taxi GPS + Registration Worker
let TT_KEY_CACHE = null;

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
// Ако има admin:token в KV — ВАЖИ САМО ТОЙ (паролите са пенсионирани).
// Иначе: legacy режим (admin:password от KV или константата).
async function checkAdminPass(env, pass) {
  if (!pass) return false;
  const token = await env.GPS_STORE.get('admin:token');
  if (token) return pass === token;
  const stored = await env.GPS_STORE.get('admin:password');
  return pass === (stored || ADMIN_PASSWORD);
}

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
    // ── TomTom трафик по отсечки (кеш 3 мин; ключът е Worker secret) ──
    if (path === '/traffic' && request.method === 'GET') {
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
          // дневен предпазител за безплатната квота
          const TT_DAILY_CAP = 2200;
          const dayKey = 'tt:count:' + new Date().toISOString().slice(0, 10);
          let used = 0;
          try { used = parseInt((await env.GPS_STORE.get(dayKey)) || '0', 10) || 0; } catch (e) {}
          if (used >= TT_DAILY_CAP) {
            let stale = null;
            try { stale = await env.GPS_STORE.get('tt:last:' + ck); } catch (e) {}
            if (stale) { try { out.push(JSON.parse(stale)); continue; } catch (e) {} }
            out.push({ err: 'quota', used: used });
            continue;
          }
          const tu = 'https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json'
                   + '?key=' + TT + '&point=' + la + ',' + ln + '&unit=KMPH';
          let item;
          try {
            const r = await fetch(tu, { cf: { cacheTtl: 120, cacheEverything: true } });
            if (!r.ok) { item = { err: r.status }; }
            else {
              const d = await r.json();
              const f = (d && d.flowSegmentData) || {};
              const cur = f.currentSpeed, free = f.freeFlowSpeed;
              const rawC = (f.coordinates && f.coordinates.coordinate) || [];
              // прореждаме до ~90 точки, за да не тежи в KV
              const step = rawC.length > 90 ? Math.ceil(rawC.length / 90) : 1;
              const coords = [];
              for (let i = 0; i < rawC.length; i += step) {
                const c = rawC[i];
                if (c && c.latitude != null) {
                  coords.push([Math.round(c.latitude * 1e5) / 1e5,
                               Math.round(c.longitude * 1e5) / 1e5]);
                }
              }
              if (rawC.length && coords.length && step > 1) {
                const last = rawC[rawC.length - 1];
                if (last && last.latitude != null) {
                  coords.push([Math.round(last.latitude * 1e5) / 1e5,
                               Math.round(last.longitude * 1e5) / 1e5]);
                }
              }
              item = { cur: cur, free: free, curT: f.currentTravelTime, freeT: f.freeFlowTravelTime,
                       conf: f.confidence, closed: !!f.roadClosure, frc: f.frc,
                       ratio: (free ? Math.round((cur / free) * 100) / 100 : null),
                       coords: coords };
            }
          } catch (e) { item = { err: String(e).slice(0, 60) }; }
          if (!item.err) {
            try { await env.GPS_STORE.put(ck, JSON.stringify(item), { expirationTtl: 240 }); } catch (e) {}
            // резервен запис за 24ч — ползва се ако свърши квотата
            try { await env.GPS_STORE.put('tt:last:' + ck, JSON.stringify(item), { expirationTtl: 86400 }); } catch (e) {}
            try { await env.GPS_STORE.put(dayKey, String(used + 1), { expirationTtl: 172800 }); } catch (e) {}
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

    if (path === '/gps' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { driver_id, token, lat, lng, online } = body;
        if (!(await checkToken(env, driver_id, token))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const did = DRIVER_TOKENS[driver_id] ? driver_id : normPhone(driver_id);
        const data = { driver_id: did, lat, lng, online: online !== false, updated_at: Date.now() };
        // Дедуп: ако сме писали < 45 сек и позицията е почти същата — не хабим запис
        try {
          const prevRaw = await env.GPS_STORE.get(`driver:${did}`);
          if (prevRaw) {
            const prev = JSON.parse(prevRaw);
            const dt = Date.now() - (prev.updated_at || 0);
            const dLat = Math.abs((prev.lat || 0) - lat), dLng = Math.abs((prev.lng || 0) - lng);
            const moved = (dLat + dLng) > 0.0007; // ~60-70 м
            // Движеща се кола: пишем на всеки цикъл. Паркирала: heartbeat само на 4 мин.
            if (prev.online === data.online && !moved && dt < 240000) {
              return new Response(JSON.stringify({ ok: true, skipped: true }), { headers: CORS });
            }
            if (prev.online === data.online && moved && dt < 25000) {
              return new Response(JSON.stringify({ ok: true, skipped: true }), { headers: CORS });
            }
          }
        } catch (e) {}
        try {
          await env.GPS_STORE.put(`driver:${did}`, JSON.stringify(data), { expirationTtl: 300 });
        } catch (e) {
          if (String(e).includes('limit')) {
            return new Response(JSON.stringify({ error: 'Дневният лимит за GPS записи е изчерпан (Cloudflare free план). Работи отново след 03:00 ч. българско време, или трайно с Workers Paid ($5/мес).', quota: true }), { status: 503, headers: CORS });
          }
          throw e;
        }
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
      if (!(await checkAdminPass(env, pass))) {
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
        if (!(await checkAdminPass(env, pass))) {
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
      if (!(await checkAdminPass(env, pass))) {
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


    // ── Admin: директно създаване на шофьор (на доверие) ──
    if (path === '/admin/add' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { pass, name, phone, car, plate } = body;
        if (!(await checkAdminPass(env, pass))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        if (!name || !phone) return new Response(JSON.stringify({ error: 'Missing name/phone' }), { status: 400, headers: CORS });
        const id = genId();
        const phoneId = normPhone(phone);
        const driverToken = genToken();
        const record = { id, name, phone, car: car || '', plate: plate || '', city: 'sofia',
          status: 'approved', driver_id: phoneId, token: driverToken,
          created_at: Date.now(), approved_at: Date.now() };
        await env.GPS_STORE.put(`token:${phoneId}`, driverToken);
        await env.GPS_STORE.put(`approved:${id}`, JSON.stringify(record));
        return new Response(JSON.stringify({ ok: true, driver_id: phoneId, token: driverToken }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── Admin: нов token за шофьор ("смяна на парола") ────
    if (path === '/admin/retoken' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { pass, driver_id } = body;
        if (!(await checkAdminPass(env, pass))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const phoneId = normPhone(driver_id);
        const existing = await env.GPS_STORE.get(`token:${phoneId}`);
        if (!existing) return new Response(JSON.stringify({ error: 'Driver not found' }), { status: 404, headers: CORS });
        const driverToken = genToken();
        await env.GPS_STORE.put(`token:${phoneId}`, driverToken);
        return new Response(JSON.stringify({ ok: true, driver_id: phoneId, token: driverToken }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── Admin: изтриване на шофьор ────────────────────────
    if (path === '/admin/revoke' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { pass, driver_id } = body;
        if (!(await checkAdminPass(env, pass))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const phoneId = normPhone(driver_id);
        await env.GPS_STORE.delete(`token:${phoneId}`);
        await env.GPS_STORE.delete(`driver:${phoneId}`);
        const list = await env.GPS_STORE.list({ prefix: 'approved:' });
        for (const key of list.keys) {
          const raw = await env.GPS_STORE.get(key.name);
          if (raw && JSON.parse(raw).driver_id === phoneId) await env.GPS_STORE.delete(key.name);
        }
        return new Response(JSON.stringify({ ok: true }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── Admin: смяна на admin паролата ────────────────────
    if (path === '/admin/password' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { pass, new_pass } = body;
        if (!(await checkAdminPass(env, pass))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        if (!new_pass || new_pass.length < 8) {
          return new Response(JSON.stringify({ error: 'Password min 8 chars' }), { status: 400, headers: CORS });
        }
        await env.GPS_STORE.put('admin:password', new_pass);
        return new Response(JSON.stringify({ ok: true }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }


    // ── Риск коефициент (KAT логика, кеш 30 мин) ──────────
    if (path === '/risk' && request.method === 'GET') {
      try {
        const cached = await env.GPS_STORE.get('risk:current');
        if (cached) {
          return new Response(cached, { headers: { ...CORS, 'Content-Type': 'application/json' } });
        }
        // Kp от NOAA
        let kp = 2;
        try {
          const kpResp = await fetch('https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json');
          const kpData = await kpResp.json();
          kp = parseFloat(kpData[kpData.length - 1][1]) || 2;
        } catch (e) {}
        // Налягане София: сега vs преди 24ч (Open-Meteo, безплатно)
        let dp = 0;
        try {
          const pResp = await fetch('https://api.open-meteo.com/v1/forecast?latitude=42.6977&longitude=23.3219&hourly=surface_pressure&past_days=1&forecast_days=1');
          const pData = await pResp.json();
          const hrs = pData.hourly.surface_pressure;
          const nowIdx = new Date().getUTCHours() + 24;
          dp = Math.abs((hrs[nowIdx] || 0) - (hrs[nowIdx - 24] || 0));
        } catch (e) {}
        // Лунна възраст (локална математика)
        const moonAge = ((Date.now() / 86400000 - 10957.5 + 4.867) % 29.53 + 29.53) % 29.53;
        const now = new Date(Date.now() + 3 * 3600000); // София ≈ UTC+3 лято
        const dow = now.getUTCDay();
        const hour = now.getUTCHours();
        // KAT формули
        const kpEff = kp >= 7.5 ? 0.95 : kp >= 6 ? 1.08 : kp >= 5 ? 1.14 : kp >= 3 ? 1.05 : 1.0;
        const pEff = dp >= 10 ? 1.14 : dp >= 5 ? 1.08 : dp >= 2 ? 1.03 : 1.0;
        const mNorm = Math.abs(Math.sin((moonAge / 29.53) * Math.PI));
        const mEff = mNorm > 0.85 ? 1.06 : mNorm > 0.6 ? 1.03 : 1.0;
        const dEff = [0.82, 0.88, 0.93, 0.98, 1.28, 1.22, 0.78][dow] || 1.0;
        const inter = (kp >= 5 && dp >= 10) ? 1.08 : 1.0;
        // Пиков час (добавка за шофьори)
        const hEff = (hour >= 7 && hour <= 9) || (hour >= 16 && hour <= 19) ? 1.12
                   : (hour >= 22 || hour <= 4) ? 1.08 : 1.0;
        const coef = kpEff * pEff * mEff * dEff * inter * hEff;
        const score = Math.min(10, Math.max(0, Math.round((coef - 0.8) * 12)));
        const level = score <= 2 ? 0 : score <= 5 ? 1 : score <= 7 ? 2 : 3;
        const labels = ['Спокойна среда', 'Леко напрежение', 'Повишен стрес', 'Критично'];
        const result = JSON.stringify({
          ok: true, coefficient: Math.round(coef * 100) / 100, score, level, label: labels[level],
          factors: { kp: Math.round(kp * 10) / 10, pressure_delta: Math.round(dp * 10) / 10,
                     moon_age: Math.round(moonAge * 10) / 10, dow, hour, rush: hEff > 1.0 },
          kat_url: 'https://emillion-lab.github.io/KAT/', updated: Date.now()
        });
        try { await env.GPS_STORE.put('risk:current', result, { expirationTtl: 2400 }); } catch (e) {}
        return new Response(result, { headers: { ...CORS, 'Content-Type': 'application/json' } });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false, error: e.message }), { status: 500, headers: CORS });
      }
    }


    // ── Admin: редакция на чакаща заявка ──────────────────
    if (path === '/admin/update' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { pass, id, name, phone, car, plate } = body;
        if (!(await checkAdminPass(env, pass))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const raw = await env.GPS_STORE.get(`pending:${id}`);
        if (!raw) return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: CORS });
        const rec = JSON.parse(raw);
        if (name) rec.name = name;
        if (phone) rec.phone = phone;
        if (car !== undefined) rec.car = car;
        if (plate !== undefined) rec.plate = plate;
        await env.GPS_STORE.put(`pending:${id}`, JSON.stringify(rec));
        return new Response(JSON.stringify({ ok: true, record: rec }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── Admin: ротация на token (нов, стар умира) ─────────
    if (path === '/admin/rotate-token' && request.method === 'POST') {
      try {
        const body = await request.json();
        if (!(await checkAdminPass(env, body.pass))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        const bytes = crypto.getRandomValues(new Uint8Array(16));
        const t = 'fta_' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
        await env.GPS_STORE.put('admin:token', t);
        return new Response(JSON.stringify({ ok: true, token: t }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }


    // ── Analytics beacon (без бисквитки, без трети страни) ──
    if (path === '/track' && request.method === 'POST') {
      try {
        const body = await request.json();
        const ev = String(body.event || '').replace(/[^a-z_]/g, '').slice(0, 24);
        if (!ev) return new Response(JSON.stringify({ ok: false }), { status: 400, headers: CORS });
        const day = new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10);
        const key = `stats:${day}:${ev}`;
        const cur = parseInt(await env.GPS_STORE.get(key) || '0', 10);
        try { await env.GPS_STORE.put(key, String(cur + 1), { expirationTtl: 40 * 86400 }); } catch (e) {}
        return new Response(JSON.stringify({ ok: true }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false }), { status: 500, headers: CORS });
      }
    }

    // ── Анонимно клиентско присъствие (загрубено, TTL 10 мин) ──
    if (path === '/presence' && request.method === 'POST') {
      try {
        const body = await request.json();
        let { lat, lng } = body;
        lat = Math.round(parseFloat(lat) * 1000) / 1000; // ~110 м
        lng = Math.round(parseFloat(lng) * 1000) / 1000;
        if (!isFinite(lat) || !isFinite(lng)) return new Response(JSON.stringify({ ok: false }), { status: 400, headers: CORS });
        // само около София
        if (Math.abs(lat - 42.7) > 0.6 || Math.abs(lng - 23.32) > 0.9) {
          return new Response(JSON.stringify({ ok: true, ignored: true }), { headers: CORS });
        }
        try { await env.GPS_STORE.put(`presence:${genId()}`, JSON.stringify({ lat, lng, t: Date.now() }), { expirationTtl: 600 }); } catch (e) {}
        return new Response(JSON.stringify({ ok: true }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ ok: false }), { status: 500, headers: CORS });
      }
    }

    // ── Шофьор: живи клиентски точки (изисква driver token) ──
    if (path === '/presence' && request.method === 'GET') {
      const driver_id = url.searchParams.get('driver_id');
      const token = url.searchParams.get('token');
      if (!(await checkToken(env, driver_id, token))) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      const list = await env.GPS_STORE.list({ prefix: 'presence:' });
      const dots = [];
      for (const k of list.keys.slice(0, 50)) {
        const raw = await env.GPS_STORE.get(k.name);
        if (raw) dots.push(JSON.parse(raw));
      }
      return new Response(JSON.stringify({ ok: true, count: dots.length, dots }), { headers: CORS });
    }

    // ── Admin: статистика 14 дни ─────────────────────────
    if (path === '/admin/stats' && request.method === 'GET') {
      const pass = url.searchParams.get('pass');
      if (!(await checkAdminPass(env, pass))) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      const out = {};
      for (let i = 0; i < 14; i++) {
        const day = new Date(Date.now() + 3 * 3600000 - i * 86400000).toISOString().slice(0, 10);
        const list = await env.GPS_STORE.list({ prefix: `stats:${day}:` });
        const row = {};
        for (const k of list.keys) {
          const ev = k.name.split(':')[2];
          row[ev] = parseInt(await env.GPS_STORE.get(k.name) || '0', 10);
        }
        if (Object.keys(row).length) out[day] = row;
      }
      return new Response(JSON.stringify({ ok: true, days: out }), { headers: CORS });
    }

    if (path === '/mvrfetch') {
      // Passthrough към mvr.bg и chitanka.info (Грамофонче) — GitHub Actions IP-тата са блокирани, Cloudflare минава
      const target = url.searchParams.get('u') || '';
      let t;
      try { t = new URL(target); } catch { return new Response(JSON.stringify({ error: 'bad url' }), { status: 400, headers: CORS }); }
      const ALLOWED = [/(^|\.)mvr\.bg$/, /(^|\.)chitanka\.info$/, /(^|\.)eventim\.bg$/, /(^|\.)theatre\.art\.bg$/];
      if (!ALLOWED.some(re => re.test(t.hostname))) {
        return new Response(JSON.stringify({ error: 'host not allowed' }), { status: 403, headers: CORS });
      }
      const upstream = await fetch(t.toString(), {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36',
          'Accept-Language': 'bg-BG,bg;q=0.9',
          'Accept': 'text/html,application/xhtml+xml',
        },
        cf: { cacheTtl: 900, cacheEverything: true },
      });
      const body = await upstream.text();
      return new Response(body, { status: upstream.status, headers: { ...CORS, 'Content-Type': 'text/html; charset=utf-8' } });
    }

    if (path === '/' || path === '/health') {
      return new Response(JSON.stringify({ service: 'fish.taxi Worker', status: 'ok', version: '2.8.1' }), { headers: CORS });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: CORS });
  }
};
