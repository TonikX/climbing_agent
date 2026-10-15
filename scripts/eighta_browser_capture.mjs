// Run only inside the authorised cua_repl browser session, passing its bound tab.
// No HTTP client, session-token access, authentication automation or hidden API.
export function parseCsv(text) {
  const rows=[]; let row=[], value='', quoted=false;
  for(let i=0;i<text.length;i++) {
    const ch=text[i];
    if(ch==='"') { if(quoted && text[i+1]==='"'){value+='"';i++;} else quoted=!quoted; }
    else if(ch===',' && !quoted){row.push(value);value='';}
    else if(ch==='\n' && !quoted){row.push(value.replace(/\r$/,''));rows.push(row);row=[];value='';}
    else value+=ch;
  }
  if(value || row.length){row.push(value);rows.push(row);}
  const headers=(rows.shift()||[]).map(s=>s.replace(/^\uFEFF/,''));
  return rows.filter(r=>r.some(Boolean)).map(r=>Object.fromEntries(headers.map((h,i)=>[h,r[i]||''])));
}
const routeFields=['country','area','discipline','crag','crag_url','sector','name','grade','url'];
const coverageFields=['name','url','expected','captured','status'];
const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';
async function writeCsv(fs,path,rows,fields) {
  await fs.writeFile(path+'.part','\uFEFF'+fields.join(',')+'\r\n'+rows.map(r=>fields.map(k=>quote(r[k])).join(',')).join('\r\n')+'\r\n','utf8');
  await fs.rename(path+'.part',path);
}
export async function restore(fs,directory) {
  const read=async name=>{try{return parseCsv(await fs.readFile(directory+'/'+name+'.csv','utf8'));}catch(e){if(e.code==='ENOENT')return [];throw e;}};
  const state={directory,index:await read('crags-index'),routes:await read('routes'),coverage:await read('coverage')};
  if(!state.index.length)throw new Error('Capture the published area index first');
  return state;
}
export async function captureBatch(tab,fs,state,batchSize=4) {
  const results=[];
  for(const c of state.index.filter(c=>!state.coverage.some(s=>s.url===c.url&&s.status==='complete')).slice(0,batchSize)) {
    const expected=Number(c.expected);
    const url=new URL(c.url);
    if(url.origin!=='https://www.8a.nu' || !/^\/crags\/(sportclimbing|bouldering)\/turkey\/[^/]+\/routes$/.test(url.pathname))throw new Error('Unexpected published crag URL');
    if(await tab.url()!==c.url)await tab.goto(c.url);
    await tab.playwright.getByRole('table').waitFor({state:'visible',timeoutMs:15000});
    if(expected>0)await tab.playwright.getByRole('table').getByRole('row').nth(1).waitFor({state:'attached',timeoutMs:15000});
    for(let attempt=0;attempt<8;attempt++) {
      const n=(await tab.playwright.getByRole('table').getByRole('row').count())-1;
      if(n>=expected)break;
      const ax=await tab.getAXState({emit:false,disableDiffing:true});
      const match=ax.match(/^\s*(\d+) table\s*$/m);
      if(!match)throw new Error('No current scroll table: '+c.name);
      await tab.scroll(Number(match[1]),'down',12);
      await tab.playwright.getByRole('table').getByRole('row').nth(n+1).waitFor({state:'attached',timeoutMs:15000});
    }
    const parsed=await tab.playwright.getByRole('table').evaluate(t=>({html:t.outerHTML,rows:Array.from(t.querySelectorAll('tr')).filter(r=>r.querySelectorAll('td').length).map(r=>({cells:Array.from(r.querySelectorAll('td')).map(c=>c.innerText),links:Array.from(r.querySelectorAll('a')).map(a=>({text:a.innerText.trim(),href:a.href}))}))}));
    const discipline=url.pathname.split('/')[2];
    const rows=parsed.rows.map(r=>({country:'Турция',area:'Geyikbayırı',discipline,crag:c.name,crag_url:c.url,sector:r.links.find(a=>a.text)?.text||'',name:r.cells[0].split('\n')[0].trim(),grade:r.cells[1]?.trim()||'',url:r.links[0]?.href||''}));
    if(rows.some(r=>!r.name||!r.url.startsWith(c.url.slice(0,-'/routes'.length)+'/sectors/')))throw new Error('Source route/parent mismatch: '+c.name);
    const escapedName=c.name.replaceAll('&','&amp;').replaceAll('<','&lt;');
    await fs.writeFile(state.directory+'/html/'+discipline+'-'+url.pathname.split('/')[4]+'.html','<!doctype html><meta charset="utf-8"><title>'+escapedName+'</title>'+parsed.html,'utf8');
    state.routes=state.routes.filter(r=>r.crag_url!==c.url).concat(rows);
    const result={name:c.name,url:c.url,expected,captured:rows.length,status:rows.length===expected?'complete':'count_mismatch'};
    state.coverage=state.coverage.filter(r=>r.url!==c.url).concat(result);
    await writeCsv(fs,state.directory+'/routes.csv',state.routes,routeFields);
    await writeCsv(fs,state.directory+'/coverage.csv',state.coverage,coverageFields);
    results.push(result);
    // User requested pauses. No parallel browsing or retries after a denial.
    await new Promise(resolve=>setTimeout(resolve,3000+Math.floor(Math.random()*2001)));
  }
  return {complete:state.coverage.filter(r=>r.status==='complete').length,total:state.index.length,routes:state.routes.length,batch:results};
}
