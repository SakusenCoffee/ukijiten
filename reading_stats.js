let readingStats = null;
let statsYear = new Date().getFullYear();
let ankiStatsYear = new Date().getFullYear();
let statsNotice = '';
let statsNoticeTimer = null;
let statsEntryDraft = null;
window.statsImportNotice = message => {
  statsNotice=message;clearTimeout(statsNoticeTimer);
  statsNoticeTimer=setTimeout(()=>{statsNotice='';if(readingStats)updateReadingStats(readingStats);},5000);
};
const statsDays = n => statsNumber(n)+' '+(n===1?'day':'days');
function statsNumber(n) { return Number(n || 0).toLocaleString(); }
function statsDuration(seconds) {
  const total=Math.max(0,Math.floor(Number(seconds)||0));
  const minutes=Math.floor(total/60);
  return minutes>=60?Math.floor(minutes/60)+'h '+minutes%60+'m':minutes?minutes+'m':total+'s';
}
function statsEscape(s) { const node=document.createElement('span');node.textContent=String(s);return node.innerHTML.replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
function statsDate(date) { const d=new Date(date);d.setMinutes(d.getMinutes()-d.getTimezoneOffset());return d.toISOString().slice(0,10); }
function updateReadingStats(data) {
  readingStats=data;
  const area=document.getElementById('reading-stats');
  if(!area)return;
  if(typeof readingHistoryState!=='undefined'&&readingHistoryState&&area.querySelector('#reading-history'))return;
  if(typeof statsSettingsDraft !== 'undefined' && statsSettingsDraft){refreshUploadedFiles();updateCloudConnections();return;}
  if(statsEntryDraft && area.querySelector('#stats-entry-form'))return;
  const scroll=document.getElementById('inline-settings').scrollTop;
  const previousAnkiInsights=area.querySelector('#anki-insights');
  const dates=Object.keys(data.days).sort();
  const notice=data.refresh_notice||statsNotice;
  const cards=[['Characters read',statsNumber(data.total),'All time'],['Today',statsNumber(data.today),'Japanese characters'],['Streak',statsDays(data.streak),'Best: '+statsDays(data.longest)],['Total time',Math.floor(data.seconds/3600)+'h '+Math.floor(data.seconds%3600/60)+'m','Reading + Anki reviews']];
  area.innerHTML=`<div class="stats-top"><button id="stats-back" class="dictionary-back-icon" title="Back to dictionary" aria-label="Back to dictionary"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 8V3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8M4 17h7M8 7h3M8 10h3"/><circle cx="17" cy="14" r="4"/><path d="m20 17 2 2"/></svg></button><div class="stats-actions"><button id="stats-refresh" class="stats-refresh ${data.refreshing?'is-refreshing':''}" title="Refresh enabled sources" aria-label="Refresh enabled sources" aria-busy="${!!data.refreshing}" ${data.refreshing?'disabled':''}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 7a7 7 0 0 1 11.6-1L20 9M4 15l2.3 3A7 7 0 0 0 18 17"/></svg></button><button id="stats-settings" title="Stats settings" aria-label="Stats settings"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/></svg></button><button id="stats-add" class="stats-add" title="Add reading entry" aria-label="Add reading entry"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg></button></div></div>
    <div class="stats-heading" style="justify-content:flex-end"><span class="stats-status ${data.status?.startsWith('Live')?'is-live':''}"><i></i>${statsEscape(data.status||'Waiting for texthooker')}</span></div>
    ${notice?'<p class="stats-import-notice" role="status">'+statsEscape(notice)+'</p>':''}<div class="stats-cards">${cards.map(([label,value,note])=>`<article class="stats-card ${label==='Total time'?'stats-card-total':label==='Streak'?'stats-card-streak':''}"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`).join('')}</div>
    <section class="stats-surface stats-sources"><div class="stats-section-head"><h3>By source</h3><span>${data.sources.length} ${data.sources.length===1?'source':'sources'}</span></div><div class="stats-source-list">${data.sources.length?data.sources.slice(0,8).map((s,i)=>`<div class="stats-source"><div><b>${statsEscape(s.source)}</b><span>${statsNumber(s.characters)}</span></div><div class="stats-source-track"><i style="width:${100*s.characters/Math.max(1,data.sources[0].characters)}%;--source-hue:${160+i*23}"></i></div></div>`).join(''):'<div class="stats-empty">Your reading sources will appear here.</div>'}</div></section>
    ${data.anki_decks?.length?`<section class="stats-surface" id="anki-time-summary"><div class="stats-section-head"><h3>Anki review time</h3><span>${statsEscape(data.anki_status||'')}</span></div><div class="stats-anki-decks">${data.anki_decks.map(deck=>`<div class="stats-anki-deck"><span>${statsEscape(deck.deck)}</span><strong>${Math.floor(deck.seconds/3600)}h ${Math.floor(deck.seconds%3600/60)}m</strong><small>${statsNumber(deck.reviews)} reviews</small></div>`).join('')}</div></section>`:''}
    ${(data.source_settings?.anki?.enabled&&data.source_settings.anki.decks?.length||data.anki_decks?.length)?statsHeatmapCard('anki-consistency','Anki','Selected decks',data.anki_days||{}):''}
    ${statsHeatmapCard('reading-consistency','Reading',''+statsDays(Object.keys(data.consistency_days||{}).length)+' active',data.consistency_days||{})}
    <section class="stats-surface"><div class="stats-section-head"><h3>Recent reading</h3><div class="history-recent-actions"><span>${dates[0]?'Since '+dates[0]:''}</span><button id="stats-history">History…</button></div></div><div class="stats-recent">${data.recent.length?data.recent.map(r=>`<div class="stats-recent-row"><time>${r.day}</time><b>${statsEscape(r.source)}</b><span class="stats-kind">${r.source.startsWith('Mokuro Browser · ')?'Mokuro':r.kind==='live'?(r.source.startsWith('Game OCR · ')?'Local':'GSM'):r.kind==='manual'?'Manual':'Import'}</span><strong class="stats-recent-characters">${statsNumber(r.characters)} <small>chars</small></strong><strong class="stats-recent-time" aria-label="Reading time" title="Reading time">${statsDuration(r.seconds)}</strong></div>`).join(''):'<div class="stats-empty">Start reading with GSM, or import your reading history.</div>'}</div></section>
    <div class="stats-footer">Kanji & kana only · punctuation, symbols and numeric digits excluded</div>`;
  // Keep all time summaries and heatmaps ahead of the source breakdown.
  area.querySelector('#reading-consistency').after(area.querySelector('.stats-sources'));
  let studyAnchor=area.querySelector('#reading-consistency');
  for(const [service,activity] of Object.entries(data.study_sources||{})){
    const id='study-'+service,title=service==='jpdb'?'jpdb.io':'Renshuu',subtitle=service==='jpdb'?statsNumber(activity.reviews)+' reviews':'Study-goal completion';
    studyAnchor.insertAdjacentHTML('afterend',statsHeatmapCard(id,title,subtitle,activity.days));studyAnchor=area.querySelector('#'+id);
    const select=studyAnchor.querySelector('select');select.onchange=()=>renderStudyHeatmap(Number(select.value),id,activity.days,service);renderStudyHeatmap(Number(select.value),id,activity.days,service);
  }
  area.querySelector('#stats-settings').onclick=showStatsSourceSettings;
  area.querySelector('#stats-add').onclick=showStatsEntryForm;
  area.querySelector('#stats-back').onclick=()=>{statsEntryDraft=null;closeSettings();};
  area.querySelector('#stats-refresh').onclick=()=>app.stats_refresh();
  area.querySelector('#stats-history').onclick=()=>openReadingHistory();
  area.querySelectorAll('.stats-recent-row').forEach((row,index)=>{const entry=data.recent[index];row.setAttribute('role','button');row.tabIndex=0;row.onclick=()=>openReadingHistory({day:entry.day,source:entry.source});row.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();row.click();}};});
  for (const [id,days,anki] of [['reading-consistency',data.consistency_days||{},false],['anki-consistency',data.anki_days||{},true]]) {
    const select=area.querySelector('#'+id+' select');if(!select)continue;
    select.value=String(anki?ankiStatsYear:statsYear);if(!select.value)select.selectedIndex=0;
    select.onchange=()=>{if(anki)ankiStatsYear=Number(select.value);else statsYear=Number(select.value);renderStatsHeatmap(Number(select.value),id,days,anki);};
    renderStatsHeatmap(Number(select.value),id,days,anki);
  }
  mountAnkiInsights(previousAnkiInsights);
  setupStatsBackToTop();
  document.getElementById('inline-settings').scrollTop=scroll;
}
function statsHeatmapCard(id,title,subtitle,days) {
  const years=[...new Set([String(new Date().getFullYear()),...Object.keys(days).map(day=>day.slice(0,4))])].sort().reverse();
  return `<section class="stats-surface" id="${id}"><div class="stats-section-head"><div><h3>${title}</h3><p>${subtitle}</p></div><div class="anki-heatmap-actions">${id==='anki-consistency'?ankiInsightButtons():''}<label class="stats-year-label">Year <select aria-label="${title} heatmap year">${years.map(year=>`<option>${year}</option>`).join('')}</select></label></div></div><div class="stats-heatmap-scroll"><div class="stats-heatmap" aria-label="${title} yearly heatmap"></div></div><div class="stats-legend"><span>Less</span>${[0,1,2,3,4].map(level=>`<i class="heat-${level}"></i>`).join('')}<span>More</span></div>${id==='anki-consistency'?'<div id="anki-insights" hidden></div>':''}</section>`;
}
function renderStudyHeatmap(year,id,days,service){
  const grid=document.querySelector('#'+id+' .stats-heatmap');grid.replaceChildren();
  const first=new Date(year,0,1),end=new Date(year+1,0,1),max=Math.max(1,...Object.values(days).map(day=>day.reviews||0));
  for(let index=0;index<(first.getDay()+6)%7;index++){const cell=document.createElement('i');cell.style.visibility='hidden';grid.append(cell);}
  for(let day=new Date(first);day<end;day.setDate(day.getDate()+1)){
    const key=statsDate(day),value=days[key]||{},amount=service==='renshuu'?(value.completion||0):(value.reviews||0);
    const cell=document.createElement('i');cell.dataset.day=key;cell.className='heat-'+(amount?Math.max(1,Math.min(4,Math.ceil(service==='renshuu'?amount/25:4*Math.sqrt(amount/max)))):0);
    cell.title=key+' · '+(service==='renshuu'?amount+'% study goal':statsNumber(amount)+' reviews');grid.append(cell);
  }
}
function renderStatsHeatmap(year,id,days,anki=false) {
  const heatmap=document.querySelector('#'+id+' .stats-heatmap');if(!heatmap)return;heatmap.replaceChildren();
  const first=new Date(year,0,1),end=new Date(year+1,0,1);
  const measure=anki?'reviews':'characters';
  const max=Math.max(1,...Object.entries(days).filter(([day])=>day.startsWith(String(year))).map(([,value])=>value[measure]||0));
  for(let i=0;i<(first.getDay()+6)%7;i++){const cell=document.createElement('i');cell.style.visibility='hidden';heatmap.append(cell);}
  for(let d=new Date(first);d<end;d.setDate(d.getDate()+1)){
    const day=statsDate(d),count=days[day]?.[measure]||0;
    const activity=count||(!anki && days[day]?.seconds?1:0);
    const cell=document.createElement('i');cell.dataset.day=day;cell.className='heat-'+(activity?Math.max(1,Math.ceil(4*Math.sqrt(activity/max))):0);
    cell.title=anki?`${day} · ${statsNumber(count)} reviews · ${Math.round((days[day]?.seconds||0)/60)} min`:`${day} · ${statsNumber(count)} characters · ${Math.round((days[day]?.seconds||0)/60)} min`;
    heatmap.append(cell);
  }
}

