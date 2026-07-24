# -*- coding: utf-8 -*-
"""Пази безплатната квота на TomTom:
1) кешът става 4 минути вместо 3 (по-малко заявки при същата полезност)
2) дневен брояч в KV — при доближаване на лимита спира да пита TomTom
   и връща последната известна стойност, вместо да трупа такси."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()

if 'TT_DAILY_CAP' in src:
    print('SKIP предпазителят вече е сложен')
    sys.exit(0)

# 1) TTL 180 -> 240
n = src.count("expirationTtl: 180")
if n:
    src = src.replace("expirationTtl: 180", "expirationTtl: 240")
    print('OK кешът за трафик: 180 -> 240 сек (%d места)' % n)

# 2) дневен брояч
old = """          const tu = 'https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json'"""
new = """          // дневен предпазител за безплатната квота
          const TT_DAILY_CAP = 2200;
          const dayKey = 'tt:count:' + new Date().toISOString().slice(0, 10);
          let used = 0;
          try { used = parseInt((await env.GPS_STORE.get(dayKey)) || '0', 10) || 0; } catch (e) {}
          if (used >= TT_DAILY_CAP) {
            let stale = null;
            try { stale = await env.GPS_STORE.get('tt:last:' + ck); } catch (e) {}
            if (stale) { try { out.push(JSON.parse(stale)); continue; } catch (e) {} }
            out.push({ err: 'quota', used: used });
            continue;
          }
          const tu = 'https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json'"""

if old in src:
    src = src.replace(old, new, 1)
    print('OK дневен предпазител при 2200 заявки')
else:
    print('FAIL заявката към TomTom не е намерена')
    sys.exit(1)

# 3) увеличаване на брояча + дълготраен резервен запис
old2 = """          if (!item.err) {
            try { await env.GPS_STORE.put(ck, JSON.stringify(item), { expirationTtl: 240 }); } catch (e) {}
          }"""
new2 = """          if (!item.err) {
            try { await env.GPS_STORE.put(ck, JSON.stringify(item), { expirationTtl: 240 }); } catch (e) {}
            // резервен запис за 24ч — ползва се ако свърши квотата
            try { await env.GPS_STORE.put('tt:last:' + ck, JSON.stringify(item), { expirationTtl: 86400 }); } catch (e) {}
            try { await env.GPS_STORE.put(dayKey, String(used + 1), { expirationTtl: 172800 }); } catch (e) {}
          }"""
if old2 in src:
    src = src.replace(old2, new2, 1)
    print('OK брояч + резервен запис за 24ч')
else:
    print('⚠ мястото за записване на кеша не е намерено — броячът няма да расте')

open(path, 'w', encoding='utf-8').write(src)
