# -*- coding: utf-8 -*-
"""Ключът за TomTom се търси в три места, по приоритет:
  1) env.TOMTOM_KEY   (Worker secret, ако някога бъде сложен)
  2) D1 CONFIG_DB     (таблица secrets — там е сега)
  3) KV GPS_STORE     (резервно)
Кешира се в паметта на worker инстанцията, за да не се чете при всяка заявка."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()
log = []

if 'CONFIG_DB' in src:
    print('SKIP D1 четенето вече е добавено')
    sys.exit(0)

if "path === '/traffic'" not in src:
    print('FAIL /traffic не е намерен')
    sys.exit(1)

old_a = """        let TT = env.TOMTOM_KEY || TT_KEY_CACHE;
        if (!TT) {
          try { TT = await env.GPS_STORE.get('TOMTOM_KEY'); } catch (e) {}
          if (TT) TT_KEY_CACHE = TT;
        }"""
new_a = """        let TT = env.TOMTOM_KEY || TT_KEY_CACHE;
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
        if (TT) TT_KEY_CACHE = TT;"""

if old_a in src:
    src = src.replace(old_a, new_a, 1)
    log.append('OK ключът се чете от env -> D1 -> KV')
else:
    pat = re.compile(r'let TT = env\.TOMTOM_KEY \|\| TT_KEY_CACHE;.*?if \(TT\) TT_KEY_CACHE = TT;\n\s*\}', re.S)
    if pat.search(src):
        src = pat.sub(new_a, src, count=1)
        log.append('OK ключът се чете от env -> D1 -> KV (хлабав шаблон)')
    else:
        log.append('⚠ блокът за ключа не е намерен — проверявам ръчно')

# по-ясно съобщение при липса
src = src.replace("hint: 'сложи го като Worker secret ИЛИ в KV с ключ TOMTOM_KEY'",
                  "hint: 'очаква се в D1 CONFIG_DB.secrets, KV или Worker secret'")

open(path, 'w', encoding='utf-8').write(src)
open('traffic-patch-report.txt', 'w', encoding='utf-8').write('\n'.join(log) + '\n')
print('\n'.join(log))