function showReadingStats(data) {
  statsSettingsDraft=null;
  statsEntryDraft=null;
  closeSettings();showSettings(motion);
  const area=document.getElementById('inline-settings');area.replaceChildren();
  const stats=document.createElement('div');stats.id='reading-stats';stats.className='reading-stats';area.append(stats);
  updateReadingStats(data);
}

function showStatsEntryForm() {
  if(statsEntryDraft)return;
  statsEntryDraft={identifier:crypto.randomUUID(),characters:0,hours:0,minutes:0,description:'',day:readingStats.today_day||statsDate(new Date())};
  const form=document.createElement('form');form.id='stats-entry-form';form.className='stats-surface stats-entry-form';
  form.innerHTML=`<h3>Add reading entry</h3><div class="stats-entry-fields"><label>Date<input name="day" type="date" required></label><label>Characters<input name="characters" type="number" min="0" max="1000000000" step="1" value="0" required></label><label>Hours<input name="hours" type="number" min="0" max="1000000" step="1" value="0" required></label><label>Minutes<input name="minutes" type="number" min="0" max="59" step="1" value="0" required></label></div><label class="stats-entry-description">Description<textarea name="description" rows="2" maxlength="500"></textarea></label><p class="stats-entry-error" role="alert" hidden></p><div class="stats-actions"><button type="button" id="stats-entry-cancel">Cancel</button><button type="submit">Add entry</button></div>`;
  const area=document.getElementById('reading-stats');area.querySelector('.stats-heading').after(form);
  form.elements.day.value=statsEntryDraft.day;
  form.querySelector('#stats-entry-cancel').onclick=()=>closeStatsEntryForm(form);
  form.onsubmit=event=>{
    event.preventDefault();if(!form.reportValidity())return;
    for(const name of ['characters','hours','minutes'])statsEntryDraft[name]=Number(form.elements[name].value);
    statsEntryDraft.day=form.elements.day.value;statsEntryDraft.description=form.elements.description.value;
    const submit=form.querySelector('[type=submit]');submit.disabled=true;
    app.stats_add_entry(JSON.stringify(statsEntryDraft),response=>{
      const result=JSON.parse(response);
      if(result.error){const error=form.querySelector('.stats-entry-error');error.textContent=result.error;error.hidden=false;submit.disabled=false;return;}
      statsEntryDraft=null;window.statsImportNotice('Entry added');updateReadingStats(readingStats);app.reading_stats();
    });
  };
  animateStatsEntryForm(form);
  form.elements.characters.focus({preventScroll:true});form.scrollIntoView({block:'nearest'});
}

