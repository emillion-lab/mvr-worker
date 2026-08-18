# -*- coding: utf-8 -*-
# mvr-proxy · admin панелът се пренаписва + нов /admin/drivers
#
# ЗАЩО:
# 1. Панелът беше мъртъв. JS-ът му живее в template literal, а кавичките в
#    inline onclick бяха екранирани с една наклонена черта. Вътре в template
#    literal това е валиден escape и се свежда до гола кавичка, тъй че в
#    сервираната страница оставаха два залепени стринга без оператор →
#    SyntaxError → целият <script> не се парсва → бутонът не прави нищо и
#    не се появява никакво съобщение. Затова inline onclick отпада напълно
#    и се минава на DOM listener-и: няма кавички в стрингове, няма капан.
# 2. Всяка грешка се поглъщаше. fetch().then(r=>r.json()) без try/catch
#    хвърля в async функция и умира тихо. Сега се показва HTTP статусът.
# 3. Панелът не показваше реалните шофьори. approved:* съществува само за
#    минали през заявка или /admin/add. Вписаните направо в KV (Емил, Петър)
#    бяха невидими — а те са тези, които карат. Истината за „кой има достъп"
#    е token:*, затова новият /admin/drivers чете нея.
# 4. /admin/password записваше KV admin:password, който checkAdminPass
#    вече изобщо не чете. Мъртъв ендпойнт, който може да те заключи по
#    погрешка — маха се.
#
# Идемпотентен: втори пуск не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'ADMIN_PANEL_V2' in s:
    print('SKIP: admin panel patch already applied'); sys.exit(0)


def rep(old, new, tag):
    global s
    c = s.count(old)
    if c != 1:
        print('FAIL anchor (%d hits): %s' % (c, tag)); sys.exit(1)
    s = s.replace(old, new)
    print(' -', tag)


# ─────────────────────────────────────────────────────────────
# 1) Целият панел: HTML тяло + скрипт
# ─────────────────────────────────────────────────────────────
OLD_PANEL = r""".mu{color:#8899AA;font-size:13px}.tok{font-family:monospace;font-size:12px;background:#0B1220;padding:6px;border-radius:6px;word-break:break-all;margin-top:6px}
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
</script></body></html>"""

