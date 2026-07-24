# -*- coding: utf-8 -*-
"""По-дълги отсечки: zoom 10 -> 8 в заявката към TomTom.
По-малкият zoom връща по-дълъг пътен фрагмент — отсечките спират да са къси
парченца и покриват участък между кръстовища."""
import re, sys

path = 'src/worker.js'
src = open(path, encoding='utf-8').read()

if 'flowSegmentData/absolute/8/json' in src:
    print('SKIP zoom вече е 8')
    sys.exit(0)

if 'flowSegmentData/absolute/10/json' in src:
    src = src.replace('flowSegmentData/absolute/10/json', 'flowSegmentData/absolute/8/json')
    open(path, 'w', encoding='utf-8').write(src)
    print('OK zoom 10 -> 8 (по-дълги отсечки)')
else:
    print('FAIL URL-ът към TomTom не е намерен')
    sys.exit(1)
