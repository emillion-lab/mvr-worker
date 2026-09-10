# -*- coding: utf-8 -*-
# mvr-proxy · FT-NEXTPEAK-V1
#
# Целта: сайтът да казва кога иде следващият пик, вместо да рисува
# 24-часова графика. Прозорците са фиксирани и НЕ идват от данните на МВР
# (там има само дневни числа), затова се смятат на едно място — тук — и се
# раздават наготово, за да не се появи втора сметка във фронтенда.
#
# Идемпотентен: втори пуск не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'FT-NEXTPEAK-V1' in s:
    print('SKIP: FT-NEXTPEAK-V1 вече е приложен'); sys.exit(0)

OLD1 = "        const hourScore = sc(coef * hEff, CUTS), hourHarmScore = sc(hCoef * hEff, HCUTS);"

NEW1 = """        const hourScore = sc(coef * hEff, CUTS), hourHarmScore = sc(hCoef * hEff, HCUTS);

        /* FT-NEXTPEAK-V1: кой е следващият прозорец с повишен коефициент.
           Три фиксирани прозореца, същите множители като hEff по-горе. */
        const PEAKS = [
          { from: 7,  to: 9,  f: 1.12, name: 'сутрешен пик' },
          { from: 16, to: 19, f: 1.12, name: 'следобеден пик' },
          { from: 22, to: 4,  f: 1.08, name: 'нощен прозорец' }
        ];
        const inWin = (h, w) => w.from <= w.to ? (h >= w.from && h <= w.to)
                                               : (h >= w.from || h <= w.to);
        const activeWin = PEAKS.find(w => inWin(hour, w));
        const nextWin = activeWin || PEAKS
          .map(w => ({ w, d: (w.from - hour + 24) % 24 }))
          .sort((a, b) => a.d - b.d)[0].w;
        const nextPeak = {
          name: nextWin.name, from: nextWin.from, to: nextWin.to,
          active: !!activeWin,
          in_hours: activeWin ? 0 : (nextWin.from - hour + 24) % 24,
          score: sc(coef * nextWin.f, CUTS),
          harm_score: sc(hCoef * nextWin.f, HCUTS)
        };"""

OLD2 = "          hour_factor: hEff, hour_reason: hourReason, hour_label: hourLabel,"
NEW2 = """          hour_factor: hEff, hour_reason: hourReason, hour_label: hourLabel,
          next_peak: nextPeak,"""

for i, (o, n) in enumerate([(OLD1, NEW1), (OLD2, NEW2)], 1):
    c = s.count(o)
    if c != 1:
        print('FAIL: котва %d се среща %d пъти, очаква се 1' % (i, c)); sys.exit(1)
    s = s.replace(o, n)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK  FT-NEXTPEAK-V1 приложен  %d -> %d chars' % (n0, len(s)))
