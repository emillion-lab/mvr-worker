export default {
  async fetch(request) {
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET',
      'Content-Type': 'application/json; charset=utf-8',
    };
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors });

    const MVR_URLS = [
      'https://www.mvr.bg/press/%D0%B0%D0%BA%D1%82%D1%83%D0%B0%D0%BB%D0%BD%D0%B0-%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D1%8F/%D0%B0%D0%BA%D1%82%D1%83%D0%B0%D0%BB%D0%BD%D0%B0-%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D1%8F/%D0%BF%D1%8A%D1%82%D0%BD%D0%B0-%D0%BE%D0%B1%D1%81%D1%82%D0%B0%D0%BD%D0%BE%D0%B2%D0%BA%D0%B0',
      'https://www.mvr.bg/press',
    ];
    const HDRS = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'bg-BG,bg;q=0.9,en;q=0.8',
      'Referer': 'https://www.mvr.bg/',
    };
    const BG_MONTHS = {'януари':1,'февруари':2,'март':3,'април':4,'май':5,'юни':6,'юли':7,'август':8,'септември':9,'октомври':10,'ноември':11,'декември':12};

    function parseDate(text) {
      const m = text.toLowerCase().match(/(\d{1,2})\s+(януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември)\s+(\d{4})/);
      if (!m) return null;
      const mo = BG_MONTHS[m[2]];
      return mo ? `${m[3]}-${String(mo).padStart(2,'0')}-${String(m[1]).padStart(2,'0')}` : null;
    }
    function parseAccidents(html) {
      const t = html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ');
      const find = ps => { for(const p of ps){const m=t.match(new RegExp(p,'iu'));if(m)for(const g of m.slice(1))if(g&&/^\d+$/.test(g))return parseInt(g);} return null; };
      const light=find([/([\d]+)\s+леки\s+(?:пътно)?транспортни/,/([\d]+)\s+леки\s+ПТП/]);
      const serious=find([/([\d]+)\s+тежки\s+(?:пътно)?транспортни/,/([\d]+)\s+тежки\s+ПТП/]);
      const dead=find([/([\d]+)\s+(?:са\s+)?загинали/,/([\d]+)\s+(?:човека?\s+)?загина/]);
      const injured=find([/([\d]+)\s+(?:са\s+)?ранени/,/([\d]+)\s+пострадали/]);
      return {light,serious,dead,injured,total:light!=null&&serious!=null?light+serious:light};
    }
    function extractLinks(html) {
      const links=[],seen=new Set();
      for(const pat of[/href="(\/press[^"]*(?:пътна|произшествия)[^"]*)"/gi,/href="(\/press\/[^"]+\/\d{4}\/[^"]+)"/gi,/href="(\/press\/[^"]*актуална[^"]*)"/gi]){
        let m; while((m=pat.exec(html))!==null){const u='https://www.mvr.bg'+m[1];if(!seen.has(u)){seen.add(u);links.push(u);}}
      }
      return links.slice(0,8);
    }

    try {
      let listHtml=null,listStatus=0;
      for(const url of MVR_URLS){const r=await fetch(url,{headers:HDRS});listStatus=r.status;if(r.ok){listHtml=await r.text();break;}}
      if(!listHtml) return new Response(JSON.stringify({error:`MVR HTTP ${listStatus}`,days:[],days_count:0,updated:new Date().toISOString()}),{headers:cors});

      const links=extractLinks(listHtml),days=[];
      for(const url of links){
        try{
          const r=await fetch(url,{headers:HDRS});if(!r.ok)continue;
          const html=await r.text();
          const ud=url.match(/\/(\d{4})\/(\d{1,2})\/(\d{1,2})\//);
          const date=ud?`${ud[1]}-${ud[2].padStart(2,'0')}-${ud[3].padStart(2,'0')}`:parseDate(html.slice(0,4000));
          if(!date)continue;
          days.push({date,url,...parseAccidents(html),scraped_at:new Date().toISOString()});
        }catch(e){}
      }
      days.sort((a,b)=>b.date.localeCompare(a.date));
      return new Response(JSON.stringify({updated:new Date().toISOString(),source:'МВР via Cloudflare Worker',days_count:days.length,links_found:links.length,days},null,2),{headers:cors});
    } catch(e) {
      return new Response(JSON.stringify({error:e.message,days:[],days_count:0,updated:new Date().toISOString()}),{headers:cors});
    }
  }
};