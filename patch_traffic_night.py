# -*- coding: utf-8 -*-
"""Нощен режим за трафика: 23:00–06:00 софийско време кешът става 30 минути
вместо 4. Нощем пътищата са свободни и няма смисъл да горим квота —
но не спираме напълно, за да се хващат ремонти и затворени участъци."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()

if 'TT_NIGHT' in src:
    print('SKIP нощният режим вече е сложен')
    sys.exit(0)

# вмъкваме изчисляването на режима преди дневния предпазител
old = """          // дневен предпазител за безплатната квота
          const TT_DAILY_CAP = 2200;"""
new = """          // нощем (23:00–06:00 софийско) кешираме много по-дълго
          const sofiaH = (new Date().getUTCHours() + 3) % 24;
          const TT_NIGHT = (sofiaH >= 23 || sofiaH < 6);
          const TT_TTL = TT_NIGHT ? 1800 : 240;
          // дневен предпазител за безплатната квота
          const TT_DAILY_CAP = 2200;"""
if old in src:
    src = src.replace(old, new, 1)
    print('OK нощен режим: 23:00–06:00 -> кеш 30 мин')
else:
    print('FAIL мястото за нощния режим не е намерено')
    sys.exit(1)

# TTL-ът на кеша става променлив
n = src.count("{ expirationTtl: 240 }")
if n:
    src = src.replace("{ expirationTtl: 240 }", "{ expirationTtl: TT_TTL }")
    print('OK кешът ползва променлив TTL (%d места)' % n)

open(path, 'w', encoding='utf-8').write(src)
