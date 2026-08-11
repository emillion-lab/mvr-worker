#!/usr/bin/env python3
"""Добавя /dispatch endpoint в src/worker.js.

Позволява пускане на GitHub Actions workflow-и през HTTP заявка към
mvr-proxy, без Cloudflare dashboard и без локален git — т.е. работи и от
телефон. Пази се с DISPATCH_KEY (Worker secret); токенът GH_TOKEN също е
Worker secret и никога не влиза в repo-то.

Скриптът е idempotent: ако блокът вече е вътре, не прави нищо.
"""
import sys

PATH = 'src/worker.js'
MARKER = ("    if (path === '/' || path === '/health') {\n"
          "      return new Response(JSON.stringify({ service: 'fish.taxi Worker', "
          "status: 'ok', version: ")

BLOCK = r"""    // ── GitHub Actions dispatch ───────────────────────────
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

"""


def main():
    src = open(PATH, encoding='utf-8').read()

    if "path === '/dispatch'" in src:
        print('/dispatch вече е вътре — нищо за правене')
        return

    i = src.find(MARKER)
    if i < 0:
        print('ГРЕШКА: не намирам health маршрута — файлът се е променил')
        sys.exit(1)

    src = src[:i] + BLOCK + src[i:]
    open(PATH, 'w', encoding='utf-8').write(src)
    print('добавен /dispatch, нов размер:', len(src))


if __name__ == '__main__':
    main()
