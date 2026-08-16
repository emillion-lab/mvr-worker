// fish.taxi GPS + Registration Worker
let TT_KEY_CACHE = null;

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Content-Type': 'application/json; charset=utf-8',
};

// DRIVER_TOKENS е премахната: константа в публично repo не е тайна.
// Единственият източник е KV: token:{normPhone(driver_id)}.

// ADMIN_PASSWORD е премахната: константа в публично repo не е тайна.
// Админ достъпът се чете от Worker secret ADMIN_TOKEN (виж checkAdminPass).
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

// Сравнение в постоянно време — за да не изтича дължина/съвпадение по време.
function adminSafeEq(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

// Ред на проверка:
//   1. Worker secret ADMIN_TOKEN — каноничният източник.
//   2. KV admin:token — преходно, докато секретът се разнесе навсякъде.
// Трета опция няма. Ако и двете липсват, админът е затворен — това е
// нарочно: по-добре заключена врата, отколкото врата с публичен ключ.
async function checkAdminPass(env, pass) {
  if (!pass) return false;
  if (env.ADMIN_TOKEN && adminSafeEq(pass, env.ADMIN_TOKEN)) return true;
  const token = await env.GPS_STORE.get('admin:token');
  if (token && adminSafeEq(pass, token)) return true;
  return false;
}

/* ─── FT-PRIVACY-BASE ───
   Офлайн шофьор не показва къде наистина е. Показва базата си.
   Домашният адрес не бива да се извежда от публично API. */
const BASE_FALLBACK = { lat: 42.6977, lng: 23.3219 };   // център на София

async function getBase(env, did) {
  try {
    const raw = await env.GPS_STORE.get(`base:${did}`);
    if (raw) {
      const b = JSON.parse(raw);
      if (typeof b.lat === 'number' && typeof b.lng === 'number') return b;
    }
  } catch (e) {}
  return BASE_FALLBACK;
}

/* Връща копие на записа с подменени координати, ако е офлайн. */
async function maskIfOffline(env, d) {
  if (d.online) return d;
  const base = await getBase(env, d.driver_id);
  return Object.assign({}, d, {
    lat: base.lat,
    lng: base.lng,
    approx: true,          // за интерфейса: това е база, не жива позиция
    at_base: true
  });
}

async function checkToken(env, driver_id, token) {
  if (!driver_id || !token) return false;
  const stored = await env.GPS_STORE.get(`token:${normPhone(driver_id)}`);
  if (stored === null) return false;
  return adminSafeEq(stored, token);
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
        const list = pts.split(';').slice(0, 20);
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
          // нощем (23:00–06:00 софийско) кешираме много по-дълго
          // TT_SCHEDULE — кешът следва натоварването на деня
          const sofiaH = (new Date().getUTCHours() + 3) % 24;
          let TT_TTL;
          if (sofiaH >= 23 || sofiaH < 6) TT_TTL = 3600;                    // нощ: 60 мин
          else if (sofiaH >= 21) TT_TTL = 1800;                             // късна вечер: 30 мин
          else if ((sofiaH >= 8 && sofiaH < 10) ||
                   (sofiaH >= 17 && sofiaH < 19)) TT_TTL = 300;             // пик: 5 мин
          else TT_TTL = 600;                                                // ден: 10 мин
          const TT_NIGHT = (TT_TTL >= 1800);
          // дневен предпазител за безплатната квота
          const TT_DAILY_CAP = 2400;
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
          const tu = 'https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/8/json'
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
            try { await env.GPS_STORE.put(ck, JSON.stringify(item), { expirationTtl: TT_TTL }); } catch (e) {}
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
        const did = normPhone(driver_id);
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
            if (prev.online === data.online && moved && dt < 40000) {
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
          /* дори да не е натиснат СТОП — щом е офлайн, точката се маскира */
          drivers.push(await maskIfOffline(env, d));
        }
        return new Response(JSON.stringify({ ok: true, count: drivers.length, online: drivers.filter(d => d.online).length, drivers }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    /* Задаване на собствената база. Изисква драйвър токен. */
    if (path === '/base' && request.method === 'POST') {
      try {
        const body = await request.json();
        const { driver_id, token, lat, lng } = body;
        if (!(await checkToken(env, driver_id, token))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
        }
        if (typeof lat !== 'number' || typeof lng !== 'number') {
          return new Response(JSON.stringify({ error: 'lat and lng must be numbers' }), { status: 400, headers: CORS });
        }
        const did = normPhone(driver_id);
        await env.GPS_STORE.put(`base:${did}`, JSON.stringify({ lat, lng }));
        return new Response(JSON.stringify({ ok: true, base: { lat, lng } }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    if (path === '/base' && request.method === 'GET') {
      try {
        const did = normPhone(url.searchParams.get('driver_id') || '');
        if (!did) return new Response(JSON.stringify({ error: 'driver_id required' }), { status: 400, headers: CORS });
        return new Response(JSON.stringify({ ok: true, base: await getBase(env, did) }), { headers: CORS });
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
        const did = normPhone(driver_id);
        const raw = await env.GPS_STORE.get(`driver:${did}`);
        const existing = raw ? JSON.parse(raw) : { driver_id: did, lat: BASE_FALLBACK.lat, lng: BASE_FALLBACK.lng };
        existing.online = !!online;
        existing.updated_at = Date.now();
        if (!existing.online) {
          /* СТОП: истинската точка не се запазва изобщо. */
          const base = await getBase(env, did);
          existing.lat = base.lat;
          existing.lng = base.lng;
          existing.approx = true;
          existing.at_base = true;
        } else {
          delete existing.approx;
          delete existing.at_base;
        }
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
        // ═══ RISK_V2 — калибрирано върху 4018 дни МВР (2015–2025) ═══
        // Геомагнитни бури, лунна фаза и Δ налягане са проверени и отпаднали.
        // Валежът е най-силният фактор (r=+0.366), следван от облачността.
        let rain = 0, snow = 0, tmin = null, tmax = null, wind = null, sun = null;
        try {
          const w = await fetch('https://api.open-meteo.com/v1/forecast?latitude=42.6977&longitude=23.3219'
            + '&daily=precipitation_sum,snowfall_sum,temperature_2m_min,temperature_2m_max,'
            + 'wind_speed_10m_max,sunshine_duration,daylight_duration&forecast_days=1&timezone=Europe%2FSofia');
          const d = (await w.json()).daily;
          rain = d.precipitation_sum?.[0] ?? 0;
          snow = d.snowfall_sum?.[0] ?? 0;
          tmin = d.temperature_2m_min?.[0]; tmax = d.temperature_2m_max?.[0];
          wind = d.wind_speed_10m_max?.[0];
          if (d.sunshine_duration?.[0] != null && d.daylight_duration?.[0])
            sun = d.sunshine_duration[0] / d.daylight_duration[0];
        } catch (e) {}

        const now = new Date(Date.now() + 3 * 3600000);   // София ≈ UTC+3
        const dow = now.getUTCDay(), mon = now.getUTCMonth() + 1, dom = now.getUTCDate();
        const hour = now.getUTCHours();

        const WD = [0.797,1.074,1.037,1.014,1.052,1.120,0.905];
        const MO = [0.943,0.916,0.888,0.923,0.963,1.056,1.088,1.106,1.063,1.065,1.013,0.970];
        const HWD = [1.007,0.942,1.046,0.959,0.939,1.004,1.102];
        const HMO = [0.741,0.736,0.791,0.861,1.001,1.154,1.263,1.319,1.148,1.032,1.008,0.927];
        const CUTS  = [0.837,0.926,0.987,1.038,1.078,1.122,1.175,1.289,1.474];
        const HCUTS = [0.771,0.894,0.977,1.047,1.123,1.200,1.253,1.333,1.411];

        let rEff = rain>=20?1.347 : rain>=10?1.200 : rain>=5?1.113
                 : rain>=2?1.044  : rain>=0.5?1.004 : 0.964;
        if (snow>=5) rEff=Math.max(rEff,1.404);
        else if (snow>=2) rEff=Math.max(rEff,1.243);
        else if (snow>=0.5) rEff=Math.max(rEff,1.052);

        let hR = rain>=20?1.301 : rain>=10?1.178 : rain>=5?1.062
               : rain>=2?1.019  : rain>=0.5?0.988 : 0.978;
        if (snow>=5) hR=Math.max(hR,1.239);
        else if (snow>=2) hR=Math.max(hR,1.106);
        else if (snow>=0.5) hR=Math.max(hR,0.957);

        const cEff = sun==null?1.0 : sun<0.15?1.175 : sun<0.35?1.071 : sun<0.55?1.026 : sun<0.75?0.999 : 0.975;
        const hC   = sun==null?1.0 : sun<0.15?1.142 : sun<0.35?1.043 : sun<0.55?0.948 : sun<0.75?0.979 : 0.988;
        const iEff = tmin==null?1.0 : (tmin<=0 && rain+snow>0.5)?1.18 : tmin<=-3?1.06 : tmin<=0?1.03 : 1.0;
        const wEff = wind==null?1.0 : wind>=60?1.09 : wind>=40?1.04 : 1.0;
        let aEff = 1.0;
        if (tmin!=null && tmax!=null && !(sun!=null && sun<0.6)) {
          const rg = tmax - tmin, spring = mon>=3 && mon<=5;
          if (rg>=17) aEff = spring?1.061:1.046; else if (rg>=14) aEff = spring?1.033:1.022;
        }
        let xEff = 1.0;
        if (mon===1) xEff = dom===1?0.547 : dom===2?0.774 : 1.0;
        else if (mon===12) xEff = dom===31?0.561 : dom>=27?0.85 : dom>=24?1.0
                                : dom===23?1.35 : dom>=21?1.22 : dom>=19?1.18 : dom>=16?1.12 : 1.0;

        // Пиковият час не е част от KAT — там данните са дневни и не могат да го
        // проверят — но за шофьор е реален, затова се запазва.
        const hEff = (hour >= 7 && hour <= 9) || (hour >= 16 && hour <= 19) ? 1.12
                   : (hour >= 22 || hour <= 4) ? 1.08 : 1.0;

        const common = iEff * wEff * aEff * xEff * hEff;
        const coef  = rEff * cEff * WD[dow]  * MO[mon-1]  * common;
        const hCoef = hR   * hC   * HWD[dow] * HMO[mon-1] * common;
        const sc = (m, cuts) => { let s=1; for (const c of cuts) if (m>=c) s++; return Math.min(10, s); };
        const score = sc(coef, CUTS), harmScore = sc(hCoef, HCUTS);
        const level = score <= 3 ? 0 : score <= 6 ? 1 : score <= 8 ? 2 : 3;
        const labels = ['Спокойна среда', 'Обичайно', 'Повишено внимание', 'Висок риск'];
        const result = JSON.stringify({
          ok: true, coefficient: Math.round(coef * 100) / 100, score, level, label: labels[level],
          car_score: score, harm_score: harmScore,
          harm_coefficient: Math.round(hCoef * 100) / 100,
          factors: { rain: Math.round(rain*10)/10, snow: Math.round(snow*10)/10,
                     cloud: sun==null?null:Math.round((1-sun)*100),
                     tmin, tmax, wind, dow, mon, hour, rush: hEff > 1.0 },
          model: 'KAT v3 · МВР 2015–2025',
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

    // ── Летищни пристигания (AeroDataBox през API.market, кеш 15 мин) ──
    if (path.startsWith('/flights/') && request.method === 'GET') {
      try {
        const iata = (path.split('/')[2] || '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 3);
        if (iata.length !== 3) return new Response(JSON.stringify({ error: 'bad IATA code' }), { status: 400, headers: CORS });
        const debug = url.searchParams.get('debug') === '1';
        const fresh = url.searchParams.get('fresh') === '1';
        const ck = `flights:${iata}`;
        const lastKey = `flights:last:${iata}`;
        const DAY_BUDGET = 180;          // единици/ден (6000/мес ≈ 200/ден, с резерв)
        const dayKey = 'adb:used:' + new Date(Date.now() + 3*3600000).toISOString().slice(0,10);

        if (!debug && !fresh) {
          const cached = await env.GPS_STORE.get(ck);
          if (cached) return new Response(cached, { headers: CORS });
        }

        // Бюджетна спирачка: при изчерпан дневен лимит сервираме последното
        // известно състояние вместо да харчим единици.
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
        // Колко скоро има кацане → толкова често има смисъл да питаме
        const nowMs = Date.now();
        let nextIn = 1e9;
        arrivals.forEach(a => {
          const s = a.revised || a.scheduled;
          if (!s) return;
          const ts = new Date(String(s).replace(' ', 'T')).getTime();
          const d = ts - nowMs;
          if (d > -20*60000 && d < nextIn) nextIn = d;
        });
        const mins = nextIn / 60000;
        // близко кацане → пресни закъснения; мъртви часове → пестим
        const TTL = mins <= 45  ? 300     //  5 мин — полет каца скоро
                  : mins <= 120 ? 900     // 15 мин
                  : mins <= 240 ? 1800    // 30 мин
                  :               3600;   // 60 мин — нищо не идва

        let usedNow = 0;
        try {
          usedNow = parseInt(await env.GPS_STORE.get(dayKey) || '0', 10) + 2;
          await env.GPS_STORE.put(dayKey, String(usedNow), { expirationTtl: 40 * 86400 });
        } catch (e) {}

        const out = JSON.stringify({ ok: true, airport: iata, count: arrivals.length,
                                     updated: nowMs, adbToday: usedNow, ttl: TTL,
                                     nextInMin: Math.round(mins), arrivals });
        try { await env.GPS_STORE.put(ck, out, { expirationTtl: TTL }); } catch (e) {}
        // дълготрайно резервно копие за бюджетната спирачка
        try { await env.GPS_STORE.put(lastKey, out, { expirationTtl: 86400 }); } catch (e) {}
        return new Response(out, { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── Generic scrape proxy (за bot-защитени сайтове; кеш 30 мин) ──
    if (path === '/scrape' && request.method === 'GET') {
      try {
        const target = url.searchParams.get('url');
        if (!target) return new Response(JSON.stringify({ error: 'missing ?url=' }), { status: 400, headers: CORS });
        // allowlist — само разрешени домейни, за да не е отворено прокси
        const ALLOW = ['eventim.bg', 'www.eventim.bg', 'public-api.eventim.com', 'ndk.bg', 'www.ndk.bg', 'bilet.bg', 'www.bilet.bg', 'arenaarmeecsofia.net', 'www.arenaarmeecsofia.net', 'theatre.art.bg', 'www.theatre.art.bg', 'gong.bg', 'www.gong.bg', 'visitsofia.bg', 'www.visitsofia.bg', 'sofia.bg', 'www.sofia.bg', 'live.bdz.bg', 'razpisanie.bdz.bg', 'bdz.bg', 'www.bdz.bg', 'centralnaavtogara.bg', 'www.centralnaavtogara.bg'];
        let host;
        try { host = new URL(target).hostname; } catch (e) { return new Response(JSON.stringify({ error: 'bad url' }), { status: 400, headers: CORS }); }
        if (!ALLOW.includes(host)) return new Response(JSON.stringify({ error: 'host not allowed', host }), { status: 403, headers: CORS });
        const ck = 'scrape:' + target;
        const cached = await env.GPS_STORE.get(ck);
        if (cached && url.searchParams.get('fresh') !== '1') return new Response(cached, { headers: { ...CORS, 'X-Cache': 'HIT' } });
        const isApi = host === 'public-api.eventim.com' || host.startsWith('api.') || target.includes('/api/') || target.includes('graphql');
        // live таблата не се кешират дълго — данните са в реално време
        const liveHost = host === 'live.bdz.bg';
        const ttl = liveHost ? 120 : 1800;
        const resp = await fetch(target, {
          headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
            'Accept': isApi ? 'application/json' : 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'bg-BG,bg;q=0.9,en;q=0.8',
          },
          cf: { cacheTtl: ttl, cacheEverything: true },
        });
        const body = await resp.text();
        if (resp.ok && body.length > 500) {
          try { await env.GPS_STORE.put(ck, body, { expirationTtl: ttl }); } catch (e) {}
        }
        return new Response(body, { status: resp.status, headers: { ...CORS, 'Content-Type': (isApi ? 'application/json' : 'text/html') + '; charset=utf-8', 'X-Cache': 'MISS' } });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 502, headers: CORS });
      }
    }

    // ── GitHub Actions dispatch ───────────────────────────
    // Пуска workflow в emillion-lab без Cloudflare dashboard и без
    // локален git. Пази се с DISPATCH_KEY: без правилен ключ връща 401,
    // защото токенът отдолу може да пише в репата.
    //   GET  /dispatch?key=…&repo=FISHTAXI&workflow=build-registry.yml
    //   GET  /dispatch?key=…&repo=FISHTAXI              → списък workflow-и
    //   GET  /dispatch?key=…&repo=FISHTAXI&runs=1       → последни изпълнения
    if (path === '/dispatch') {
      const key = url.searchParams.get('key') || '';
      if (!env.DISPATCH_KEY || key !== env.DISPATCH_KEY) {
        return new Response(JSON.stringify({ error: 'unauthorized' }), { status: 401, headers: CORS });
      }
      const tok = env.GH_TOKEN;
      if (!tok) {
        return new Response(JSON.stringify({ error: 'GH_TOKEN not configured on the worker' }), { status: 500, headers: CORS });
      }
      const owner = env.GH_OWNER || 'emillion-lab';
      const repo = url.searchParams.get('repo');
      if (!repo) {
        return new Response(JSON.stringify({ error: 'repo parameter required' }), { status: 400, headers: CORS });
      }
      const wf = url.searchParams.get('workflow');
      const ref = url.searchParams.get('ref') || 'main';
      const H = {
        'Authorization': 'Bearer ' + tok,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'mvr-proxy-dispatch',
        'X-GitHub-Api-Version': '2022-11-28'
      };
      const api = 'https://api.github.com/repos/' + owner + '/' + repo + '/actions';

      try {
        // последни изпълнения — за проверка след пускане
        if (url.searchParams.get('runs')) {
          const u = wf
            ? api + '/workflows/' + encodeURIComponent(wf) + '/runs?per_page=5'
            : api + '/runs?per_page=5';
          const r = await fetch(u, { headers: H });
          const d = await r.json();
          if (!r.ok) {
            return new Response(JSON.stringify({ error: d.message || 'github error', status: r.status }), { status: r.status, headers: CORS });
          }
          return new Response(JSON.stringify({
            ok: true,
            runs: (d.workflow_runs || []).map(x => ({
              name: x.name, status: x.status, conclusion: x.conclusion,
              branch: x.head_branch, created_at: x.created_at, url: x.html_url
            }))
          }), { headers: CORS });
        }

        // без workflow → изброй наличните
        if (!wf) {
          const r = await fetch(api + '/workflows?per_page=100', { headers: H });
          const d = await r.json();
          if (!r.ok) {
            return new Response(JSON.stringify({ error: d.message || 'github error', status: r.status }), { status: r.status, headers: CORS });
          }
          return new Response(JSON.stringify({
            ok: true,
            workflows: (d.workflows || []).map(w => ({
              name: w.name, file: w.path.split('/').pop(), state: w.state
            }))
          }), { headers: CORS });
        }

        // същинският dispatch — GitHub връща 204 без тяло
        const body = { ref };
        const inputsRaw = url.searchParams.get('inputs');
        if (inputsRaw) {
          try { body.inputs = JSON.parse(inputsRaw); } catch (e) {}
        }
        const r = await fetch(api + '/workflows/' + encodeURIComponent(wf) + '/dispatches', {
          method: 'POST', headers: { ...H, 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        if (r.status === 204) {
          return new Response(JSON.stringify({
            ok: true, action: 'queued', repo, workflow: wf, ref,
            watch: 'https://github.com/' + owner + '/' + repo + '/actions/workflows/' + wf
          }), { headers: CORS });
        }
        const txt = await r.text();
        let msg = txt;
        try { msg = (JSON.parse(txt).message) || txt; } catch (e) {}
        // 422 обикновено значи, че workflow-ът няма 'on: workflow_dispatch'
        return new Response(JSON.stringify({ error: msg, status: r.status }), { status: r.status, headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 502, headers: CORS });
      }
    }

    if (path === '/' || path === '/health') {
      return new Response(JSON.stringify({ service: 'fish.taxi Worker', status: 'ok', version: '2.8.1' }), { headers: CORS });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), { status: 404, headers: CORS });
  }
};