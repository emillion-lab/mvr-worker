# -*- coding: utf-8 -*-
"""Ключът за TomTom да се чете от env.TOMTOM_KEY ИЛИ от KV (GPS_STORE).
Така може да се сложи по два начина:
  A) Cloudflare dashboard -> Settings -> Variables -> Secret TOMTOM_KEY
  B) GitHub Actions -> KV Tool -> action=put, key=TOMTOM_KEY, value=<ключа>
Стойността се кешира в паметта на worker-а, за да не се чете KV при всяка заявка."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()
log = []

if 'TT_KEY_CACHE' in src:
    print('SKIP вече е приложено')
    sys.exit(0)

if "path === '/traffic'" not in src:
    print('FAIL /traffic не е намерен — пусни първо patch_traffic.py')
    sys.exit(1)

# 1) кеш в модула (живее докато worker инстанцията е топла)
if 'let TT_KEY_CACHE' not in src:
    m = re.search(r'^(export default|const CORS)', src, re.M)
    ins = 'let TT_KEY_CACHE = null;\n\n'
    if m:
        src = src[:m.start()] + ins + src[m.start():]
        log.append('OK кеш променлива добавена')
    else:
        src = ins + src
        log.append('OK кеш променлива добавена (в началото)')

# 2) проверката за ключа: env -> KV -> грешка
old = """        if (!env.TOMTOM_KEY) {
          return new Response(JSON.stringify({ error: 'TOMTOM_KEY не е зададен' }),
            { status: 503, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }"""
new = """        let TT = env.TOMTOM_KEY || TT_KEY_CACHE;
        if (!TT) {
          try { TT = await env.GPS_STORE.get('TOMTOM_KEY'); } catch (e) {}
          if (TT) TT_KEY_CACHE = TT;
        }
        if (!TT) {
          return new Response(JSON.stringify({
              error: 'TOMTOM_KEY липсва',
              hint: 'сложи го като Worker secret ИЛИ в KV с ключ TOMTOM_KEY'
            }),
            { status: 503, headers: { ...CORS, 'Content-Type': 'application/json' } });
        }"""
if old in src:
    src = src.replace(old, new, 1)
    log.append('OK проверката чете env + KV')
else:
    # по-хлабав вариант, ако отстъпът се различава
    pat = re.compile(r'if \(!env\.TOMTOM_KEY\) \{.*?\}\n', re.S)
    if pat.search(src):
        src = pat.sub(new.strip() + '\n', src, count=1)
        log.append('OK проверката заменена (хлабав шаблон)')
    else:
        log.append('⚠ проверката за ключа не е намерена')

# 3) самата заявка ползва TT вместо env.TOMTOM_KEY
n = src.count("'?key=' + env.TOMTOM_KEY")
if n:
    src = src.replace("'?key=' + env.TOMTOM_KEY", "'?key=' + TT")
    log.append('OK заявката ползва намерения ключ (%d места)' % n)

open(path, 'w', encoding='utf-8').write(src)
open('traffic-patch-report.txt', 'w', encoding='utf-8').write('\n'.join(log) + '\n')
print('\n'.join(log))
