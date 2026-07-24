# -*- coding: utf-8 -*-
"""Добавя геометрията на отсечката в отговора на /traffic.
TomTom връща coordinates.coordinate[] — реалната линия на пътя.
Досега я изхвърляхме и оставаше само точка."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()

if 'coords:' in src and 'flowSegmentData' in src:
    print('SKIP геометрията вече се връща')
    sys.exit(0)

old = """              item = { cur: cur, free: free, curT: f.currentTravelTime, freeT: f.freeFlowTravelTime,
                       conf: f.confidence, closed: !!f.roadClosure,
                       ratio: (free ? Math.round((cur / free) * 100) / 100 : null) };"""

new = """              const rawC = (f.coordinates && f.coordinates.coordinate) || [];
              // прореждаме до ~90 точки, за да не тежи в KV
              const step = rawC.length > 90 ? Math.ceil(rawC.length / 90) : 1;
              const coords = [];
              for (let i = 0; i < rawC.length; i += step) {
                const c = rawC[i];
                if (c && c.latitude != null) {
                  coords.push([Math.round(c.latitude * 1e5) / 1e5,
                               Math.round(c.longitude * 1e5) / 1e5]);
                }
              }
              if (rawC.length && coords.length && step > 1) {
                const last = rawC[rawC.length - 1];
                if (last && last.latitude != null) {
                  coords.push([Math.round(last.latitude * 1e5) / 1e5,
                               Math.round(last.longitude * 1e5) / 1e5]);
                }
              }
              item = { cur: cur, free: free, curT: f.currentTravelTime, freeT: f.freeFlowTravelTime,
                       conf: f.confidence, closed: !!f.roadClosure, frc: f.frc,
                       ratio: (free ? Math.round((cur / free) * 100) / 100 : null),
                       coords: coords };"""

if old in src:
    src = src.replace(old, new, 1)
    open(path, 'w', encoding='utf-8').write(src)
    print('OK геометрията се връща (до ~90 точки на отсечка)')
else:
    # по-хлабав шаблон
    pat = re.compile(r'item = \{ cur: cur, free: free.*?ratio: \(free \? Math\.round\(\(cur / free\) \* 100\) / 100 : null\) \};', re.S)
    if pat.search(src):
        src = pat.sub(new.strip(), src, count=1)
        open(path, 'w', encoding='utf-8').write(src)
        print('OK геометрията се връща (хлабав шаблон)')
    else:
        print('FAIL конструкцията на item не е намерена')
        sys.exit(1)
