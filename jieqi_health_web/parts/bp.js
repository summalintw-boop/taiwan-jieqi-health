// ===== 血壓追蹤（722 原則）：資料只存本機瀏覽器 =====
(function(){
const KEY='jq-bp722';
const $b=id=>document.getElementById(id);
if(!$b('bpw'))return;
const pad=n=>String(n).padStart(2,'0');
const ymdLocal=dt=>`${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())}`;
const load=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]');}catch(e){return[];}};
const save=L=>{try{localStorage.setItem(KEY,JSON.stringify(L.slice(-200)));}catch(e){$b('bp-msg').textContent='這個瀏覽器無法儲存紀錄（可能是無痕模式）。';}};
const SL={am:'早上',pm:'晚上'};
const status=(s,d)=>s<120&&d<80?['低於 120/80，在國健署建議的正常範圍','var(--lv1)']:['高於正常值 120/80，請持續記錄並帶給醫師看','var(--lv2)'];
function last7(){const out=[],t=new Date();for(let i=6;i>=0;i--){const x=new Date(t);x.setDate(t.getDate()-i);out.push(ymdLocal(x));}return out;}
function windowRecs(L){const days=last7();return{days,recs:L.filter(r=>days.includes(r.date))};}
const fmtR=r=>r?`${r.s}/${r.d}${r.p?`<small> ${r.p}</small>`:''}`:'—';
function avg(rs){if(!rs.length)return null;const a=k=>Math.round(rs.reduce((x,r)=>x+r[k],0)/rs.length);const ps=rs.filter(r=>r.p);return{s:a('s'),d:a('d'),p:ps.length?Math.round(ps.reduce((x,r)=>x+r.p,0)/ps.length):0,n:rs.length};}

function render(){
  const L=load(), {days,recs}=windowRecs(L), A=avg(recs);
  const get=(d,sl)=>recs.find(r=>r.date===d&&r.slot===sl);
  // 進度
  $b('bp-prog').innerHTML=`722 進度：最近 7 天已量 <b>${recs.length}</b> / 14 次<div class="bar"><i style="width:${recs.length/14*100}%"></i></div>`;
  // 表格
  $b('bp-tbl').innerHTML='<thead><tr><th>日期</th><th>早上</th><th>晚上</th></tr></thead><tbody>'+
    days.map(d=>`<tr><td>${+d.slice(5,7)}/${+d.slice(8)}（${'日一二三四五六'[new Date(d+'T00:00:00').getDay()]}）</td><td>${fmtR(get(d,'am'))}</td><td>${fmtR(get(d,'pm'))}</td></tr>`).join('')+
    (A?`<tr class="avg"><td>7 天平均</td><td colspan="2">${A.s}/${A.d}${A.p?`・脈搏 ${A.p}`:''}（${A.n} 次）<br><span style="color:${status(A.s,A.d)[1]}">${status(A.s,A.d)[0]}</span></td></tr>`:'')+'</tbody>';
  drawChart(days,recs);
  $b('bp-doc').disabled=$b('bp-copy').disabled=!recs.length;
  if(!$b('bp-docview').hidden)renderDoc();
}
function drawChart(days,recs){
  const el=$b('bp-chart');
  if(!recs.length){el.innerHTML='<div class="sub">記錄後這裡會出現最近 7 天的趨勢圖。</div>';return;}
  const W=340,H=170,pl=30,pr=8,pt=10,pb=22, lo=50, hi=180;
  const x=(i,sl)=>pl+(i+(sl==='am'?.3:.7))*(W-pl-pr)/7, y=v=>pt+(H-pt-pb)*(1-(Math.max(lo,Math.min(hi,v))-lo)/(hi-lo));
  const pts=recs.map(r=>({r,i:days.indexOf(r.date)})).sort((a,b)=>a.i-b.i||(a.r.slot==='am'?-1:1));
  const path=k=>pts.map((p,j)=>`${j?'L':'M'}${x(p.i,p.r.slot).toFixed(1)},${y(p.r[k]).toFixed(1)}`).join('');
  let g='';
  [60,80,100,120,140,160].forEach(v=>{g+=`<line x1="${pl}" x2="${W-pr}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)" stroke-width="${v===120||v===80?1.5:.6}" ${v===120||v===80?'stroke-dasharray="4 3"':''}/><text x="${pl-4}" y="${y(v)+3}" text-anchor="end" font-size="9" fill="var(--muted)">${v}</text>`;});
  days.forEach((d,i)=>{g+=`<text x="${pl+(i+.5)*(W-pl-pr)/7}" y="${H-6}" text-anchor="middle" font-size="9" fill="var(--muted)">${+d.slice(5,7)}/${+d.slice(8)}</text>`;});
  g+=`<path d="${path('s')}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>`;
  g+=`<path d="${path('d')}" fill="none" stroke="var(--ink)" stroke-width="2" stroke-dasharray="5 3" stroke-linejoin="round"/>`;
  pts.forEach(p=>{const cx=x(p.i,p.r.slot);
    g+=`<circle cx="${cx}" cy="${y(p.r.s)}" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/><rect x="${cx-4}" y="${y(p.r.d)-4}" width="8" height="8" fill="var(--ink)" stroke="var(--surface)" stroke-width="2"/>`;});
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="最近 7 天血壓趨勢圖">${g}</svg><div class="tip" hidden></div>
    <div class="bplg"><span><i style="background:var(--accent)"></i>● 收縮壓</span><span><i style="background:var(--ink)"></i>■ 舒張壓（虛線）</span><span><i style="background:var(--line)"></i>灰色虛線：正常上限 120／80</span><span>每天左點為早上、右點為晚上</span></div>`;
  const svg=el.querySelector('svg'), tip=el.querySelector('.tip');
  const move=e=>{const b=svg.getBoundingClientRect(), px=(e.clientX-b.left)/b.width*W;let best=null,bd=1e9;pts.forEach(p=>{const dx=Math.abs(x(p.i,p.r.slot)-px);if(dx<bd){bd=dx;best=p;}});
    if(!best||bd>25){tip.hidden=true;return;}tip.hidden=false;tip.style.left=(x(best.i,best.r.slot)/W*100)+'%';tip.style.top=(y(best.r.s)/H*b.height)+'px';
    tip.textContent=`${+best.r.date.slice(5,7)}/${+best.r.date.slice(8)} ${SL[best.r.slot]}：${best.r.s}/${best.r.d}${best.r.p?` 脈搏 ${best.r.p}`:''}`;};
  svg.addEventListener('pointermove',move);svg.addEventListener('pointerdown',move);svg.addEventListener('pointerleave',()=>tip.hidden=true);
}
function docText(){
  const {days,recs}=windowRecs(load()), A=avg(recs), get=(d,sl)=>recs.find(r=>r.date===d&&r.slot===sl), f=r=>r?`${r.s}/${r.d}${r.p?` 脈搏${r.p}`:''}`:'—';
  return `居家血壓紀錄（722 原則）${+days[0].slice(5,7)}/${+days[0].slice(8)}–${+days[6].slice(5,7)}/${+days[6].slice(8)}\n`+days.map(d=>`${+d.slice(5,7)}/${+d.slice(8)} 早 ${f(get(d,'am'))}　晚 ${f(get(d,'pm'))}`).join('\n')+(A?`\n7 天平均 ${A.s}/${A.d}${A.p?` 脈搏${A.p}`:''}（共 ${A.n} 次）`:'');
}
function renderDoc(){
  const {days,recs}=windowRecs(load()), A=avg(recs), get=(d,sl)=>recs.find(r=>r.date===d&&r.slot===sl), f=r=>r?`${r.s}/${r.d}${r.p?` <small>脈搏 ${r.p}</small>`:''}`:'—';
  $b('bp-docview').innerHTML=`<h4>居家血壓紀錄（722 原則）</h4><div class="sub">每次量兩遍取平均・單位 mmHg</div><table><tr><th>日期</th><th>早上</th><th>晚上</th></tr>${days.map(d=>`<tr><td>${+d.slice(5,7)}/${+d.slice(8)}</td><td>${f(get(d,'am'))}</td><td>${f(get(d,'pm'))}</td></tr>`).join('')}</table>${A?`<div style="margin-top:6px"><b>7 天平均 ${A.s}/${A.d}</b>${A.p?`・脈搏 ${A.p}`:''}（共 ${A.n} 次）</div>`:''}`;
}
const now=new Date(); ($b(now.getHours()<12?'bp-am':'bp-pm')).checked=true;
$b('bp-form').addEventListener('submit',e=>{e.preventDefault();
  const n=id=>{const v=$b(id).value.trim();return v===''?null:+v;};
  const s1=n('bp-s1'),d1=n('bp-d1'),p1=n('bp-p1'),s2=n('bp-s2'),d2=n('bp-d2'),p2=n('bp-p2');
  const ok=(s,d)=>s>=50&&s<=260&&d>=30&&d<=180&&s>d;
  if(!ok(s1,d1)){$b('bp-msg').textContent='第一遍請輸入正確的收縮壓與舒張壓，例如 120 和 80。';return;}
  if((s2!=null||d2!=null)&&!ok(s2,d2)){$b('bp-msg').textContent='第二遍的數字不完整或不正確；只量一遍可以留白。';return;}
  const rs=[[s1,d1,p1]];if(s2!=null)rs.push([s2,d2,p2]);
  const mean=i=>Math.round(rs.reduce((x,r)=>x+r[i],0)/rs.length), ps=rs.map(r=>r[2]).filter(Boolean);
  const slot=document.querySelector('input[name="bp-slot"]:checked').value, date=ymdLocal(new Date());
  const rec={date,slot,s:mean(0),d:mean(1),p:ps.length?Math.round(ps.reduce((a,b)=>a+b,0)/ps.length):0,n:rs.length};
  const L=load(), had=L.findIndex(r=>r.date===date&&r.slot===slot); if(had>=0)L.splice(had,1); L.push(rec); save(L);
  const st=status(rec.s,rec.d);
  $b('bp-msg').innerHTML=`${had>=0?'已更新':'已記錄'}今天${SL[slot]}：<b>${rec.s}/${rec.d}</b>${rs.length>1?'（兩遍平均）':''}・<span style="color:${st[1]}">${st[0]}</span>`;
  ['bp-s1','bp-d1','bp-p1','bp-s2','bp-d2','bp-p2'].forEach(id=>$b(id).value='');
  render();});
$b('bp-doc').onclick=()=>{const v=$b('bp-docview');v.hidden=!v.hidden;$b('bp-doc').textContent=v.hidden?'給醫師看':'收起';if(!v.hidden){renderDoc();v.scrollIntoView({behavior:'smooth',block:'nearest'});}};
$b('bp-copy').onclick=()=>{const t=docText();
  const fb=()=>{const v=$b('bp-docview');v.hidden=false;renderDoc();const r=document.createRange();r.selectNodeContents(v);const s=getSelection();s.removeAllRanges();s.addRange(r);$b('bp-msg').textContent='無法自動複製，已選取紀錄，請按住或按 Ctrl+C 複製。';};
  try{navigator.clipboard.writeText(t).then(()=>{$b('bp-msg').textContent='已複製最近 7 天的紀錄，可貼到 LINE 或簡訊給醫師或家人。';},fb);}catch(e){fb();}};
$b('bp-clear').onclick=()=>{const b=$b('bp-clear');if(b.dataset.c){save([]);b.dataset.c='';b.textContent='清除全部紀錄';$b('bp-msg').textContent='已清除全部紀錄。';render();}else{b.dataset.c='1';b.textContent='再按一次確定清除';setTimeout(()=>{if(b.dataset.c){b.dataset.c='';b.textContent='清除全部紀錄';}},5000);}};
render();
})();
