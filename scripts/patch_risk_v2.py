"""Заменя /risk в mvr-proxy с преизчисления модел.

Шофьорското приложение НЕ смята риска само — тегли го от този endpoint.
Затова екранът показваше 0.88× "Спокойна среда" и "Kp 2.0", докато KAT
показва 6/10 и 6/10: тук стоеше целият стар модел.

Какво отпада (проверено върху 4018 дни МВР 2015–2025 и потвърдено в UK/US):
  kpEff  — геомагнитни бури, r=-0.023, нищо при закъснения 0–7 дни
  mEff   — лунна фаза, проверена в три държави, фазите се разминават
  pEff   — Δ налягане, r=-0.060
  inter  — взаимодействието Kp×налягане, следва от горните
  dEff   — старите дневни коефициенти бяха сериозно сгрешени: четвъртък
           1.28 срещу реални 1.05, понеделник 0.88 срещу 1.07. Out-of-sample
           даваха R²=-0.26, тоест по-зле от това да не се прави нищо.

Какво влиза: валеж и сняг (най-силните фактори), облачност, лед, вятър,
правилните дневни и месечни коефициенти, празници, предколеден трафик,
новогодишна яма, денонощна амплитуда.

Пиковият час (hEff) СЕ ЗАПАЗВА. Той не е част от KAT — там данните са дневни
и не могат да го проверят — но за шофьор е реален и полезен.

Отговорът пази старите полета (coefficient, score, level, label, factors),
за да не се чупи приложението, и добавя новите две скали.
"""
import io

src = io.open('src/worker.js', encoding='utf-8').read()
count = 0

def rep(old, new):
    global src, count
    c = src.count(old)
    assert c == 1, 'MARKER x%d: %r' % (c, old[:80])
    src = src.replace(old, new); count += 1

