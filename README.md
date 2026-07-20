# mvr-worker

Cloudflare Worker (mvr-proxy): GPS, регистрации, admin, /risk, /flights/{IATA}, /mvrfetch proxy.

Деплой: push към main → CI качва build-нат worker (src/worker.js + src/flights-snippet.js) и пише deploy-report.txt с живи тестове.
