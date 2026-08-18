# -*- coding: utf-8 -*-
# mvr-proxy · ендпойнтите, от които се нуждае пълният админ конзол.
#
# Добавя:
#   /admin/kv        — четене и писане в GPS_STORE (списък, стойност, запис, триене)
#   /admin/dispatch  — пускане на GitHub workflow с admin token вместо DISPATCH_KEY
#   /admin/health    — квоти, кешове, броячи на един поглед
#
# ЗАЩИТА, която не е по избор:
#   admin:token НЕ може да се пише или трие през /admin/kv. Иначе една
#   сгрешена буква в браузъра заключва админа завинаги, а хешове не се
#   обръщат. Ротацията минава единствено през /admin/rotate-token.
#   token:* може да се чете само като имена на ключове, не като стойности —
#   шофьорските токени не бива да излизат в отговор на списък.
#
# Идемпотентен: втори пуск не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'ADMIN_TOOLS_V1' in s:
    print('SKIP: admin tools already applied'); sys.exit(0)

ANCHOR = "    // ── Admin: реалните шофьори (по KV token:*) ───────────"
if s.count(ANCHOR) != 1:
    print('FAIL anchor (%d hits)' % s.count(ANCHOR)); sys.exit(1)

TOOLS = """    /* ═══ ADMIN_TOOLS_V1 ═══
       KV браузър, GitHub dispatch и състояние на системата. */

    // ── Admin: KV браузър ─────────────────────────────────
    // Пази се от самозаключване: admin:token е недосегаем оттук.
    // Стойностите на token:* не се връщат — имената стигат.
    if (path === '/admin/kv') {
      const isPost = request.method === 'POST';
      let body = {};
      if (isPost) { try { body = await request.json(); } catch (e) {} }
      const pass = isPost ? body.pass : url.searchParams.get('pass');
      if (!(await checkAdminPass(env, pass))) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      const op = (isPost ? body.op : url.searchParams.get('op')) || 'list';
      const key = (isPost ? body.key : url.searchParams.get('key')) || '';
      const PROTECTED = key === 'admin:token' || key === 'admin:password';
      try {
        if (op === 'list') {
          const prefix = (url.searchParams.get('prefix') || '');
          const out = [];
          let cursor = undefined, pages = 0;
          do {
            const r = await env.GPS_STORE.list({ prefix, cursor, limit: 1000 });
            for (const k of r.keys) out.push(k.name);
            cursor = r.list_complete ? null : r.cursor;
            pages++;
          } while (cursor && pages < 5 && out.length < 3000);
          out.sort();
          return new Response(JSON.stringify({ ok: true, count: out.length, keys: out }), { headers: CORS });
        }
        if (op === 'get') {
          if (!key) return new Response(JSON.stringify({ error: 'key required' }), { status: 400, headers: CORS });
          if (key.startsWith('token:') || PROTECTED) {
            return new Response(JSON.stringify({ error: 'Стойността на този ключ не се показва. Ползвай ротация.' }), { status: 403, headers: CORS });
          }
          const v = await env.GPS_STORE.get(key);
          return new Response(JSON.stringify({ ok: true, key, value: v, exists: v !== null }), { headers: CORS });
        }
        if (op === 'put') {
          if (!isPost) return new Response(JSON.stringify({ error: 'POST required' }), { status: 405, headers: CORS });
          if (!key) return new Response(JSON.stringify({ error: 'key required' }), { status: 400, headers: CORS });
          if (PROTECTED) {
            return new Response(JSON.stringify({ error: 'admin:token не се пише оттук — ползвай /admin/rotate-token' }), { status: 403, headers: CORS });
          }
          if (typeof body.value !== 'string') {
            return new Response(JSON.stringify({ error: 'value must be a string' }), { status: 400, headers: CORS });
          }
          const opts = {};
          if (body.ttl && Number(body.ttl) >= 60) opts.expirationTtl = Number(body.ttl);
          await env.GPS_STORE.put(key, body.value, opts);
          return new Response(JSON.stringify({ ok: true, key, bytes: body.value.length }), { headers: CORS });
        }
        if (op === 'delete') {
          if (!isPost) return new Response(JSON.stringify({ error: 'POST required' }), { status: 405, headers: CORS });
          if (!key) return new Response(JSON.stringify({ error: 'key required' }), { status: 400, headers: CORS });
          if (PROTECTED) {
            return new Response(JSON.stringify({ error: 'admin:token не се трие оттук — това би заключило админа завинаги' }), { status: 403, headers: CORS });
          }
          await env.GPS_STORE.delete(key);
          return new Response(JSON.stringify({ ok: true, key, deleted: true }), { headers: CORS });
        }
        return new Response(JSON.stringify({ error: 'unknown op' }), { status: 400, headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

    // ── Admin: GitHub workflow-и ──────────────────────────
    // Същото като /dispatch, но се отключва с admin token, за да не се
    // налага втори ключ в телефона. GH_TOKEN си остава само в Worker-а.
    if (path === '/admin/dispatch') {
      const isPost = request.method === 'POST';
      let body = {};
      if (isPost) { try { body = await request.json(); } catch (e) {} }
      const pass = isPost ? body.pass : url.searchParams.get('pass');
      if (!(await checkAdminPass(env, pass))) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      const tok = env.GH_TOKEN;
      if (!tok) {
        return new Response(JSON.stringify({ error: 'GH_TOKEN не е сложен на Worker-а' }), { status: 500, headers: CORS });
      }
      const owner = env.GH_OWNER || 'emillion-lab';
      const repo = isPost ? body.repo : url.searchParams.get('repo');
      const wf = isPost ? body.workflow : url.searchParams.get('workflow');
      const ref = (isPost ? body.ref : url.searchParams.get('ref')) || 'main';
      const H = {
        'Authorization': 'Bearer ' + tok,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'mvr-proxy-admin',
        'X-GitHub-Api-Version': '2022-11-28'
      };
      try {
        if (!repo) {
          const r = await fetch('https://api.github.com/orgs/' + owner + '/repos?per_page=100&sort=pushed', { headers: H });
          const d = await r.json();
          if (!r.ok) return new Response(JSON.stringify({ error: d.message || 'github error' }), { status: r.status, headers: CORS });
          return new Response(JSON.stringify({ ok: true, repos: (d || []).map(x => x.name) }), { headers: CORS });
        }
        const api = 'https://api.github.com/repos/' + owner + '/' + repo + '/actions';
        if (!isPost && url.searchParams.get('runs')) {
          const u = wf ? api + '/workflows/' + encodeURIComponent(wf) + '/runs?per_page=5' : api + '/runs?per_page=5';
          const r = await fetch(u, { headers: H });
          const d = await r.json();
          if (!r.ok) return new Response(JSON.stringify({ error: d.message || 'github error' }), { status: r.status, headers: CORS });
          return new Response(JSON.stringify({ ok: true, runs: (d.workflow_runs || []).map(x => ({
            name: x.name, status: x.status, conclusion: x.conclusion,
            created_at: x.created_at, url: x.html_url })) }), { headers: CORS });
        }
        if (!isPost) {
          const r = await fetch(api + '/workflows?per_page=100', { headers: H });
          const d = await r.json();
          if (!r.ok) return new Response(JSON.stringify({ error: d.message || 'github error' }), { status: r.status, headers: CORS });
          return new Response(JSON.stringify({ ok: true, workflows: (d.workflows || [])
            .filter(w => w.state === 'active')
            .map(w => ({ name: w.name, file: w.path.split('/').pop() })) }), { headers: CORS });
        }
        if (!wf) return new Response(JSON.stringify({ error: 'workflow required' }), { status: 400, headers: CORS });
        const payload = { ref };
        if (body.inputs && typeof body.inputs === 'object') payload.inputs = body.inputs;
        const r = await fetch(api + '/workflows/' + encodeURIComponent(wf) + '/dispatches', {
          method: 'POST', headers: { ...H, 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (r.status === 204) {
          return new Response(JSON.stringify({ ok: true, queued: true, repo, workflow: wf, ref,
            watch: 'https://github.com/' + owner + '/' + repo + '/actions/workflows/' + wf }), { headers: CORS });
        }
        const txt = await r.text();
        let m = txt; try { m = JSON.parse(txt).message || txt; } catch (e) {}
        return new Response(JSON.stringify({ error: m, status: r.status }), { status: r.status, headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 502, headers: CORS });
      }
    }

    // ── Admin: състояние на системата ─────────────────────
    // Квотите са единственото, което може да спре платформата тихо:
    // TomTom спира на 2400 заявки, AeroDataBox на 180 единици, а KV
    // писанията имат дневен таван на безплатния план.
    if (path === '/admin/health' && request.method === 'GET') {
      if (!(await checkAdminPass(env, url.searchParams.get('pass')))) {
        return new Response(JSON.stringify({ error: 'Unauthorized' }), { status: 401, headers: CORS });
      }
      try {
        const today = new Date(Date.now() + 3 * 3600000).toISOString().slice(0, 10);
        const num = async (k) => parseInt((await env.GPS_STORE.get(k)) || '0', 10) || 0;
        const countPrefix = async (prefix) => {
          const r = await env.GPS_STORE.list({ prefix, limit: 1000 });
          return r.keys.length;
        };
        const tt = await num('tt:count:' + new Date().toISOString().slice(0, 10));
        const adb = await num('adb:used:' + today);
        const riskRaw = await env.GPS_STORE.get('risk:current');
        let risk = null;
        if (riskRaw) { try { const j = JSON.parse(riskRaw); risk = { car: j.car_score, harm: j.harm_score, label: j.label }; } catch (e) {} }
        return new Response(JSON.stringify({
          ok: true, version: '2.9.1', day: today,
          quotas: {
            tomtom: { used: tt, cap: 2400, pct: Math.round(tt / 24) },
            aerodatabox: { used: adb, cap: 180, pct: Math.round(adb / 1.8) }
          },
          kv: {
            drivers: await countPrefix('driver:'),
            tokens: await countPrefix('token:'),
            pending: await countPrefix('pending:'),
            approved: await countPrefix('approved:'),
            presence: await countPrefix('presence:'),
            bases: await countPrefix('base:')
          },
          risk_cached: risk,
          secrets: {
            admin_token_secret: !!env.ADMIN_TOKEN,
            admin_token_kv: !!(await env.GPS_STORE.get('admin:token')),
            gh_token: !!env.GH_TOKEN,
            tomtom: !!env.TOMTOM_KEY,
            dispatch_key: !!env.DISPATCH_KEY
          }
        }), { headers: CORS });
      } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500, headers: CORS });
      }
    }

""" + ANCHOR

s = s.replace(ANCHOR, TOOLS)
io.open(p, 'w', encoding='utf-8').write(s)
print('OK  %d -> %d chars' % (n0, len(s)))
