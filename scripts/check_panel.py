# -*- coding: utf-8 -*-
"""Проверява JS-а, който браузърът НАИСТИНА получава от /admin.

`node --check src/worker.js` не хваща грешки вътре в панела, защото там
скриптът е низ в template literal — синтактично валиден низ, който може да
съдържа напълно счупен JavaScript. Точно това се случи: inline onclick с
екранирани кавички се свеждаше до залепени низове и целият <script> спираше
да се парсва, без нито едно съобщение на екрана.

Затова тук панелът се изрязва, template literal escape-ите се разгръщат
както ги разгръща JS, и резултатът се подава на `node --check` отделно.
"""
import io, os, subprocess, sys

s = io.open('src/worker.js', encoding='utf-8').read()

start = s.index('const html = `') + len('const html = `')
end = s.index('`;', start)
panel = s[start:end]

# template literal-ът превръща \' в ' и \" в " още преди браузърът да види низа
served = panel.replace("\\'", "'").replace('\\"', '"')

js = served[served.index('<script>') + len('<script>'):served.index('</script>')]
io.open('/tmp/served_panel.js', 'w', encoding='utf-8').write(js)

r = subprocess.run(['node', '--check', '/tmp/served_panel.js'],
                   capture_output=True, text=True)
if r.returncode != 0:
    print('ПАНЕЛЪТ Е СЧУПЕН — сервираният JS не се парсва:')
    print(r.stderr)
    sys.exit(1)

print('сервираният панел JS се парсва чисто (%d знака)' % len(js))
