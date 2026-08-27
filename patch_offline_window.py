#!/usr/bin/env python3
"""
patch_offline_window.py — вдига OFFLINE_AFTER_MS от 2 на 6 минути.

Защо: GET /gps маркира шофьор офлайн, ако последният запис е на повече
от OFFLINE_AFTER_MS. Беше 2 минути. Но POST /gps праща heartbeat само
на 4 минути за стояща кола (dt < 240000 → skip). Между два heartbeat-а
стоящата кола винаги пада офлайн за ~2 минути — точно това правеше
профила на fish.taxi да мига "Offline" при жив GPS.

Прагът трябва да НАДВИШАВА най-дългия heartbeat. 6 мин > 4 мин с резерв.
Страничен ефект: наистина изгубен шофьор виси "онлайн" до 6 мин преди
да падне вместо 2. За платформата това е по-доброто — по-добре без
мигане, отколкото да чезнеш докато чакаш клиент.

Idempotent: ако вече е 6 минути, не прави нищо.
"""
import sys

PATH = 'src/worker.js'
OLD = 'const OFFLINE_AFTER_MS = 2 * 60 * 1000;'
NEW = 'const OFFLINE_AFTER_MS = 6 * 60 * 1000;'

src = open(PATH).read()

if NEW in src:
    print('вече е 6 минути — нищо за правене')
    sys.exit(0)

n = src.count(OLD)
if n != 1:
    print(f'ГРЕШКА: очаквах точно 1 съвпадение на anchor-а, намерих {n}')
    sys.exit(1)

src = src.replace(OLD, NEW)
open(PATH, 'w').write(src)
print('OFFLINE_AFTER_MS: 2 → 6 минути')
