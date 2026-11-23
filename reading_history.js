let readingHistoryState=null;
function historyKind(row){return row.source.startsWith('Mokuro Browser · ')?'Mokuro Browser':row.kind==='manual'?'Manual':row.kind==='import'?'Import':row.source.startsWith('Game OCR · ')?'Local':'GSM';}
function historyDuration(seconds){seconds=Math.floor(Number(seconds||0));const minutes=Math.floor(seconds/60);return minutes>=60?Math.floor(minutes/60)+'h '+minutes%60+'m':minutes?minutes+'m'+(seconds%60?' '+seconds%60+'s':''):seconds+'s';}
function openReadingHistory(initial={}){
  statsEntryDraft=null;
  readingHistoryState={filter:{...initial},grouped:true,offset:0,selected:new Map(),all:false,request:0};
  const area=document.getElementById('reading-stats');
  area.innerHTML=`<div class="stats-top"><div class="stats-history-nav"><button id="history-back">← Statistics</button><button id="history-dictionary" class="dictionary-back-icon" title="Back to dictionary" aria-label="Back to dictionary">${dictionaryBackButton().innerHTML}</button></div><h2>Reading history</h2></div>
    <section class="stats-surface" id="reading-history"><div class="history-filters"><label>Source<select id="history-source"><option value="">All sources</option></select></label><label>From<input id="history-from" type="date"></label><label>To<input id="history-to" type="date"></label><label class="history-search">Search<input id="history-search" type="search" placeholder="Source or saved text"></label></div>
    <div class="history-actions"><label><input type="checkbox" id="history-group" checked>Group by day</label><button id="history-all-page">Select page</button><button id="history-all-matching">Select all results</button><button id="history-clear-selection">Clear selection</button><button id="history-delete" disabled>Delete selected</button></div>
    <p id="history-summary" class="stats-setting-note" role="status"></p><p id="history-error" role="alert"></p><div id="history-results"></div><div class="history-pagination"><button id="history-previous">Previous</button><span id="history-page"></span><button id="history-next">Next</button></div></section>`;
  const state=readingHistoryState;
  if(state.filter.day){state.filter.from=state.filter.day;state.filter.to=state.filter.day;delete state.filter.day;}
  for(const key of ['from','to','search']){
    const input=document.getElementById('history-'+key);input.value=state.filter[key]||'';
    input.oninput=()=>{state.filter[key]=input.value;state.offset=0;clearHistorySelection();clearTimeout(state.debounce);state.debounce=setTimeout(loadReadingHistory,key==='search'?200:0);};
  }
  document.getElementById('history-source').onchange=event=>{state.filter.source=event.target.value;state.offset=0;clearHistorySelection();loadReadingHistory();};
  document.getElementById('history-group').onchange=event=>{state.grouped=event.target.checked;state.offset=0;clearHistorySelection();loadReadingHistory();};
  document.getElementById('history-back').onclick=()=>{readingHistoryState=null;updateReadingStats(readingStats);document.getElementById('inline-settings').scrollTop=0;};
  document.getElementById('history-dictionary').onclick=()=>{readingHistoryState=null;closeSettings();};
  document.getElementById('history-previous').onclick=()=>{state.offset=Math.max(0,state.offset-50);loadReadingHistory();};
  document.getElementById('history-next').onclick=()=>{state.offset+=50;loadReadingHistory();};
  document.getElementById('history-clear-selection').onclick=clearHistorySelection;
  document.getElementById('history-all-page').onclick=()=>{state.all=false;for(const row of state.data.entries){const item=historySelection(row,state.grouped);state.selected.set(item.id,item);}updateHistorySelection();};
  document.getElementById('history-all-matching').onclick=()=>{state.selected.clear();state.all=true;updateHistorySelection();};
  document.getElementById('history-delete').onclick=deleteReadingHistory;
  document.getElementById('inline-settings').scrollTop=0;loadReadingHistory();setupStatsBackToTop();
}
function historySelection(row,grouped){
  const query=grouped?{...readingHistoryState.filter,day:row.day,source:row.source,kind:row.kind}:null;
  return {id:grouped?'group:'+JSON.stringify(query):'key:'+row.key,query,key:row.key,grouped,records:row.records||1,day:row.day,source:row.source,kind:row.kind};
}
function clearHistorySelection(){if(!readingHistoryState)return;readingHistoryState.selected.clear();readingHistoryState.all=false;updateHistorySelection();}
function updateHistorySelection(){
  const state=readingHistoryState;if(!state)return;
  const count=state.all?(state.data?.records||0):[...state.selected.values()].reduce((sum,row)=>sum+row.records,0);
  const button=document.getElementById('history-delete');if(!button)return;button.disabled=!count;button.textContent=count?'Delete '+statsNumber(count)+' records':'Delete selected';
  for(const input of document.querySelectorAll('[data-history-selection]')){
    const item=input.historyItem,parentGroup=item.grouped?null:[...state.selected.values()].find(group=>group.grouped&&group.day===item.day&&group.source===item.source&&group.kind===item.kind);
    input.checked=state.all||!!parentGroup||state.selected.has(item.id);input.disabled=state.all||!!parentGroup;
  }
}
function loadReadingHistory(){
  const state=readingHistoryState;if(!state)return;const request=++state.request;
  app.stats_history_query(JSON.stringify({...state.filter,grouped:state.grouped,offset:state.offset,limit:50}),response=>{
    if(readingHistoryState!==state||request!==state.request)return;
    const data=JSON.parse(response),error=document.getElementById('history-error');error.textContent=data.error||'';if(data.error)return;
    state.data=data;
    if(data.offset>=data.total&&data.total){state.offset=Math.floor((data.total-1)/50)*50;loadReadingHistory();return;}
    const source=document.getElementById('history-source');source.replaceChildren(new Option('All sources',''));
    for(const row of data.sources)source.add(new Option(row.title,row.value));
    if(state.filter.source&&!data.sources.some(row=>row.value===state.filter.source))source.add(new Option(state.filter.source,state.filter.source));source.value=state.filter.source||'';
    document.getElementById('history-summary').textContent=statsNumber(data.records)+' records · '+statsNumber(data.characters)+' characters · '+historyDuration(data.seconds);
    const results=document.getElementById('history-results');results.replaceChildren();
    for(const row of data.entries)results.append(historyRow(row,data.grouped));
    if(!data.entries.length){const empty=document.createElement('p');empty.className='stats-empty';empty.textContent='No reading records.';results.append(empty);}
    document.getElementById('history-previous').disabled=!data.offset;document.getElementById('history-next').disabled=data.offset+data.limit>=data.total;
    document.getElementById('history-page').textContent=data.total?(data.offset+1)+'–'+Math.min(data.offset+data.limit,data.total)+' / '+statsNumber(data.total):'0';
    document.getElementById('history-all-matching').disabled=!data.records;document.getElementById('history-all-page').disabled=!data.entries.length;
    updateHistorySelection();
  });
}
function historyRow(row,grouped){
  const state=readingHistoryState,details=document.createElement('details');details.className='history-entry'+(grouped?' history-group':'');
  const summary=document.createElement('summary'),selection=historySelection(row,grouped),input=document.createElement('input');input.type='checkbox';input.dataset.historySelection=selection.id;input.historyItem=selection;input.setAttribute('aria-label','Select '+row.day+' '+(row.title||row.source));
  input.onclick=event=>event.stopPropagation();input.onchange=()=>{if(input.checked){if(selection.grouped)for(const [id,item] of state.selected)if(!item.grouped&&item.day===row.day&&item.source===row.source&&item.kind===row.kind)state.selected.delete(id);state.selected.set(selection.id,selection);}else state.selected.delete(selection.id);updateHistorySelection();};
  const label=document.createElement('div');label.className='history-entry-label';
  const clock=row.captured?new Date(row.captured*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):row.day;
  label.innerHTML=`<span class="history-date">${statsEscape(grouped?row.day:clock)}</span><b>${statsEscape(row.title||row.source)}</b><span class="stats-kind">${historyKind(row)}</span><strong>${statsNumber(row.characters)} <small>chars</small>${row.seconds?' · '+historyDuration(row.seconds):''}${grouped?' · '+statsNumber(row.records)+' records':''}</strong><span class="history-disclosure" aria-hidden="true">›</span>`;
  summary.append(input,label);details.append(summary);const body=document.createElement('div');body.className='history-entry-body';details.append(body);
  let loaded=false;
  details.ontoggle=()=>{
    if(!details.open||loaded)return;loaded=true;
    if(grouped){let offset=0;const more=document.createElement('button');more.textContent='Load more records';
      const load=()=>{more.disabled=true;app.stats_history_query(JSON.stringify({...state.filter,day:row.day,source:row.source,kind:row.kind,grouped:false,offset,limit:50}),response=>{if(readingHistoryState!==state||!details.isConnected)return;const result=JSON.parse(response);if(result.error){body.textContent=result.error;return;}more.remove();for(const entry of result.entries)body.append(historyRow(entry,false));offset+=result.entries.length;if(offset<result.total){more.disabled=false;body.append(more);}updateHistorySelection();});};more.onclick=load;load();
    }else{
      body.textContent='Loading…';app.stats_history_text(row.key,response=>{if(readingHistoryState!==state||!details.isConnected)return;const result=JSON.parse(response);body.replaceChildren();const text=document.createElement('pre');text.className='history-saved-text';text.textContent=result.error||result.text||'No saved text.';body.append(text);if(result.truncated){const note=document.createElement('small');note.textContent='Text shortened.';body.append(note);}});
    }
  };return details;
}
function deleteReadingHistory(){
  const state=readingHistoryState;if(!state)return;
  const selection=state.all?{all_matching:true,filter:state.filter}:{keys:[...state.selected.values()].filter(row=>!row.grouped).map(row=>row.key),groups:[...state.selected.values()].filter(row=>row.grouped).map(row=>row.query)};
  const count=state.all?state.data.records:[...state.selected.values()].reduce((sum,row)=>sum+row.records,0);
  if(!count||!confirm('Delete '+statsNumber(count)+' reading records from statistics?'))return;
  const button=document.getElementById('history-delete');button.disabled=true;
  app.stats_history_delete(JSON.stringify(selection),response=>{if(readingHistoryState!==state)return;const result=JSON.parse(response);document.getElementById('history-error').textContent=result.error||'';if(!result.error){clearHistorySelection();loadReadingHistory();}else updateHistorySelection();});
}