rep("""        // Kp от NOAA
        let kp = 2;
        try {
          const kpResp = await fetch('https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json');
          const kpData = await kpResp.json();
          kp = parseFloat(kpData[kpData.length - 1][1]) || 2;
        } catch (e) {}
        // Налягане София: сега vs преди 24ч (Open-Meteo, безплатно)
        let dp = 0;
        try {
          const pResp = await fetch('https://api.open-meteo.com/v1/forecast?latitude=42.6977&longitude=23.3219&hourly=surface_pressure&past_days=1&forecast_days=1');
          const pData = await pResp.json();
          const hrs = pData.hourly.surface_pressure;
          const nowIdx = new Date().getUTCHours() + 24;
          dp = Math.abs((hrs[nowIdx] || 0) - (hrs[nowIdx - 24] || 0));
        } catch (e) {}
        // Лунна възраст (локална математика)
        // точна възраст спрямо референтно новолуние (6 ян 2000, 18:14 UTC)
        const MOON_REF = Date.UTC(2000, 0, 6, 18, 14), MOON_SYN = 29.530588853 * 86400000;
        const moonAge = ((((Date.now() - MOON_REF) % MOON_SYN) + MOON_SYN) % MOON_SYN) / 86400000;
        const now = new Date(Date.now() + 3 * 3600000); // София ≈ UTC+3 лято
        const dow = now.getUTCDay();
        const hour = now.getUTCHours();
        // KAT формули
        const kpEff = kp >= 7.5 ? 0.95 : kp >= 6 ? 1.08 : kp >= 5 ? 1.14 : kp >= 3 ? 1.05 : 1.0;
        const pEff = dp >= 10 ? 1.14 : dp >= 5 ? 1.08 : dp >= 2 ? 1.03 : 1.0;
        const mNorm = Math.abs(Math.sin((moonAge / 29.530588853) * Math.PI));
        const mEff = mNorm > 0.85 ? 1.06 : mNorm > 0.6 ? 1.03 : 1.0;
        const dEff = [0.82, 0.88, 0.93, 0.98, 1.28, 1.22, 0.78][dow] || 1.0;
        const inter = (kp >= 5 && dp >= 10) ? 1.08 : 1.0;
        // Пиков час (добавка за шофьори)
        const hEff = (hour >= 7 && hour <= 9) || (hour >= 16 && hour <= 19) ? 1.12
                   : (hour >= 22 || hour <= 4) ? 1.08 : 1.0;
        const coef = kpEff * pEff * mEff * dEff * inter * hEff;
        const score = Math.min(10, Math.max(0, Math.round((coef - 0.8) * 12)));
        const level = score <= 2 ? 0 : score <= 5 ? 1 : score <= 7 ? 2 : 3;
        const labels = ['Спокойна среда', 'Леко напрежение', 'Повишен стрес', 'Критично'];
        const result = JSON.stringify({
          ok: true, coefficient: Math.round(coef * 100) / 100, score, level, label: labels[level],
          factors: { kp: Math.round(kp * 10) / 10, pressure_delta: Math.round(dp * 10) / 10,
                     moon_age: Math.round(moonAge * 10) / 10, dow, hour, rush: hEff > 1.0 },
          kat_url: 'https://emillion-lab.github.io/KAT/', updated: Date.now()
        });""",
"""        // ═══ RISK_V2 — калибрирано върху 4018 дни МВР (2015–2025) ═══
        // Геомагнитни бури, лунна фаза и Δ налягане са проверени и отпаднали.
        // Валежът е най-силният фактор (r=+0.366), следван от облачността.
        let rain = 0, snow = 0, tmin = null, tmax = null, wind = null, sun = null;
        try {
          const w = await fetch('https://api.open-meteo.com/v1/forecast?latitude=42.6977&longitude=23.3219'
            + '&daily=precipitation_sum,snowfall_sum,temperature_2m_min,temperature_2m_max,'
            + 'wind_speed_10m_max,sunshine_duration,daylight_duration&forecast_days=1&timezone=Europe%2FSofia');
          const d = (await w.json()).daily;
          rain = d.precipitation_sum?.[0] ?? 0;
          snow = d.snowfall_sum?.[0] ?? 0;
          tmin = d.temperature_2m_min?.[0]; tmax = d.temperature_2m_max?.[0];
          wind = d.wind_speed_10m_max?.[0];
          if (d.sunshine_duration?.[0] != null && d.daylight_duration?.[0])
            sun = d.sunshine_duration[0] / d.daylight_duration[0];
        } catch (e) {}

        const now = new Date(Date.now() + 3 * 3600000);   // София ≈ UTC+3
        const dow = now.getUTCDay(), mon = now.getUTCMonth() + 1, dom = now.getUTCDate();
        const hour = now.getUTCHours();

        const WD = [0.797,1.074,1.037,1.014,1.052,1.120,0.905];
        const MO = [0.943,0.916,0.888,0.923,0.963,1.056,1.088,1.106,1.063,1.065,1.013,0.970];
        const HWD = [1.007,0.942,1.046,0.959,0.939,1.004,1.102];
        const HMO = [0.741,0.736,0.791,0.861,1.001,1.154,1.263,1.319,1.148,1.032,1.008,0.927];
        const CUTS  = [0.837,0.926,0.987,1.038,1.078,1.122,1.175,1.289,1.474];
        const HCUTS = [0.771,0.894,0.977,1.047,1.123,1.200,1.253,1.333,1.411];

        let rEff = rain>=20?1.347 : rain>=10?1.200 : rain>=5?1.113
                 : rain>=2?1.044  : rain>=0.5?1.004 : 0.964;
        if (snow>=5) rEff=Math.max(rEff,1.404);
        else if (snow>=2) rEff=Math.max(rEff,1.243);
        else if (snow>=0.5) rEff=Math.max(rEff,1.052);

        let hR = rain>=20?1.301 : rain>=10?1.178 : rain>=5?1.062
               : rain>=2?1.019  : rain>=0.5?0.988 : 0.978;
        if (snow>=5) hR=Math.max(hR,1.239);
        else if (snow>=2) hR=Math.max(hR,1.106);
        else if (snow>=0.5) hR=Math.max(hR,0.957);

        const cEff = sun==null?1.0 : sun<0.15?1.175 : sun<0.35?1.071 : sun<0.55?1.026 : sun<0.75?0.999 : 0.975;
        const hC   = sun==null?1.0 : sun<0.15?1.142 : sun<0.35?1.043 : sun<0.55?0.948 : sun<0.75?0.979 : 0.988;
        const iEff = tmin==null?1.0 : (tmin<=0 && rain+snow>0.5)?1.18 : tmin<=-3?1.06 : tmin<=0?1.03 : 1.0;
        const wEff = wind==null?1.0 : wind>=60?1.09 : wind>=40?1.04 : 1.0;
        let aEff = 1.0;
        if (tmin!=null && tmax!=null && !(sun!=null && sun<0.6)) {
          const rg = tmax - tmin, spring = mon>=3 && mon<=5;
          if (rg>=17) aEff = spring?1.061:1.046; else if (rg>=14) aEff = spring?1.033:1.022;
        }
        let xEff = 1.0;
        if (mon===1) xEff = dom===1?0.547 : dom===2?0.774 : 1.0;
        else if (mon===12) xEff = dom===31?0.561 : dom>=27?0.85 : dom>=24?1.0
                                : dom===23?1.35 : dom>=21?1.22 : dom>=19?1.18 : dom>=16?1.12 : 1.0;

        // Пиковият час не е част от KAT — там данните са дневни и не могат да го
        // проверят — но за шофьор е реален, затова се запазва.
        const hEff = (hour >= 7 && hour <= 9) || (hour >= 16 && hour <= 19) ? 1.12
                   : (hour >= 22 || hour <= 4) ? 1.08 : 1.0;

        const common = iEff * wEff * aEff * xEff * hEff;
        const coef  = rEff * cEff * WD[dow]  * MO[mon-1]  * common;
        const hCoef = hR   * hC   * HWD[dow] * HMO[mon-1] * common;
        const sc = (m, cuts) => { let s=1; for (const c of cuts) if (m>=c) s++; return Math.min(10, s); };
        const score = sc(coef, CUTS), harmScore = sc(hCoef, HCUTS);
        const level = score <= 3 ? 0 : score <= 6 ? 1 : score <= 8 ? 2 : 3;
        const labels = ['Спокойна среда', 'Обичайно', 'Повишено внимание', 'Висок риск'];
        const result = JSON.stringify({
          ok: true, coefficient: Math.round(coef * 100) / 100, score, level, label: labels[level],
          car_score: score, harm_score: harmScore,
          harm_coefficient: Math.round(hCoef * 100) / 100,
          factors: { rain: Math.round(rain*10)/10, snow: Math.round(snow*10)/10,
                     cloud: sun==null?null:Math.round((1-sun)*100),
                     tmin, tmax, wind, dow, mon, hour, rush: hEff > 1.0 },
          model: 'KAT v3 · МВР 2015–2025',
          kat_url: 'https://emillion-lab.github.io/KAT/', updated: Date.now()
        });""")

io.open('src/worker.js', 'w', encoding='utf-8').write(src)
print('PATCHED %d blocks OK' % count)
