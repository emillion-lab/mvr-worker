# -*- coding: utf-8 -*-
"""Добавя /traffic ендпойнт в worker.js (TomTom Flow Segment Data).
Ключът НЕ е в кода: env.TOMTOM_KEY (Worker secret). Кеш 3 мин в KV.
v2: сам намира къде се разклоняват маршрутите и докладва реалната структура."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()
log = []

if "'/traffic'" in src or '"/traffic"' in src:
    print('SKIP /traffic вече съществува')
    sys.exit(0)

# какви ендпойнти има изобщо
eps = sorted(set(re.findall(r"""['"](/[a-zA-Z0-9_\-]{2,24})['"]""", src)))
log.append('намерени пътища: ' + ', '.join(eps[:30]))

# как се сравнява пътят
forms = []
for rx, label in [
    (r"path\s*===\s*['\"]/", "path === '/...'"),
    (r"pathname\s*===\s*['\"]/", "pathname === '/...'"),
    (r"url\.pathname\s*===\s*['\"]/", "url.pathname === '/...'"),
    (r"path\.startsWith\(['\"]/", "path.startsWith('/...')"),
    (r"case\s*['\"]/", "switch/case '/...'"),
]:
    n = len(re.findall(rx, src))
    if n:
        forms.append('%s x%d' % (label, n))
log.append('форми на рутиране: ' + (', '.join(forms) or 'НЕЯСНО'))

# намираме първото разклонение по път и се закачаме ПРЕДИ него
m = None
for rx in (r"\n([ \t]*)if\s*\(\s*(?:url\.)?path(?:name)?\s*===\s*['\"]/",
           r"\n([ \t]*)if\s*\(\s*(?:url\.)?path(?:name)?\.startsWith\(\s*['\"]/",
           r"\n([ \t]*)case\s+['\"]/"):
    m = re.search(rx, src)
    if m:
        break
if not m:
    open('traffic-patch-report.txt', 'w', encoding='utf-8').write('\n'.join(log) + '\nFAIL: няма разпознато рутиране\n')
    print('\n'.join(log))
    print('FAIL няма разпознато рутиране')
    sys.exit(1)

indent = m.group(1)
pos = m.start() + 1
ln = src.count('\n', 0, pos) + 1
log.append('вмъквам преди ред %d (отстъп %d интервала)' % (ln, len(indent)))

BLOCK = """// ── TomTom трафик по отсечки (кеш 3 мин; ключът е Worker secret) ──
if (path === '/traffic' && request.method === 'GET') {
  try {
    if (!env.TOMTOM_KEY) {
      return new Response(JSON.stringify({ error: 'TOMTOM_KEY не е зададен' }),
        { status: 503, headers: { ...CORS, 'Content-Type': 'application/json' } });
    }
    const pts = url.searchParams.get('pts');
    if (!pts) {
      return new Response(JSON.stringify({ error: 'missing ?pts=lat,lng;lat,lng' }),
        { status: 400, headers: { ...CORS, 'Content-Type': 'application/json' } });
    }
    const list = pts.split(';').slice(0, 12);
    const out = [];
    for (const p of list) {
      const parts = p.split(',');
      const la = parseFloat(parts[0]), ln = parseFloat(parts[1]);
      if (!isFinite(la) || !isFinite(ln)) { out.push(null); continue; }
      const ck = 'tt:' + la.toFixed(4) + ',' + ln.toFixed(4);
      const cached = await env.GPS_STORE.get(ck);
      if (cached && url.searchParams.get('fresh') !== '1') {
        try { out.push(JSON.parse(cached)); continue; } catch (e) {}
      }
      const tu = 'https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json'
               + '?key=' + env.TOMTOM_KEY + '&point=' + la + ',' + ln + '&unit=KMPH';
      let item;
      try {
        const r = await fetch(tu, { cf: { cacheTtl: 120, cacheEverything: true } });
        if (!r.ok) { item = { err: r.status }; }
        else {
          const d = await r.json();
          const f = (d && d.flowSegmentData) || {};
          const cur = f.currentSpeed, free = f.freeFlowSpeed;
          item = { cur: cur, free: free, curT: f.currentTravelTime, freeT: f.freeFlowTravelTime,
                   conf: f.confidence, closed: !!f.roadClosure,
                   ratio: (free ? Math.round((cur / free) * 100) / 100 : null) };
        }
      } catch (e) { item = { err: String(e).slice(0, 60) }; }
      if (!item.err) {
        try { await env.GPS_STORE.put(ck, JSON.stringify(item), { expirationTtl: 180 }); } catch (e) {}
      }
      out.push(item);
    }
    return new Response(JSON.stringify({ updated: new Date().toISOString(), data: out }),
      { headers: { ...CORS, 'Content-Type': 'application/json' } });
  } catch (e) {
    return new Response(JSON.stringify({ error: e.message }),
      { status: 502, headers: { ...CORS, 'Content-Type': 'application/json' } });
  }
}

"""
block = '\n'.join((indent + l) if l.strip() else l for l in BLOCK.split('\n'))
src = src[:pos] + block + src[pos:]
open(path, 'w', encoding='utf-8').write(src)
log.append('OK /traffic вмъкнат')
open('traffic-patch-report.txt', 'w', encoding='utf-8').write('\n'.join(log) + '\n')
print('\n'.join(log))
