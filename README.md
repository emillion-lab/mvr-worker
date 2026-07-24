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
| `/traffic?pts=lat,lng;...` | TomTom Flow Segment — скорост + геометрия, кеш 4 мин |

## TomTom квота

Безплатният план е **2500 заявки/ден**. Защити:

- кеш 4 минути в KV → максимум 15 заявки/час на отсечка, независимо колко клиента гледат
- при 6 отсечки: 90/час → 2160/ден дори при денонощна работа
- дневен брояч `tt:count:YYYY-MM-DD`; при 2200 спира да пита TomTom
- резервен запис `tt:last:*` за 24ч — при изчерпана квота се връща последната известна стойност вместо грешка

## Ключове

- `TOMTOM_KEY` — Worker secret. Може и в KV със същото име (worker-ът търси и на двете места).
- Никога не влиза в repo-то: то е **публично**.

## Deploy

`deploy.yml` при push към `main` сглобява `src/worker.js` + `flights-snippet.js` + `scrape-snippet.js`
и качва през Cloudflare API. `keep_bindings` пази secret-ите.

**Важно:** commit, направен от workflow с вградения `GITHUB_TOKEN`, НЕ задейства deploy.
След автоматичен патч трябва ръчен push (или `workflow_dispatch` на Deploy Worker).
