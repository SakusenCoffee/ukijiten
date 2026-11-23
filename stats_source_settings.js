let statsSettingsDraft = null;
let statsDeckNames = [];
let statsDeckRequest = null;
const statsSourceExpanded=new Set(),statsProviderExpanded=new Set();
const statsSourceLabels = {gsm:'Texthooker WebSocket',mokuro_browser:'Mokuro Browser',gsm_history:'GSM database',anki:'Anki',mokuro:'Mokuro',ttsu:'Ttsu Reader',jpdb:'jpdb.io',renshuu:'Renshuu',files:'Reading history files'};
function showStatsSourceSettings() {
  if (!readingStats?.source_settings) return;
  statsSettingsDraft = structuredClone(readingStats.source_settings);
  statsSourceExpanded.clear();statsProviderExpanded.clear();
  statsDeckNames = [...statsSettingsDraft.anki.decks];
  renderStatsSourceSettings();
}
function renderStatsSourceSettings() {
  const area=document.getElementById('reading-stats');
  if(!area || !statsSettingsDraft)return;
  area.replaceChildren();
  const heading=document.createElement('div');heading.className='stats-top';
  const back=document.createElement('button');back.className='dictionary-back-icon';back.title='Back to Statistics';back.setAttribute('aria-label',back.title);back.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3 3 8l5 5M3 8h9M5 20v-4m6 4v-8m6 8V6m5 14H3"/></svg>';
  back.onclick=()=>{statsSettingsDraft=null;updateReadingStats(readingStats);};
  const title=document.createElement('h2');title.textContent='Stats settings';const navigation=document.createElement('div');navigation.className='settings-navigation';navigation.append(back,dictionaryBackButton());heading.append(navigation,title);area.append(heading);
  const form=document.createElement('form');form.className='stats-source-settings';area.append(form);
  const description=document.createElement('p');description.className='stats-setting-note';description.textContent='Disabling a source stops updates. Uploaded files stay enabled.';form.append(description);
  function rememberExpanded(details,key,expanded){
    details.open=expanded.has(key);
    details.addEventListener('toggle',()=>{if(!details.isConnected)return;if(details.open)expanded.add(key);else expanded.delete(key);});
  }
  function sourceHeading(title,conf){
    const head=document.createElement('summary');head.className='stats-source-heading';
    const name=document.createElement('strong');name.className='stats-source-name';name.textContent=title;
    const toggleLabel=document.createElement('label');toggleLabel.className='stats-source-toggle stats-source-switch';
    const state=document.createElement('span');state.textContent=conf.enabled?'Enabled':'Disabled';
    const toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=conf.enabled;toggle.setAttribute('role','switch');toggle.setAttribute('aria-label',title);
    toggle.onclick=event=>event.stopPropagation();toggleLabel.onclick=event=>event.stopPropagation();
    toggle.onchange=()=>{conf.enabled=toggle.checked;state.textContent=conf.enabled?'Enabled':'Disabled';updateCloudConnections();};
    toggleLabel.append(state,toggle);head.append(name,toggleLabel);return head;
  }
  function field(parent,label,value,changed,type='text',hint='') {
    const row=document.createElement('label');row.className='stats-source-field';
    const caption=document.createElement('span');caption.textContent=label;
    const input=document.createElement(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;
    input.value=value??'';if(type==='textarea')input.rows=3;
    input.oninput=()=>changed(input.value);row.append(caption,input);
    if(hint){const note=document.createElement('small');note.textContent=hint;row.append(note);}
    parent.append(row);return input;
  }
  function paths(parent,source) {
    const conf=statsSettingsDraft[source];
    const choose=document.createElement('button');choose.type='button';choose.textContent=source==='gsm_history'?'Choose database…':'Choose files…';
    choose.onclick=()=>app.stats_pick_files(source,response=>{
      const selected=JSON.parse(response);if(!selected.length)return;
      if(source==='gsm_history')conf.path=selected[0];else conf.paths=[...new Set([...conf.paths,...selected])];
      renderStatsSourceSettings();
    });parent.append(choose);
    const list=document.createElement('div');list.className='stats-selected-files';
    const files=source==='gsm_history'?(conf.path?[conf.path]:[]):conf.paths;
    for(const path of files) {
      if(source!=='anki' && (readingStats.imported_files||[]).some(file=>file.path===path))continue;
      const row=document.createElement('div');row.className='stats-file-row';
      const name=document.createElement('span');name.textContent=path.split(/[\\/]/).pop();name.title=path;
      const remove=document.createElement('button');remove.type='button';remove.textContent='Remove';
      remove.onclick=()=>{if(source==='gsm_history')conf.path='';else conf.paths=conf.paths.filter(p=>p!==path);renderStatsSourceSettings();};
      row.append(name,remove);list.append(row);
    }
    parent.append(list);
  }
  function provider(parent,key,title) {
    const conf=statsSettingsDraft.mokuro[key],details=document.createElement('details');details.className='mokuro-provider';details.dataset.provider=key;
    rememberExpanded(details,key,statsProviderExpanded);
    const summary=sourceHeading(title,conf);if(['google_drive','mega','onedrive'].includes(key)){const status=document.createElement('span');status.className='cloud-status';status.dataset.cloudStatus=key;summary.insertBefore(status,summary.lastElementChild);}details.append(summary);
    const body=document.createElement('div');body.className='mokuro-provider-body';details.append(body);
    parent.append(details);return body;
  }
  statsSettingsDraft.day??={cutoff_hour:0};
  const dayCard=document.createElement('section');dayCard.className='stats-surface';dayCard.id='stats-day-boundary';
  const dayTitle=document.createElement('h3');dayTitle.textContent='Day boundary';dayCard.append(dayTitle);
  const dayInput=field(dayCard,'Hours after midnight',statsSettingsDraft.day.cutoff_hour,()=>{},'number','');
  dayInput.id='stats-day-cutoff';dayInput.min=0;dayInput.max=23;dayInput.step=1;dayInput.required=true;
  const dayNote=document.createElement('p');dayNote.className='stats-setting-note';dayCard.append(dayNote);
  const describeDay=()=>dayNote.textContent='Before '+String(statsSettingsDraft.day.cutoff_hour).padStart(2,'0')+':00 counts toward the previous day. Imported daily totals keep their dates.';
  dayInput.oninput=()=>{if(dayInput.value!==''&&dayInput.checkValidity()){statsSettingsDraft.day.cutoff_hour=Number(dayInput.value);describeDay();}};
  describeDay();form.append(dayCard);
  for(const [source,label] of Object.entries(statsSourceLabels)) {
    const conf=statsSettingsDraft[source],card=document.createElement('details');card.className='stats-surface stats-source-setting';card.dataset.source=source;
    rememberExpanded(card,source,statsSourceExpanded);card.append(sourceHeading(label,conf));
    const content=document.createElement('div');content.className='stats-source-body';card.append(content);
    const setup=document.createElement('div');setup.className='stats-source-setup';content.append(setup);
    const metricSource=source==='gsm_history'?'gsm':source,metricConfig=statsSettingsDraft[metricSource];
    const metrics=document.createElement('div');metrics.className='stats-metric-options';
    const choices=['gsm','gsm_history','mokuro','mokuro_browser','ttsu','files'].includes(source)?[['include_characters','Include characters'],['include_time','Include time']]:source==='anki'?[['include_time','Include review time']]:[['include_activity','Include study activity'],...(source==='jpdb'?[['include_anki_reviews','Include reviews imported from Anki']]:[])];
    for(const [key,title] of choices){const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.checked=metricConfig[key]!==false;input.dataset.metricSource=metricSource;input.dataset.metric=key;input.onchange=()=>{metricConfig[key]=input.checked;for(const other of document.querySelectorAll('[data-metric-source="'+metricSource+'"][data-metric="'+key+'"]'))other.checked=input.checked;};label.append(input,document.createTextNode(title));metrics.append(label);}setup.append(metrics);
    if(source==='gsm_history'){const note=document.createElement('p');note.className='stats-setting-note';note.textContent='Character and time selection is shared with live text to keep overlapping GSM records consistent.';setup.append(note);}
    if(source==='gsm') field(setup,'WebSocket URL',conf.url,value=>conf.url=value,'text','Default: ws://127.0.0.1:55000/ws/texthooker');
    if(source==='mokuro_browser') field(setup,'History database',conf.path,value=>conf.path=value,'text','Updates automatically while reading. Time is estimated between scans up to 90 seconds apart.');
    if(['gsm_history','mokuro','files','ttsu','jpdb','renshuu'].includes(source)) paths(setup,source);
    if(['ttsu','jpdb','renshuu'].includes(source)){
      const note=document.createElement('p');note.className='stats-setting-note';note.textContent={ttsu:'Manage → select books → Export → ZIP, with Statistics selected. Statistics JSON and export folders also work.',jpdb:'Settings → Export vocabulary reviews (.json). This contains review activity, without recorded time or character totals.',renshuu:'Use an API key from Renshuu Settings to import study-goal completion. This data is a percentage, without recorded time or character totals.'}[source];setup.prepend(note);
      const site=document.createElement('button');site.type='button';site.textContent='Open '+label;site.onclick=()=>app.stats_open_site(source);setup.append(site);
    }
    if(source==='ttsu'){
      const input=field(setup,'Export folder',conf.folder,value=>conf.folder=value,'text','Refresh reads statistics_*.json files inside this folder.');
      const choose=document.createElement('button');choose.type='button';choose.textContent='Choose export folder…';choose.onclick=()=>app.stats_pick_import_folder('ttsu',path=>{if(path){conf.folder=path;input.value=path;}});setup.append(choose);
    }
    if(source==='renshuu'){
      field(setup,'API key','',value=>{if(value)conf.key=value;else delete conf.key;},'password',conf.key_saved?'Saved. Leave blank to keep.':'');
      const saveConnection=document.createElement('button');saveConnection.type='button';saveConnection.textContent='Save connection';saveConnection.onclick=()=>{saveConnection.disabled=true;app.stats_save_sources(JSON.stringify({renshuu:{...conf,enabled:true}}),response=>{const result=JSON.parse(response);saveConnection.disabled=false;if(result.error){document.getElementById('stats-source-save-status').textContent=result.error;return;}readingStats.source_settings=result.settings;statsSettingsDraft.renshuu=result.settings.renshuu;renderStatsSourceSettings();document.getElementById('stats-source-save-status').textContent='Connection saved. Use Refresh to update activity.';});};setup.append(saveConnection);
    }
    if(source==='mokuro') {
      for(const [key,label] of [['google_drive','Google Drive'],['mega','MEGA'],['onedrive','OneDrive']]) {
        const body=provider(setup,key,label),connection=conf[key];
        const account=document.createElement('p');account.className='cloud-account';account.dataset.cloudAccount=key;body.append(account);
        const actions=document.createElement('div');actions.className='cloud-actions';
        const connect=document.createElement('button');connect.type='button';connect.dataset.cloudConnect=key;connect.textContent='Connect';
        connect.onclick=()=>{connect.disabled=true;app.stats_cloud_connect(key);};
        const disconnect=document.createElement('button');disconnect.type='button';disconnect.textContent='Disconnect';disconnect.dataset.cloudDisconnect=key;
        disconnect.onclick=()=>{disconnect.disabled=true;app.stats_cloud_disconnect(key,response=>{
          const result=JSON.parse(response);disconnect.disabled=false;
          if(result.error){document.getElementById('stats-source-save-status').textContent=result.error;return;}
          readingStats.cloud_connections=result.connections;
          statsSettingsDraft.mokuro[key].enabled=false;
          renderStatsSourceSettings();
        });};actions.append(connect,disconnect);body.append(actions);
        field(body,'History file path',connection.path,value=>connection.path=value,'text','Within the same cloud account used by Mokuro.');
      }
      const webdav=conf.webdav,body=provider(setup,'webdav','WebDAV');
      field(body,'WebDAV URL',webdav.webdav_server_url,v=>webdav.webdav_server_url=v,'url','The folder containing mokuro-reader/volume-data.json.');
      field(body,'Username',webdav.webdav_username,v=>webdav.webdav_username=v);
      field(body,'Password','',v=>{if(v)webdav.webdav_password=v;else delete webdav.webdav_password;},'password',webdav.webdav_password_saved?'Saved. Leave blank to keep.':'');
      field(body,'Bearer token','',v=>{if(v)webdav.webdav_token=v;else delete webdav.webdav_token;},'password','Optional alternative to a password.');
      const webdavActions=document.createElement('div');webdavActions.className='cloud-actions';
      const connectWebdav=document.createElement('button');connectWebdav.type='button';connectWebdav.id='stats-webdav-save';
      connectWebdav.textContent=webdav.webdav_password_saved||webdav.webdav_token_saved?'Save connection':'Connect';webdavActions.append(connectWebdav);body.append(webdavActions);
      const webdavStatus=document.createElement('p');webdavStatus.id='stats-webdav-status';webdavStatus.className='stats-setting-note';webdavStatus.setAttribute('role','status');body.append(webdavStatus);
      connectWebdav.onclick=()=>{
        if(![...body.querySelectorAll('input')].every(input=>input.reportValidity()))return;
        connectWebdav.disabled=true;webdavStatus.textContent='Saving…';
        app.stats_save_sources(JSON.stringify({mokuro:{enabled:true,webdav:{...webdav,enabled:true}}}),response=>{
          const result=JSON.parse(response);connectWebdav.disabled=false;
          if(result.error){webdavStatus.textContent=result.error;return;}
          readingStats.source_settings=result.settings;statsSettingsDraft.mokuro.enabled=true;statsSettingsDraft.mokuro.webdav=result.settings.mokuro.webdav;
          statsSourceExpanded.add('mokuro');statsProviderExpanded.add('webdav');renderStatsSourceSettings();
          document.getElementById('stats-webdav-status').textContent='Connection saved. Use Refresh to import history.';
        });
      };
      if(webdav.webdav_password_saved || webdav.webdav_token_saved){const account=document.createElement('p');account.className='cloud-account';account.textContent='Saved login: '+(webdav.webdav_username||'Bearer token');body.prepend(account);const clear=document.createElement('button');clear.type='button';clear.textContent='Disconnect';clear.onclick=()=>{clear.disabled=true;app.stats_cloud_disconnect('webdav',response=>{const result=JSON.parse(response);if(result.error){clear.disabled=false;document.getElementById('stats-source-save-status').textContent=result.error;return;}statsSettingsDraft.mokuro.webdav=result.settings.mokuro.webdav;renderStatsSourceSettings();});};body.append(clear);}
      const local=provider(setup,'local_folder','Local Folder');
      const input=field(local,'Folder',conf.local_folder.path,v=>conf.local_folder.path=v,'text','Choose the folder containing volume-data.json or mokuro-reader.');
      const choose=document.createElement('button');choose.type='button';choose.textContent='Choose folder…';choose.onclick=()=>app.stats_pick_folder(path=>{if(path){conf.local_folder.path=path;input.value=path;}});local.append(choose);
    }
    if(source==='files') {const upload=document.createElement('button');upload.type='button';upload.id='stats-source-import';upload.textContent='Import now…';upload.onclick=()=>app.stats_import();setup.append(upload);const note=document.createElement('p');note.className='stats-setting-note';note.textContent='Ttsu statistics ZIP/JSON, activity CSV, text records, or character totals. Reload reads selected files.';setup.prepend(note);}
    if(source==='anki') {
      const row=document.createElement('label');row.className='stats-source-field';const caption=document.createElement('span');caption.textContent='Connection';
      const backend=document.createElement('select');backend.id='stats-anki-backend';
      for(const [value,label] of [['connect','AnkiConnect'],['collection','Collection files (desktop or sync server)']]){const option=document.createElement('option');option.value=value;option.textContent=label;backend.append(option);}
      backend.value=conf.backend;backend.onchange=()=>{conf.backend=backend.value;renderStatsSourceSettings();};row.append(caption,backend);setup.append(row);
      if(conf.backend==='connect') {
        field(setup,'AnkiConnect URL',conf.url,value=>conf.url=value,'url','Open Anki with the AnkiConnect add-on. Default port: 8765.');
        field(setup,'API key', '',value=>{if(value)conf.key=value;else delete conf.key;},'password',conf.key_saved?'Saved. Leave blank to keep.':'Optional.');
        if(conf.key_saved){const clear=document.createElement('button');clear.type='button';clear.textContent='Clear saved API key';clear.onclick=()=>{conf.key='';conf.key_saved=false;renderStatsSourceSettings();};setup.append(clear);}
      } else paths(setup,'anki');
      const load=document.createElement('button');load.type='button';load.id='stats-load-decks';load.textContent='Load decks';
      load.onclick=()=>{load.disabled=true;load.textContent='Loading…';statsDeckRequest=JSON.stringify(conf);app.stats_load_decks(statsDeckRequest);};setup.append(load);
      const notice=document.createElement('p');notice.id='stats-decks-notice';notice.className='stats-setting-note';notice.textContent='Includes subdecks. Select the decks whose review time you want to count.';setup.append(notice);
      const decks=document.createElement('div');decks.id='stats-deck-list';decks.className='stats-deck-list';setup.append(decks);renderStatsDeckChoices();
    }
    const uploads=document.createElement('div');uploads.className='stats-uploaded-files';uploads.dataset.assetSource=source;content.append(uploads);
    form.append(card);
    // Deck list belongs to this card; render after it is attached.
    if(source==='anki')renderStatsDeckChoices();
  }
  renderManualEntries(form);
  refreshUploadedFiles();
  updateCloudConnections();
  const status=document.createElement('p');status.id='stats-source-save-status';status.setAttribute('role','status');form.append(status);
  const actions=document.createElement('div');actions.className='stats-actions';const save=document.createElement('button');save.type='submit';save.textContent='Save';actions.append(save);form.append(actions);
  setupStatsBackToTop();
  form.onsubmit=event=>{event.preventDefault();if(!form.reportValidity())return;save.disabled=true;
    app.stats_save_sources(JSON.stringify(statsSettingsDraft),response=>{
      const result=JSON.parse(response);save.disabled=false;
      if(result.error){status.textContent=result.error;return;}
      readingStats.refresh_notice='';readingStats.source_settings=result.settings;statsSettingsDraft=null;statsNotice='Settings saved';updateReadingStats(readingStats);
    });
  };
}
function renderStatsDeckChoices() {
  const list=document.getElementById('stats-deck-list');if(!list || !statsSettingsDraft)return;
  list.replaceChildren();const selected=statsSettingsDraft.anki.decks;
  for(const name of [...new Set([...statsDeckNames,...selected])].sort()) {
    const row=document.createElement('label'),input=document.createElement('input'),label=document.createElement('span');input.type='checkbox';input.checked=selected.includes(name);label.textContent=name;
    input.onchange=()=>{statsSettingsDraft.anki.decks=input.checked?[...new Set([...statsSettingsDraft.anki.decks,name])]:statsSettingsDraft.anki.decks.filter(d=>d!==name);};row.append(input,label);list.append(row);
  }
}
function statsDecksLoaded(result) {
  if(!statsSettingsDraft)return;
  const button=document.getElementById('stats-load-decks');if(button){button.disabled=false;button.textContent='Load decks';}
  const notice=document.getElementById('stats-decks-notice');
  if(statsDeckRequest!==JSON.stringify(statsSettingsDraft.anki)){if(notice)notice.textContent='Connection changed. Load decks again.';return;}
  if(result.error){if(notice)notice.textContent=result.error;return;}
  statsDeckNames=result.decks;renderStatsDeckChoices();if(notice)notice.textContent=result.decks.length?'Includes subdecks.':'No decks found.';
}

function refreshUploadedFiles() {
  if(!statsSettingsDraft)return;
  for(const list of document.querySelectorAll('[data-asset-source]')) {
    const source=list.dataset.assetSource;
    list.replaceChildren();
    const files=(readingStats.imported_files||[]).filter(file=>file.kind===source);
    if(!files.length)continue;
    const title=document.createElement('h4');title.textContent='Imported history';list.append(title);
    for(const file of files) {
      const row=document.createElement('div');row.className='stats-file-row';row.dataset.assetId=file.id;
      const text=document.createElement('div'),name=document.createElement('strong'),info=document.createElement('small');name.textContent=file.name;name.title=file.path||'';
      info.textContent=file.kind==='jpdb'?statsNumber(file.reviews)+' reviews':file.kind==='renshuu'?statsNumber(file.activity_days)+' days of study-goal activity':statsNumber(file.characters)+' characters · '+Math.floor(file.seconds/3600)+'h '+Math.floor(file.seconds%3600/60)+'m';text.append(name,info);
      const remove=document.createElement('button');remove.type='button';remove.textContent='Remove';remove.title='Remove this history from the totals';
      remove.onclick=()=>{remove.disabled=true;app.stats_remove_file(file.id,response=>{
        const result=JSON.parse(response);
        if(result.error){remove.disabled=false;document.getElementById('stats-source-save-status').textContent=result.error;return;}
        readingStats.imported_files=result.files;
        if(file.path && statsSettingsDraft[source]?.paths)statsSettingsDraft[source].paths=statsSettingsDraft[source].paths.filter(path=>path!==file.path);
        if(file.kind==='mokuro' && !result.settings.mokuro.local_folder.enabled)statsSettingsDraft.mokuro.local_folder.enabled=false;
        if(file.id.startsWith('cloud:')){const key=file.id.split(':')[1];if(statsSettingsDraft.mokuro[key])statsSettingsDraft.mokuro[key].enabled=false;}
        renderStatsSourceSettings();
      });};row.append(text,remove);list.append(row);
    }
  }
}

function renderManualEntries(parent) {
  document.getElementById('stats-manual-entries')?.remove();
  const entries=readingStats.manual_entries||[];if(!entries.length)return;
  const card=document.createElement('section');card.id='stats-manual-entries';card.className='stats-surface';
  const title=document.createElement('h3');title.textContent='Manual entries';card.append(title);
  for(const entry of entries) {
    const row=document.createElement('div');row.className='stats-file-row';
    const text=document.createElement('div'),name=document.createElement('strong'),info=document.createElement('small');name.textContent=entry.description;
    info.textContent=entry.day+' · '+statsNumber(entry.characters)+' characters · '+Math.floor(entry.seconds/3600)+'h '+Math.floor(entry.seconds%3600/60)+'m';text.append(name,info);
    const remove=document.createElement('button');remove.type='button';remove.textContent='Remove';
    remove.onclick=()=>app.stats_remove_manual(entry.id,response=>{if(JSON.parse(response).ok){readingStats.manual_entries=readingStats.manual_entries.filter(item=>item.id!==entry.id);renderManualEntries(parent);}});
    row.append(text,remove);card.append(row);
  }
  parent.append(card);
}

function updateCloudConnections() {
  const labels={connected:'Connected',saved:'Saved connection',disconnected:'Not connected',needs_auth:'Sign-in required',connecting:'Signing in…',error:'Could not refresh'};
  for(const key of ['google_drive','mega','onedrive']) {
    const connection=readingStats?.cloud_connections?.[key]||{state:'disconnected'};
    const mokuro=statsSettingsDraft?.mokuro||readingStats?.source_settings?.mokuro;
    const enabled=!!(mokuro?.enabled&&mokuro[key]?.enabled);
    const hideFailure=!enabled&&['needs_auth','error'].includes(connection.state);
    const status=document.querySelector('[data-cloud-status='+key+']');if(status){status.hidden=hideFailure;status.textContent=hideFailure?'':labels[connection.state]||'Not connected';status.dataset.state=hideFailure?'disabled':connection.state;}
    const account=document.querySelector('[data-cloud-account='+key+']');
    if(account)account.textContent=connection.account?'Account: '+connection.account:(connection.configured?'Account details unavailable. Refresh or reconnect.':'');
    const connect=document.querySelector('[data-cloud-connect='+key+']');if(connect){connect.disabled=connection.state==='connecting'||!!readingStats.refreshing;connect.textContent=enabled&&connection.state==='needs_auth'?'Sign in again':connection.configured?'Reconnect':'Connect';}
    const disconnect=document.querySelector('[data-cloud-disconnect='+key+']');if(disconnect){disconnect.hidden=!connection.configured && connection.state!=='connecting';disconnect.disabled=!!readingStats.refreshing;}
  }
}
