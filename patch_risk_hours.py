# -*- coding: utf-8 -*-
# mvr-proxy · FT-RISKHOURS-V1
#
# Проблем: KAT сайтът смята дневна оценка (engine.js, без час), а /risk връщаше
# само часово коригирано число. Едно и също нещо на два екрана с различни
# цифри — шофьорът спира да вярва на данните.
#
# Решение: /risk връща и двете. `score` вече е ДНЕВНОТО число, същото като
# KAT. Часовото идва отделно като hour_score с ясна причина (пиков/нощен час).
# Кешът пада на 15 мин, за да не се показва „пиков час" 40 минути след пика.
#
# Идемпотентен: втори пуск не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'FT-RISKHOURS-V1' in s:
    print('SKIP: FT-RISKHOURS-V1 вече е приложен'); sys.exit(0)

OLD1 = """        // Пиковият час не е част от KAT — там данните са дневни и не могат да го
        // проверят — но за шофьор е реален, затова се запазва.
        const hEff = (hour >= 7 && hour <= 9) || (hour >= 16 && hour <= 19) ? 1.12
                   : (hour >= 22 || hour <= 4) ? 1.08 : 1.0;

        const common = iEff * wEff * aEff * xEff * hEff;
        const coef  = rEff * cEff * WD[dow]  * MO[mon-1]  * common;
        const hCoef = hR   * hC   * HWD[dow] * HMO[mon-1] * common;
        const sc = (m, cuts) => { let s=1; for (const c of cuts) if (m>=c) s++; return Math.min(10, s); };
        const score = sc(coef, CUTS), harmScore = sc(hCoef, HCUTS);"""

NEW1 = """        /* FT-RISKHOURS-V1: дневното число се смята БЕЗ часовия коефициент,
           за да съвпада точно с KAT сайта. Часът се прилага отделно. */
        const hEff = (hour >= 7 && hour <= 9) || (hour >= 16 && hour <= 19) ? 1.12
                   : (hour >= 22 || hour <= 4) ? 1.08 : 1.0;
        const hourReason = hEff === 1.12 ? 'peak' : hEff === 1.08 ? 'night' : null;
        const hourLabel  = hourReason === 'peak' ? 'пиков час'
                         : hourReason === 'night' ? 'нощен час' : null;

        const common = iEff * wEff * aEff * xEff;
        const coef  = rEff * cEff * WD[dow]  * MO[mon-1]  * common;
        const hCoef = hR   * hC   * HWD[dow] * HMO[mon-1] * common;
        const sc = (m, cuts) => { let s=1; for (const c of cuts) if (m>=c) s++; return Math.min(10, s); };
        const score = sc(coef, CUTS), harmScore = sc(hCoef, HCUTS);
        const hourScore = sc(coef * hEff, CUTS), hourHarmScore = sc(hCoef * hEff, HCUTS);"""

OLD2 = """          car_score: score, harm_score: harmScore,
          harm_coefficient: Math.round(hCoef * 100) / 100,
          factors: {"""

NEW2 = """          car_score: score, harm_score: harmScore,
          harm_coefficient: Math.round(hCoef * 100) / 100,
          /* Дневните — същите като на KAT сайта. Часовите — за шофьора. */
          day_score: score, day_harm_score: harmScore,
          hour_score: hourScore, hour_harm_score: hourHarmScore,
          hour_factor: hEff, hour_reason: hourReason, hour_label: hourLabel,
          factors: {"""

OLD3 = "try { await env.GPS_STORE.put('risk:current', result, { expirationTtl: 2400 }); } catch (e) {}"
NEW3 = "try { await env.GPS_STORE.put('risk:current', result, { expirationTtl: 900 }); } catch (e) {}"

for i, (o, n) in enumerate([(OLD1, NEW1), (OLD2, NEW2), (OLD3, NEW3)], 1):
    c = s.count(o)
    if c != 1:
        print('FAIL: котва %d се среща %d пъти, очаква се 1' % (i, c)); sys.exit(1)
    s = s.replace(o, n)

io.open(p, 'w', encoding='utf-8').write(s)
print('OK  FT-RISKHOURS-V1 приложен  %d -> %d chars' % (n0, len(s)))
