# -*- coding: utf-8 -*-
# mvr-proxy · FT-PUBID-REVERT-V1
#
# Връща GET /gps да праща ИСТИНСКО driver_id, както е било преди 26 авг.
# FT-PUBID-V1 (26 авг) подмени id-то с псевдоним и това счупи локацията:
# старият фронтенд съпоставя по истинско id и вече не намира шофьора.
#
# Приоритет сега: работеща локация > публична поверителност на номера.
# Номерът пак ще се вижда в /gps — точно както е било, когато е работило.
# Поверителността се връща по-късно, като се обнови фронтендът.
#
# Хваща и двете форми:
#   - без legacy_id (само FT-PUBID-V1)
#   - с legacy_id (днешният FT-LEGACYID-V1 отгоре)
# Идемпотентен: ако подмяната вече я няма, не прави нищо.
import io, sys

p = 'src/worker.js'
s = io.open(p, encoding='utf-8').read()
n0 = len(s)

# Форма 1: с днешния legacy_id patch отгоре
WITH_LEGACY = """          const pub = await maskIfOffline(env, d);
          /* FT-LEGACYID-V1: истинското id остава достъпно за стария
             фронтенд, който съпоставя по него. Псевдонимът важи паралелно. */
          pub.legacy_id = pub.driver_id;
          pub.driver_id = pubId(pub.driver_id);
          drivers.push(pub);"""

# Форма 2: само вчерашният pubId patch
PLAIN = """          const pub = await maskIfOffline(env, d);
          pub.driver_id = pubId(pub.driver_id);
          drivers.push(pub);"""

# Чисто: истинско id, без подмяна (състоянието отпреди 26 авг)
CLEAN = """          const pub = await maskIfOffline(env, d);
          /* FT-PUBID-REVERT-V1: истинско driver_id, както преди 26 авг.
             Псевдонимът е спрян до обновяване на фронтенда. */
          drivers.push(pub);"""

if WITH_LEGACY in s:
    s = s.replace(WITH_LEGACY, CLEAN)
    print('OK: revert от формата с legacy_id')
elif PLAIN in s:
    s = s.replace(PLAIN, CLEAN)
    print('OK: revert от формата само с pubId')
else:
    print('SKIP: подмяната на id вече я няма — нищо за връщане')
    sys.exit(0)

io.open(p, 'w', encoding='utf-8').write(s)
print('  %d -> %d chars' % (n0, len(s)))
