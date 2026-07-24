# mvr-worker

Cloudflare Worker за fish.taxi / BAK / SEV.

## Ендпойнти
- `/health` — статус
- `/gps`, `/track`, `/presence`, `/status` — GPS и присъствие на шофьори
- `/register`, `/admin` — регистрация и админ
- `/risk` — KAT риск
- `/mvrfetch` — тесен whitelist proxy
- `/scrape?url=` — proxy за bot-защитени сайтове (allowlist, кеш 30 мин; live табла 2 мин)
- `/traffic?pts=lat,lng;lat,lng` — TomTom Flow Segment Data по отсечки (кеш 3 мин)

## Къде живеят ключовете
Нищо чувствително не се пази в repo-то — то е **публично**.

| Какво | Къде |
|---|---|
| Cloudflare API токен | GitHub secret `CLOUDFLARE_API_TOKEN` |
| TomTom ключ | D1 база `fishtaxi-config`, таблица `secrets`, ключ `TOMTOM_KEY` |
| GPS / кеш данни | KV `GPS_STORE` |

Worker-ът търси TomTom ключа по ред: `env.TOMTOM_KEY` → D1 `CONFIG_DB` → KV.

## Bindings
- KV `GPS_STORE` → `2900a1d9de0f49deac2359e558ba5783`
- D1 `CONFIG_DB` → `fishtaxi-config` (`06dc84d5-384c-44a6-8025-3884c4bbdc88`)

## Deploy
Автоматичен при push към `main`. Сглобява `src/worker.js` + `flights-snippet.js`
+ `scrape-snippet.js` и го качва през Cloudflare API. `keep_bindings` пази
secret-ите между deploy-ите.

Забележка: commit-и, направени от workflow (с `GITHUB_TOKEN`), не задействат
deploy — нужен е push с PAT или ръчно пускане на Deploy Worker.
