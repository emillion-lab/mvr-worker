# -*- coding: utf-8 -*-
"""Адаптивен кеш по часове (идея на Емил):
  08–10 и 17–19 пик      -> 5 мин
  06–08, 10–17, 19–21    -> 10 мин
  21–23                  -> 30 мин
  23–06                  -> 60 мин
Разход: 125 заявки на отсечка на ден (беше 269) -> място за ~19 улици."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()
log = []

if 'TT_SCHEDULE' in src:
    print('SKIP графикът вече е сложен')
    sys.exit(0)

old_variants = [
    """          const sofiaH = (new Date().getUTCHours() + 3) % 24;
          const TT_NIGHT = (sofiaH >= 23 || sofiaH < 6);
          const TT_TTL = TT_NIGHT ? 1800 : 480;""",
    """          const sofiaH = (new Date().getUTCHours() + 3) % 24;
          const TT_NIGHT = (sofiaH >= 23 || sofiaH < 6);
          const TT_TTL = TT_NIGHT ? 1800 : 240;""",
]

new = """          // TT_SCHEDULE — кешът следва натоварването на деня
          const sofiaH = (new Date().getUTCHours() + 3) % 24;
          let TT_TTL;
          if (sofiaH >= 23 || sofiaH < 6) TT_TTL = 3600;                    // нощ: 60 мин
          else if (sofiaH >= 21) TT_TTL = 1800;                             // късна вечер: 30 мин
          else if ((sofiaH >= 8 && sofiaH < 10) ||
                   (sofiaH >= 17 && sofiaH < 19)) TT_TTL = 300;             // пик: 5 мин
          else TT_TTL = 600;                                                // ден: 10 мин
          const TT_NIGHT = (TT_TTL >= 1800);"""

done = False
for old in old_variants:
    if old in src:
        src = src.replace(old, new, 1)
        log.append('OK адаптивен график: пик 5м / ден 10м / вечер 30м / нощ 60м')
        done = True
        break
if not done:
    pat = re.compile(r'const sofiaH = \(new Date\(\)\.getUTCHours\(\) \+ 3\) % 24;.*?const TT_TTL = [^;]+;', re.S)
    if pat.search(src):
        src = pat.sub(new.strip(), src, count=1)
        log.append('OK адаптивен график (хлабав шаблон)')
    else:
        log.append('FAIL старият TTL блок не е намерен')
        open('traffic-patch-report.txt', 'a', encoding='utf-8').write('\n'.join(log) + '\n')
        print('\n'.join(log))
        sys.exit(1)

# до 20 точки на заявка
if "slice(0, 12)" in src:
    src = src.replace("slice(0, 12)", "slice(0, 20)")
    log.append('OK до 20 точки на заявка')

# предпазител 2400
for old_cap in ('TT_DAILY_CAP = 2200', 'TT_DAILY_CAP = 2100'):
    if old_cap in src:
        src = src.replace(old_cap, 'TT_DAILY_CAP = 2400')
        log.append('OK дневен предпазител -> 2400')
        break

open(path, 'w', encoding='utf-8').write(src)
print('\n'.join(log))
