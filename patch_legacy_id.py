# -*- coding: utf-8 -*-
# mvr-proxy · FT-LEGACYID-V1
#
# Проблем: вчерашният FT-PUBID-V1 подменя driver_id с псевдоним в GET /gps.
# Старият фронтенд (index.html, v2026.07.13-d) съпоставя GPS запис с профил
# по ИСТИНСКО id — вече не намира записа, шофьорът излиза офлайн в центъра.
#
# Решение без гадаене: до псевдонима слагаме и legacy_id с истинското id.
# Работи независимо кой ключ чете фронтендът:
#   - чете истинско id  -> намира legacy_id, връща се онлайн
#   - чете псевдоним    -> него вече го има, нищо не се чупи
#
# Обратимо: махането на реда връща състоянието отпреди patch-а.
# Идемпотентен: втори пуск не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

if 'FT-LEGACYID-V1' in s:
    print('SKIP: legacy_id patch already applied'); sys.exit(0)

# Котва: точно блокът, който FT-PUBID-V1 е вмъкнал в GET /gps.
OLD = """          const pub = await maskIfOffline(env, d);
          pub.driver_id = pubId(pub.driver_id);
          drivers.push(pub);"""

NEW = """          const pub = await maskIfOffline(env, d);
          /* FT-LEGACYID-V1: истинското id остава достъпно за стария
             фронтенд, който съпоставя по него. Псевдонимът важи паралелно. */
          pub.legacy_id = pub.driver_id;
          pub.driver_id = pubId(pub.driver_id);
          drivers.push(pub);"""

c = s.count(OLD)
if c != 1:
    print('FAIL: котвата се среща %d пъти, очаква се 1.' % c)
    print('Вероятно FT-PUBID-V1 не е приложен или блокът е различен.')
    sys.exit(1)

s = s.replace(OLD, NEW)
io.open(p, 'w', encoding='utf-8').write(s)
print('OK  FT-LEGACYID-V1 приложен  %d -> %d chars' % (n0, len(s)))
