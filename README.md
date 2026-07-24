# mvr-worker

Cloudflare Worker за fish.taxi / BAK екосистемата.

Публичен адрес: `https://mvr-proxy.mihov-emil.workers.dev`

## Ендпойнти

| Път | Какво прави |
|---|---|
| `/health` | статус на worker-а |
| `/gps`, `/track`, `/presence` | GPS позиции на шофьорите (KV: `GPS_STORE`) |
| `/register`, `/admin`, `/status` | регистрация и админ |
| `/risk` | KAT риск данни |
| `/mvrfetch` | тесен whitelist прокси |
| `/scrape?url=` | прокси за bot-защитени сайтове (allowlist, кеш 30 мин) |
| `/traffic?pts=lat,lng;...` | TomTom Flow Segment — скорост + геометрия, до 20 точки, zoom 8 |

## TomTom квота

Безплатно: **2500 не-tile заявки/ден** (плюс отделни 50 000 tile заявки).

Кешът следва натоварването на деня:

| Период | Кеш | Заявки/час на отсечка |
|---|---|---|
| 08–10 и 17–19 (пик) | 5 мин | 12 |
| 06–08, 10–17, 19–21 | 10 мин | 6 |
| 21–23 | 30 мин | 2 |
| 23–06 | 60 мин | 1 |

**125 заявки на отсечка на ден.** При 15 отсечки → **1875 от 2500**.

Защити: дневен брояч `tt:count:YYYY-MM-DD` (спира при 2400) и резервен
запис `tt:last:*` за 24ч, който се връща при изчерпана квота.

`zoom=8` в заявката дава по-дълги фрагменти (участък между кръстовища),
вместо къси парченца. По-малък zoom = по-дълга отсечка.

## Ключове

- `TOMTOM_KEY` — Worker secret. Може и в KV със същото име (worker-ът търси и на двете места).
- Никога не влиза в repo-то: то е **публично**.

## Deploy

`deploy.yml` при push към `main` сглобява `src/worker.js` + `flights-snippet.js` + `scrape-snippet.js`
и качва през Cloudflare API. `keep_bindings` пази secret-ите.

**Важно:** commit, направен от workflow с вградения `GITHUB_TOKEN`, НЕ задейства deploy.
След автоматичен патч трябва ръчен push (или `workflow_dispatch` на Deploy Worker).