function animateStatsEntryForm(form,closing=false) {
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return null;
  const style=getComputedStyle(form);
  const collapsed={height:'0px',opacity:0,paddingTop:'0px',paddingBottom:'0px',marginBottom:'0px',overflow:'hidden'};
  const expanded={height:form.offsetHeight+'px',opacity:1,paddingTop:style.paddingTop,paddingBottom:style.paddingBottom,marginBottom:style.marginBottom,overflow:'hidden'};
  return form.animate(closing?[expanded,collapsed]:[collapsed,expanded],{duration:90,easing:'ease-out'});
}
function closeStatsEntryForm(form) {
  const draft=statsEntryDraft;
  const finish=()=>{if(statsEntryDraft!==draft)return;statsEntryDraft=null;if(form.isConnected)updateReadingStats(readingStats);};
  form.querySelectorAll('button').forEach(button=>button.disabled=true);
  const animation=animateStatsEntryForm(form,true);
  if(animation)animation.finished.then(finish).catch(finish);else finish();
}

function setupStatsBackToTop(){
  const scroll=document.getElementById('inline-settings'),area=document.getElementById('reading-stats');if(!scroll||!area)return;
  let button=document.getElementById('stats-back-to-top');
  if(!button){
    button=document.createElement('button');button.id='stats-back-to-top';button.type='button';button.title='Back to top';button.setAttribute('aria-label','Back to top');
    button.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m6 11 6-6 6 6M12 5v15"/></svg>';
    area.append(button);
  }
  button.onclick=()=>scroll.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth'});
  const update=()=>{const current=document.getElementById('stats-back-to-top');if(current)current.hidden=scroll.scrollTop<350;};
  scroll.onscroll=update;update();
}
