#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Два патча по src/worker.js:

1. FT-PUBID-V1  — GET /gps е публичен. driver_id вече е телефон,
   затова навън излиза детерминиран псевдоним, не самият номер.

2. FT-RETOKEN-V1 — POST /request-token не ротира нищо. Записва nonce
   и уведомява админа в Telegram. Ротацията става при отваряне на
   /claim-token. Така чужда заявка не може да изхвърли шофьор офлайн.

Скриптът спира с грешка, ако котва не се намери — по-добре празен
run, отколкото тихо разминаване с живия worker.
"""
import sys, io

PATH = 'src/worker.js'

with io.open(PATH, encoding='utf-8') as f:
    src = f.read()

if 'FT-RETOKEN-V1' in src or 'FT-PUBID-V1' in src:
    print('вече е приложено')
    sys.exit(0)

def anchor(text, name):
    n = src.count(text)
    if n != 1:
        print('КОТВА "%s" се среща %d пъти, очаква се 1' % (name, n))
        sys.exit(1)

# ─── 1. pubId ───────────────────────────────────────────────
A1 = 'async function checkToken(env, driver_id, token) {'
anchor(A1, 'checkToken')

PUBID = r"""/* ═══ FT-PUBID-V1 ═══
   driver_id е телефонен номер, а GET /gps е публичен и с CORS *.
   Навън излиза детерминиран псевдоним: една и съща кола = един и същ
   идентификатор при всяко зареждане, но номерът не се възстановява. */
function pubId(did) {
  return 'd' + baseHash('pub:' + String(did || '')).toString(36);
}

"""

src = src.replace(A1, PUBID + A1, 1)

# ─── 2. GET /gps връща псевдоним ────────────────────────────
A2 = '          drivers.push(await maskIfOffline(env, d));'
anchor(A2, 'gps push')

A2_NEW = r"""          const pub = await maskIfOffline(env, d);
          pub.driver_id = pubId(pub.driver_id);
          drivers.push(pub);"""

src = src.replace(A2, A2_NEW, 1)

# ─── 3. /request-token + /claim-token ───────────────────────
A3 = "    if (path === '/' || path === '/health') {"
anchor(A3, 'health route')

RETOKEN = r"""    /* ═══ FT-RETOKEN-V1 ═══
       Заявка за нов токен. НЕ ротира нищо и НЕ отговаря дали номерът
       съществува — иначе ендпойнтът става безплатен проверител кои
       телефони са в системата, а всеки с чужд номер би могъл да
       изхвърли шофьора офлайн. Ротацията е в /claim-token. */
    if (path === '/request-token' && request.method === 'POST') {
      const OK = () => new Response(JSON.stringify({ ok: true, sent: true }), { headers: CORS });
      try {
        const body = await request.json();
        const did = normPhone(body.driver_id);
        if (!did) return OK();

        // 1 заявка на 10 мин на шофьор — спира спама към админа
        if (await env.GPS_STORE.get(`rt:rl:${did}`)) return OK();
        await env.GPS_STORE.put(`rt:rl:${did}`, '1', { expirationTtl: 600 });

        // непознат номер: същият отговор, никакво съобщение
        if (!(await env.GPS_STORE.get(`token:${did}`))) return OK();

        // един жив nonce на шофьор — новата заявка убива старата
        const prev = await env.GPS_STORE.get(`rt:ptr:${did}`);
        if (prev) { try { await env.GPS_STORE.delete(`rt:${prev}`); } catch (e) {} }

        const bytes = crypto.getRandomValues(new Uint8Array(16));
        const nonce = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
        await env.GPS_STORE.put(`rt:${nonce}`, JSON.stringify({ did, at: Date.now() }), { expirationTtl: 900 });
        await env.GPS_STORE.put(`rt:ptr:${did}`, nonce, { expirationTtl: 900 });

        let name = null;
        try {
          const ap = await env.GPS_STORE.list({ prefix: 'approved:' });
          for (const k of ap.keys) {
            const raw = await env.GPS_STORE.get(k.name);
            if (!raw) continue;
            const r = JSON.parse(raw);
            if (r.driver_id === did) { name = r.name; break; }
          }
        } catch (e) {}

        if (env.TG_BOT_TOKEN && env.TG_CHAT_ID) {
          const link = url.origin + '/claim-token?n=' + nonce;
          const until = new Date(Date.now() + 900000 + 3 * 3600000).toISOString().slice(11, 16);
          const text = '🔑 fish.taxi — заявка за нов токен\n'
            + 'Шофьор: ' + (name || '—') + ' (' + did + ')\n\n'
            + link + '\n\n'
            + 'Важи до ' + until + ' ч., еднократен.\n'
            + 'Старият токен умира чак когато линкът бъде отворен.';
          try {
            await fetch('https://api.telegram.org/bot' + env.TG_BOT_TOKEN + '/sendMessage', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ chat_id: env.TG_CHAT_ID, text, disable_web_page_preview: true })
            });
          } catch (e) {}
        }
        return OK();
      } catch (e) {
        return OK();
      }
    }

    /* Отварянето на линка е моментът на ротацията. Дотогава шофьорът
       кара със стария токен и не забелязва нищо. */
    if (path === '/claim-token' && request.method === 'GET') {
      const page = (msg, tok, did) => new Response(
        '<!DOCTYPE html><html lang="bg"><head><meta charset="utf-8">'
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + '<title>fish.taxi</title><style>'
        + 'body{font-family:system-ui;background:#0B1220;color:#E6EDF3;margin:0;padding:24px;max-width:520px;margin:auto}'
        + '.t{font-family:monospace;font-size:15px;background:#141E33;padding:12px;border-radius:8px;word-break:break-all;margin:8px 0 16px}'
        + '.mu{color:#8899AA;font-size:14px;margin-bottom:2px}'
        + '</style></head><body><h2>🐟 fish.taxi</h2><p>' + msg + '</p>'
        + (tok
            ? '<div class="mu">Driver ID</div><div class="t">' + did + '</div>'
              + '<div class="mu">Нов токен</div><div class="t">' + tok + '</div>'
              + '<p class="mu">Въведи ги в апа, после <b>СТОП</b> и пак <b>СТАРТ</b> — '
              + 'фоновата услуга държи стария, докато не се рестартира. '
              + 'Тази страница не се отваря втори път.</p>'
            : '')
        + '</body></html>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' } });

      const n = (url.searchParams.get('n') || '').replace(/[^a-f0-9]/g, '');
      if (!n) return page('Невалиден линк.', null, null);
      const raw = await env.GPS_STORE.get(`rt:${n}`);
      if (!raw) return page('Линкът е изтекъл или вече е използван. Поискай нов от приложението.', null, null);
      const did = JSON.parse(raw).did;
      await env.GPS_STORE.delete(`rt:${n}`);
      await env.GPS_STORE.delete(`rt:ptr:${did}`);
      if (!(await env.GPS_STORE.get(`token:${did}`))) return page('Този шофьор вече няма достъп.', null, null);
      const t = genToken();
      await env.GPS_STORE.put(`token:${did}`, t);
      return page('Готово. Старият токен вече не важи.', t, did);
    }

"""

src = src.replace(A3, RETOKEN + A3, 1)

with io.open(PATH, 'w', encoding='utf-8') as f:
    f.write(src)

print('приложено: FT-PUBID-V1 + FT-RETOKEN-V1')
