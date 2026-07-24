# -*- coding: utf-8 -*-
"""Разширяване за повече улици:
1) дневният кеш 4 -> 8 минути (за задръстване е напълно достатъчно)
2) лимитът от 12 точки на заявка -> 20
3) дневният предпазител 2200 -> 2400 (лимитът е 2500)
Сметка: 15 отсечки x (7.5/ч x 17ч + 2/ч x 7ч) = ~2100 от 2500."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()
log = []

# 1) дневен TTL 240 -> 480
if 'TT_NIGHT ? 1800 : 240' in src:
    src = src.replace('TT_NIGHT ? 1800 : 240', 'TT_NIGHT ? 1800 : 480')
    log.append('OK дневен кеш 4 -> 8 минути')
elif 'TT_NIGHT ? 1800 : 480' in src:
    log.append('SKIP кешът вече е 8 минути')
else:
    log.append('⚠ TTL изразът не е намерен')

# 2) до 20 точки на заявка
if "slice(0, 12)" in src:
    src = src.replace("slice(0, 12)", "slice(0, 20)")
    log.append('OK до 20 точки на заявка (беше 12)')
elif "slice(0, 20)" in src:
    log.append('SKIP лимитът вече е 20')

# 3) предпазител 2200 -> 2400
if 'TT_DAILY_CAP = 2200' in src:
    src = src.replace('TT_DAILY_CAP = 2200', 'TT_DAILY_CAP = 2400')
    log.append('OK дневен предпазител 2200 -> 2400')
elif 'TT_DAILY_CAP = 2400' in src:
    log.append('SKIP предпазителят вече е 2400')

open(path, 'w', encoding='utf-8').write(src)
print('\n'.join(log))
