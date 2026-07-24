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
| `/traffic?pts=lat,lng;...` | TomTom Flow Segment — скорост **и геометрия** на отсечката, кеш 3 мин |

## Ключове

- `TOMTOM_KEY` — Worker secret. Може и в KV със същото име (worker-ът търси и на двете места).
- Никога не влиза в repo-то: то е **публично**.

## Deploy

`deploy.yml` при push към `main` сглобява `src/worker.js` + `flights-snippet.js` + `scrape-snippet.js`
и качва през Cloudflare API. `keep_bindings` пази secret-ите.

**Важно:** commit, направен от workflow с вградения `GITHUB_TOKEN`, НЕ задейства deploy.
След автоматичен патч трябва ръчен push (или `workflow_dispatch` на Deploy Worker).
