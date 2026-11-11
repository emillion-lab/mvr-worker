#!/usr/bin/env python3
"""FT-DRIVER-PROFILE-V1 (11.11.2026) — POST /driver/profile.

Шофьорът (токен от KV, както за GPS) праща списък с второстепенни
настройки от страницата fish.taxi/profil.html. Worker-ът:
  1. проверява токена (checkToken — само KV четене, нищо не пише);
  2. пуска само разрешените ключове с правилния тип (втората проверка е
     в scripts/driver_edit.py във FISHTAXI);
  3. стартира workflow driver-intake.yml във FISHTAXI с edit_phone/edit_json.
     Нищо не се пише в KV и нищо не се листва — не тежи на квотата.
Лимит: 30 заявки на 10 мин на IP и 6 на 10 мин на шофьор (в паметта).

Идемпотентен. Котвата трябва да е точно веднъж, иначе exit 1 без промяна.
"""
import sys

P = 'src/worker.js'
MARK = 'FT-DRIVER-PROFILE-V1'
s = open(P, encoding='utf-8').read()
OLD_L = "const LANGS = ['bg','en','ru','de','fr','tr','it','es'];"
NEW_L = "const LANGS = ['bg','en','ru','de','fr','tr','it','es','cs','ar','zh'];"
if MARK in s:
    if OLD_L in s:   # 11.11.2026: чешки, арабски, китайски — както на сайта
        open(P, 'w', encoding='utf-8').write(s.replace(OLD_L, NEW_L))
        print('FT-DRIVER-PROFILE-V1: езиците разширени (cs, ar, zh)')
    else:
        print('FT-DRIVER-PROFILE-V1: вече е приложен — SKIP')
    sys.exit(0)

ANCHOR = "    if (path === '/gps' && request.method === 'POST') {"
if s.count(ANCHOR) != 1:
    print('FT-DRIVER-PROFILE-V1: котвата не е точно веднъж —', s.count(ANCHOR))
    sys.exit(1)

BLOCK = r"""    /* ═══ FT-DRIVER-PROFILE-V1 ═══ шофьорът сам сменя второстепенното */
    if (path === '/driver/profile' && request.method === 'POST') {
      const J = { ...CORS, 'Content-Type': 'application/json; charset=utf-8' };
      try {
        const g = (globalThis.__dpRl = globalThis.__dpRl || new Map());
        const hit = (k, max) => {
          const now = Date.now(), a = (g.get(k) || []).filter(t => now - t < 600000);
          a.push(now); g.set(k, a);
          if (g.size > 500) for (const [kk, vv] of g) if (!vv.length || now - vv[vv.length - 1] > 600000) g.delete(kk);
          return a.length > max;
        };
        const ip = request.headers.get('CF-Connecting-IP') || 'x';
        if (hit('ip:' + ip, 30)) {
          return new Response(JSON.stringify({ error: 'Твърде много опити. Опитай след малко.' }), { status: 429, headers: J });
        }
        const body = await request.json();
        if (!(await checkToken(env, body.driver_id, body.token))) {
          return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: J });
        }
        const did = normPhone(body.driver_id);
        if (hit('d:' + did, 6)) {
          return new Response(JSON.stringify({ error: 'Твърде много промени. Опитай след 10 минути.' }), { status: 429, headers: J });
        }
        const BOOL = ['ac','music','silent_ok','talk_ok','calm_ok','usb','streaming','petfriendly','childok','nosmoker','terminal','panoroof','legroom',
          'music_pop','music_chalga','music_rock','music_classical','music_jazz','music_electronic','music_chillout','music_lounge'];
        const TRI = ['airport','longdist','night','wheelchair'];
        const LANGS = ['bg','en','ru','de','fr','tr','it','es','cs','ar','zh'];
        const src = (body.fields && typeof body.fields === 'object') ? body.fields : {};
        const out = {};
        for (const k of BOOL) if (typeof src[k] === 'boolean') out[k] = src[k];
        for (const k of TRI) if (typeof src[k] === 'boolean' || src[k] === 'ask') out[k] = src[k];
        if (Array.isArray(src.langs)) {
          const l = src.langs.filter(x => LANGS.includes(x));
          if (l.length) out.langs = Array.from(new Set(l));
        }
        if (!Object.keys(out).length) {
          return new Response(JSON.stringify({ error: 'Няма какво да се запише.' }), { status: 400, headers: J });
        }
        if (!env.GH_TOKEN) {
          return new Response(JSON.stringify({ error: 'Временно недостъпно.' }), { status: 503, headers: J });
        }
        const owner = env.GH_OWNER || 'emillion-lab';
        const r = await fetch('https://api.github.com/repos/' + owner + '/FISHTAXI/actions/workflows/driver-intake.yml/dispatches', {
          method: 'POST',
          headers: {
            'Authorization': 'Bearer ' + env.GH_TOKEN, 'Accept': 'application/vnd.github+json',
            'User-Agent': 'mvr-proxy-profile', 'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'
          },
          body: JSON.stringify({ ref: 'main', inputs: { edit_phone: did, edit_json: JSON.stringify(out) } })
        });
        if (r.status !== 204) {
          return new Response(JSON.stringify({ error: 'Записът не мина (' + r.status + '). Пиши на Емил.' }), { status: 502, headers: J });
        }
        return new Response(JSON.stringify({ ok: true }), { headers: J });
      } catch (e) {
        return new Response(JSON.stringify({ error: 'Грешка. Опитай пак.' }), { status: 400, headers: J });
      }
    }

"""
s = s.replace(ANCHOR, BLOCK + ANCHOR)
open(P, 'w', encoding='utf-8').write(s)
print('FT-DRIVER-PROFILE-V1: приложен')
