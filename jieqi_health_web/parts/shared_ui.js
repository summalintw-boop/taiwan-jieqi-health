// ===== 共用：就醫警訊（只收錄有官方出處的內容）=====
const DANGER={
  cvd:{sign:'「微笑」臉部兩邊不對稱、「舉手」有一隻手垂下、「說你好」講不清楚',act:'儘快撥 119，並記下發生時間',src:'國民健康署（2023/6/15）',url:'https://mohw.gov.tw/cp-16-74897-1.html'},
  resp:{sign:'呼吸困難、呼吸急促、發紺、血痰、胸痛、意識改變或低血壓（流感危險徵兆）',act:'儘速就醫',src:'疾病管制署（2026/11/3）',url:'https://www.mohw.gov.tw/cp-16-88360-1.html'},
  heat:{sign:'體溫持續上升、呼吸困難或意識持續不清',act:'立即就醫或撥 119；先移到陰涼處',src:'國民健康署（2025/6/20）',url:'https://mohw.gov.tw/cp-16-82821-1.html'},
  dengue:{sign:'腹部疼痛及壓痛、持續性嘔吐、黏膜出血、嗜睡或躁動不安（登革熱重症警示徵象）',act:'儘速就醫並告知旅遊史',src:'疾病管制署（2026/6/14）',url:'https://mohw.gov.tw/cp-16-86925-1.html'},
};
function dangerHTML(keys){
  const ds=[...new Set(keys)].filter(k=>DANGER[k]);
  return `<h3>⚠️ 出現這些情況，請就醫或撥 119</h3><ul>${ds.map(k=>`<li>${ICON[k]||''} ${DANGER[k].sign} → <b>${DANGER[k].act}</b><span class="dsrc">出處：<a href="${DANGER[k].url}" target="_blank" rel="noopener">${DANGER[k].src}</a></span></li>`).join('')}<li>任何緊急狀況 → <span class="call">119</span></li></ul>`;
}
const LVT=['','○ 需留意','● 風險中','▲ 風險高'];
const store={get(k,d){try{const v=localStorage.getItem(k);return v==null?d:JSON.parse(v);}catch(e){return d;}},set(k,v){try{localStorage.setItem(k,JSON.stringify(v));}catch(e){}}};
const md=s=>`${+s.slice(5,7)}/${+s.slice(8)}`;
const wdOf=s=>'日一二三四五六'[new Date(s+'T00:00:00Z').getUTCDay()];
function reasonOf(d){
  const t=tempOf(d.date,REGION), r=[], f=parseWx(d);
  if(t){
    if(t.dmn<=-3)r.push(`最低溫比前一天低 ${(-t.dmn).toFixed(0)}°C，注意保暖`);
    else if(t.mn<=12)r.push(`最低 ${t.mn.toFixed(0)}°C 偏冷，注意保暖`);
    if(t.mx>=32)r.push(`最高 ${t.mx.toFixed(0)}°C，注意補水防中暑`);
    if(t.rng>=8)r.push(`日夜溫差 ${t.rng.toFixed(0)}°C，早晚加衣`);
  }
  if(d.rain)r.push(f.ne?'東北季風帶來降雨，濕冷路滑':'有雨，路面濕滑');
  if(histLv('ili',d.date)>=2)r.push('流感就診高峰期（疾管署歷年資料）');
  if(!r.length)r.push('天氣變化不大');
  return r.slice(0,2).join('；');
}