NEW_PANEL = r""".mu{color:#8899AA;font-size:13px}.tok{font-family:monospace;font-size:12px;background:#0B1220;padding:6px;border-radius:6px;word-break:break-all;margin-top:6px}
.err{color:#D32F2F;font-weight:700}.okc{color:#22C3A6;font-weight:700}
h2{font-size:15px;color:#8899AA;text-transform:uppercase;letter-spacing:.5px;margin:22px 0 6px}
</style></head><body>
<h1>🐟 fish.taxi — Admin</h1>
<input id="pass" type="password" placeholder="Admin token (fta_...)">
<button class="load" id="go">Зареди</button>
<div id="st"></div>
<h2>Чакащи заявки</h2><div id="out" class="mu">—</div>
<h2>Шофьори с достъп</h2><div id="drv" class="mu">—</div>
<h2>Одобрени заявки (архив)</h2><div id="appr" class="mu">—</div>
<script>
/* ADMIN_PANEL_V2 — без inline onclick.
   Старата версия строеше onclick в стринг и екранираше кавичките с една
   наклонена черта. Вътре в template literal това се свежда до гола кавичка
   и целият скрипт спираше да се парсва. Тук няма нито един escape. */
const W=location.origin;
function esc(s){return String(s||'').replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]))}
function pass(){return document.getElementById('pass').value.trim()}
function el(tag,cls,html){const e=document.createElement(tag);if(cls)e.className=cls;if(html!=null)e.innerHTML=html;return e}
function btn(label,cls,fn){const b=el('button',cls,label);b.onclick=()=>fn(b);return b}
function fail(node,e){node.innerHTML='';node.appendChild(el('span','err','⚠ '+esc(e.message)))}
async function get(path){
  const r=await fetch(W+path);
  let d=null;try{d=await r.json()}catch(e){}
  if(!r.ok||!d||!d.ok)throw new Error((d&&d.error)||('HTTP '+r.status));
  return d;
}
async function post(path,body){
  const r=await fetch(W+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let d=null;try{d=await r.json()}catch(e){}
  if(!r.ok||!d||!d.ok)throw new Error((d&&d.error)||('HTTP '+r.status));
  return d;
}
async function load(){
  const p=pass();localStorage.setItem('ftp',p);
  const st=document.getElementById('st');
  st.innerHTML='';st.appendChild(el('span','mu','Зареждане...'));
  let r;
  try{r=await get('/admin/pending?pass='+encodeURIComponent(p))}
  catch(e){fail(st,e);return}
  st.innerHTML='';st.appendChild(el('span','okc','✓ Токенът е приет'));
  const out=document.getElementById('out');out.innerHTML='';
  if(!r.records.length)out.appendChild(el('div','mu','Няма чакащи заявки'));
  for(const rec of r.records){
    const c=el('div','card');
    c.appendChild(el('div',null,'<b>'+esc(rec.name)+'</b> · '+esc(rec.phone)));
    c.appendChild(el('div','mu',esc(rec.car)+' · '+esc(rec.plate)+' · '+new Date(rec.created_at).toLocaleString('bg')));
    const res=el('div','res');
    c.appendChild(btn('✓ Одобри','ok',()=>act(rec.id,'approve',res)));
    c.appendChild(btn('✗ Откажи','no',()=>act(rec.id,'reject',res)));
    c.appendChild(res);out.appendChild(c);
  }
  loadDrivers();loadApproved();
}
async function act(id,action,res){
  try{
    const d=await post('/admin/action',{pass:pass(),id:id,action:action});
    res.innerHTML='';
    if(action==='approve')res.appendChild(el('div','tok','✓ Одобрен. ID: '+esc(d.driver_id)+'<br>Token: '+esc(d.token)));
    else res.appendChild(el('div','mu','Заявката е отказана.'));
    loadDrivers();
  }catch(e){fail(res,e)}
}
async function loadDrivers(){
  const box=document.getElementById('drv');
  let r;
  try{r=await get('/admin/drivers?pass='+encodeURIComponent(pass()))}
  catch(e){fail(box,e);return}
  box.innerHTML='';
  if(!r.drivers.length){box.appendChild(el('div','mu','Няма нито един ключ token: в KV'));return}
  for(const d of r.drivers){
    const c=el('div','card');
    const state=d.online?'<span class="okc">ONLINE</span>':'<span class="mu">офлайн</span>';
    c.appendChild(el('div',null,'<b>'+esc(d.name||('ID '+d.driver_id))+'</b> '+state));
    c.appendChild(el('div','mu','ID: '+esc(d.driver_id)
      +(d.car?' · '+esc(d.car):'')+(d.plate?' · '+esc(d.plate):'')
      +'<br>последно: '+(d.last_seen?new Date(d.last_seen).toLocaleString('bg'):'никога')
      +(d.has_base?' · има зададена база':'')));
    const res=el('div','res');
    c.appendChild(btn('🔑 Нов token','ok',()=>retok(d.driver_id,res)));
    c.appendChild(btn('🗑 Изтрий','no',()=>revoke(d.driver_id,res)));
    c.appendChild(res);box.appendChild(c);
  }
}
async function retok(id,res){
  try{
    const d=await post('/admin/retoken',{pass:pass(),driver_id:id});
    res.innerHTML='';
    res.appendChild(el('div','tok','Нов token за '+esc(id)+':<br>'+esc(d.token)
      +'<br>Прати го по Viber. Старият спира веднага, а апът трябва СТОП и после СТАРТ.'));
  }catch(e){fail(res,e)}
}
async function revoke(id,res){
  if(!confirm('Изтриване на достъпа на '+id+'?'))return;
  try{await post('/admin/revoke',{pass:pass(),driver_id:id});loadDrivers()}
  catch(e){fail(res,e)}
}
async function loadApproved(){
  const box=document.getElementById('appr');
  let r;
  try{r=await get('/admin/approved?pass='+encodeURIComponent(pass()))}
  catch(e){fail(box,e);return}
  box.innerHTML='';
  if(!r.records.length){box.appendChild(el('div','mu','Няма архивни заявки'));return}
  for(const x of r.records){
    box.appendChild(el('div','card','<b>'+esc(x.name)+'</b> · '+esc(x.phone)
      +'<br><span class="mu">'+esc(x.car)+' · '+esc(x.plate)+' · ID: '+esc(x.driver_id||'-')+'</span>'));
  }
}
document.getElementById('go').onclick=()=>load();
if(localStorage.getItem('ftp'))document.getElementById('pass').value=localStorage.getItem('ftp');
</script></body></html>"""

