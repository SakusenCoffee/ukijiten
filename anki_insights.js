let ankiInsightsData=null,ankiInsightsLoading=false,ankiInsightsError='';
let ankiGraphsOpen=false,ankiKanjiOpen=false,ankiInsightsRequest=0;
let ankiGraphDeck='combined',ankiGraphRange=90;
function ankiInsightButtons(){return `<div class="anki-card-controls"><button id="anki-graphs-toggle" class="anki-insight-toggle" title="Anki graphs" aria-label="Anki graphs" aria-expanded="${ankiGraphsOpen}"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M3 3v18h18M7 16v-5m5 5V6m5 10V9"/></svg></button><button id="anki-kanji-toggle" class="anki-insight-toggle" title="Kanji heatmaps" aria-label="Kanji heatmaps" aria-expanded="${ankiKanjiOpen}"><span aria-hidden="true">漢</span></button></div>`;}
function mountAnkiInsights(previous){
  const slot=document.getElementById('anki-insights');if(!slot)return;
  if(previous)slot.replaceWith(previous);
  document.getElementById('anki-graphs-toggle').onclick=()=>{ankiGraphsOpen=!ankiGraphsOpen;ankiKanjiOpen=false;renderAnkiInsights();ensureAnkiInsights();};
  document.getElementById('anki-kanji-toggle').onclick=()=>{ankiKanjiOpen=!ankiKanjiOpen;ankiGraphsOpen=false;renderAnkiInsights();ensureAnkiInsights();};
  renderAnkiInsights();
}
function ensureAnkiInsights(){
  if((!ankiGraphsOpen&&!ankiKanjiOpen)||ankiInsightsData||ankiInsightsLoading)return;
  ankiInsightsLoading=true;ankiInsightsError='';const request=String(++ankiInsightsRequest);
  renderAnkiInsights();app.stats_anki_insights(request);
}
function ankiInsightsLoaded(request,payload){
  if(String(ankiInsightsRequest)!==request)return;
  ankiInsightsLoading=false;ankiInsightsError=payload.error||'';ankiInsightsData=payload.data||null;
  renderAnkiInsights();
}
function resetAnkiInsights(){
  ++ankiInsightsRequest;ankiInsightsData=null;ankiInsightsError='';ankiInsightsLoading=false;
  renderAnkiInsights();ensureAnkiInsights();
}
function ankiBars(title,labels,values,unit='',color='#88a8d7',percent=false){
  const width=560,height=190,left=40,bottom=150,top=14,plot=504;
  const maximum=percent?100:Math.max(1,...values);
  const slot=plot/Math.max(1,values.length),bar=Math.max(.6,slot*.75);
  const marks=[0,.5,1].map(f=>{const y=bottom-f*(bottom-top);return `<path class="anki-plot-grid" d="M${left} ${y}h${plot}"/><text x="${left-6}" y="${y+4}" text-anchor="end">${statsNumber(Math.round(maximum*f))}${percent?'%':''}</text>`;}).join('');
  const bars=values.map((value,index)=>{
    if(value===null||value===undefined)return '';
    const y=bottom-Math.max(0,value)/maximum*(bottom-top),x=left+index*slot+(slot-bar)/2;
    return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${bar.toFixed(2)}" height="${Math.max(0,bottom-y).toFixed(2)}" rx="1" fill="${color}"><title>${statsEscape(labels[index])} · ${statsNumber(Math.round(value*10)/10)}${unit}</title></rect>`;
  }).join('');
  const indexes=values.length<=8?labels.map((_,i)=>i):[0,Math.floor((values.length-1)/2),values.length-1];
  const axis=indexes.map(index=>`<text x="${left+(index+.5)*slot}" y="${bottom+21}" text-anchor="middle">${statsEscape(labels[index])}</text>`).join('');
  const total=values.reduce((sum,value)=>sum+(value||0),0);
  return `<article class="anki-graph"><h4>${title}</h4><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${title}"><title>${title}</title>${marks}${bars}${axis}</svg>${(percent?values.every(value=>value===null):!total)?'<p class="anki-empty">No activity in this period.</p>':''}</article>`;
}
function ankiGraphMarkup(){
  const all=ankiInsightsData,groups=[all.combined,...all.decks];
  const group=ankiGraphDeck==='combined'?all.combined:all.decks.find(item=>item.deck===ankiGraphDeck)||all.combined;
  const dates=[];const end=new Date(all.date+'T12:00:00');
  for(let index=ankiGraphRange-1;index>=0;index--){const day=new Date(end);day.setDate(day.getDate()-index);dates.push(statsDate(day));}
  const days=dates.map(day=>group.days[day]||{}),labels=dates.map(day=>day.slice(5));
  const retention=days.map(day=>day.retention_total?100*day.retention_pass/day.retention_total:null);
  return `<div class="anki-insight-heading"><h4>Graphs</h4><div class="anki-graph-filters"><label>Deck <select id="anki-graph-deck">${groups.map((item,index)=>`<option value="${index===0?'combined':statsEscape(item.deck)}" ${group===item?'selected':''}>${statsEscape(item.deck)}</option>`).join('')}</select></label><label>Period <select id="anki-graph-period">${[30,90,365].map(days=>`<option value="${days}" ${ankiGraphRange===days?'selected':''}>${days} days</option>`).join('')}</select></label></div></div><div class="anki-graph-grid">
    ${ankiBars('Reviews',labels,days.map(day=>day.reviews||0),' reviews')}
    ${ankiBars('Study time',labels,days.map(day=>(day.seconds||0)/60),' min','#88d7bc')}
    ${ankiBars('Retention',labels,retention,'%','#b7a0e0',true)}
    ${ankiBars('First reviewed',labels,days.map(day=>day.first||0),' cards','#e2bb7b')}
    ${ankiBars('Answer buttons',['Again','Hard','Good','Easy'],group.answers,' reviews')}
    ${ankiBars('Card stages',['New','Learning','Young','Mature','Susp.'],group.stages,' cards','#88d7bc')}
    ${ankiBars('Review intervals',['≤1d','2–7d','8–21d','22–90d','91–365d','>365d'],group.intervals,' cards','#b7a0e0')}
    ${ankiBars('Review time of day',Array.from({length:24},(_,hour)=>String(hour).padStart(2,'0')+':00'),group.hourly,' reviews','#e2bb7b')}
    </div><p class="anki-insight-note">Daily charts use the selected period; other charts use all history or current cards. Retention: scheduled reviews only. Mature: interval of 21+ days.</p>`;
}
function renderAnkiInsights(){
  const area=document.getElementById('anki-insights');if(!area)return;
  for(const [id,open] of [['anki-graphs-toggle',ankiGraphsOpen],['anki-kanji-toggle',ankiKanjiOpen]])document.getElementById(id)?.setAttribute('aria-expanded',String(open));
  area.hidden=!ankiGraphsOpen&&!ankiKanjiOpen;if(area.hidden)return;
  const version=[ankiInsightsRequest,ankiInsightsLoading,ankiInsightsError,ankiGraphsOpen,ankiKanjiOpen,ankiGraphDeck,ankiGraphRange,kanjiGridRevision,!!ankiInsightsData].join('|');
  if(area.dataset.version===version)return;area.dataset.version=version;
  if(ankiInsightsLoading){area.innerHTML='<p class="anki-insight-note" role="status">Loading Anki…</p>';return;}
  if(ankiInsightsError){area.innerHTML=`<p class="anki-insight-note" role="alert">${statsEscape(ankiInsightsError)}</p><button id="anki-insights-retry">Retry</button>`;document.getElementById('anki-insights-retry').onclick=ensureAnkiInsights;return;}
  if(!ankiInsightsData){area.replaceChildren();return;}
  area.innerHTML=(ankiGraphsOpen?`<div id="anki-graphs">${ankiGraphMarkup()}</div>`:'')+(ankiKanjiOpen?`<div id="anki-kanji-maps">${kanjiGridMarkup()}</div>`:'');
  if(ankiKanjiOpen)bindKanjiGridOptions();
  const deck=document.getElementById('anki-graph-deck');if(deck)deck.onchange=()=>{ankiGraphDeck=deck.value;renderAnkiInsights();};
  const period=document.getElementById('anki-graph-period');if(period)period.onchange=()=>{ankiGraphRange=Number(period.value);renderAnkiInsights();};
}
