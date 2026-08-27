# -*- coding: utf-8 -*-
# mvr-proxy · FT-ORGS-FIX-V1
#
# /admin/dispatch без repo питаше GitHub /orgs/{owner}/repos за списъка.
# Но emillion-lab е ПОТРЕБИТЕЛСКИ акаунт, не организация → GitHub връща
# 404 "Not Found". Правилният endpoint за user е /users/{owner}/repos.
#
# Fix: пробвай /orgs/ първо (ако някога стане организация), при 404
# падни на /users/. Така работи и за двата случая.
# Идемпотентен.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()

if 'FT-ORGS-FIX-V1' in s:
    print('SKIP: вече приложено'); sys.exit(0)

OLD = """        if (!repo) {
          const r = await fetch('https://api.github.com/orgs/' + owner + '/repos?per_page=100&sort=pushed', { headers: H });
          const d = await r.json();
          if (!r.ok) return new Response(JSON.stringify({ error: d.message || 'github error' }), { status: r.status, headers: CORS });
          return new Response(JSON.stringify({ ok: true, repos: (d || []).map(x => x.name) }), { headers: CORS });
        }"""

NEW = """        if (!repo) {
          /* FT-ORGS-FIX-V1: emillion-lab е user, не org. Пробвай /orgs/,
             при 404 падни на /users/. */
          let r = await fetch('https://api.github.com/orgs/' + owner + '/repos?per_page=100&sort=pushed', { headers: H });
          if (r.status === 404) {
            r = await fetch('https://api.github.com/users/' + owner + '/repos?per_page=100&sort=pushed', { headers: H });
          }
          const d = await r.json();
          if (!r.ok) return new Response(JSON.stringify({ error: d.message || 'github error' }), { status: r.status, headers: CORS });
          return new Response(JSON.stringify({ ok: true, repos: (d || []).map(x => x.name) }), { headers: CORS });
        }"""

n = s.count(OLD)
if n != 1:
    print('FAIL: котвата се среща %d пъти, очаква се 1' % n)
    sys.exit(1)

s = s.replace(OLD, NEW)
io.open(p, 'w', encoding='utf-8').write(s)
print('OK: FT-ORGS-FIX-V1 приложен')