rep(OLD_PANEL, NEW_PANEL, 'admin panel rewritten without inline onclick')


# ─────────────────────────────────────────────────────────────
# 2) Нов ендпойнт: реалните шофьори по token:*
# ─────────────────────────────────────────────────────────────
ANCHOR_STATS = """    // ── Admin: статистика 14 дни ─────────────────────────"""

DRIVERS_EP = """    // ── Admin: реалните шофьори (по KV token:*) ───────────
    // approved:* съществува само за минали през заявка или /admin/add.
    // Вписаните направо в KV не се виждаха никъде, а те са тези, които
    // карат. Истината за кой има достъп е token:*, не архивът.
    // Токенът НЕ се връща: списъкът е за преглед, не за раздаване.
    if (path === '/admin/drivers' && request.method === 'GET') {
      const pass = url.searchParams.get('pass');
      if (!(await checkAdminPass(env, pass))) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      try {
        const meta = {};
        const ap = await env.GPS_STORE.list({ prefix: 'approved:' });
        for (const k of ap.keys) {
          const raw = await env.GPS_STORE.get(k.name);
          if (!raw) continue;
          const r = JSON.parse(raw);
          if (r.driver_id) meta[r.driver_id] = { name: r.name, car: r.car, plate: r.plate };
        }
        const list = await env.GPS_STORE.list({ prefix: 'token:' });
        const now = Date.now();
        const drivers = [];
        for (const k of list.keys) {
          const did = k.name.slice('token:'.length);
          let last = null, online = false;
          const raw = await env.GPS_STORE.get(`driver:${did}`);
          if (raw) {
            try {
              const d = JSON.parse(raw);
              last = d.updated_at || null;
              online = !!d.online && (now - (d.updated_at || 0)) < OFFLINE_AFTER_MS;
            } catch (e) {}
          }
          const m = meta[did] || {};
          drivers.push({
            driver_id: did,
            name: m.name || null, car: m.car || null, plate: m.plate || null,
            online, last_seen: last,
            has_base: !!(await getBase(env, did))
          });
        }
        drivers.sort((a, b) => (b.last_seen || 0) - (a.last_seen || 0));
        return new Response(JSON.stringify({ ok: true, count: drivers.length, drivers }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── Admin: статистика 14 дни ─────────────────────────"""

rep(ANCHOR_STATS, DRIVERS_EP, '/admin/drivers endpoint added')


# ─────────────────────────────────────────────────────────────
# 3) Мъртвият /admin/password отпада
# ─────────────────────────────────────────────────────────────
OLD_PASSWORD = """    // ── Admin: смяна на admin паролата ────────────────────
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
"""

NEW_PASSWORD = """    // /admin/password е премахнат. Записваше KV admin:password, който
    // checkAdminPass не чете от 16.08 — сменена оттам парола мълчаливо
    // не важеше никъде. Ротацията минава само през /admin/rotate-token.
"""

rep(OLD_PASSWORD, NEW_PASSWORD, 'dead /admin/password removed')

io.open(p, 'w', encoding='utf-8').write(s)
print('OK  %d -> %d chars' % (n0, len(s)))
