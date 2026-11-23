let translationConfig=null,translationDraft=null,translationModels=[],translationSequence=0,translationDetectTimer=null,translationModelsRequest=null;
const translationState={text:'',output:'',language:'',target:'en',busy:false,request:'',notice:''};
function translationId(){return String(++translationSequence);}
function openTranslation(config){
  translationConfig=config;translationDraft=structuredClone(config);translationState.target=config.target;
  closeSettings();showSettings(motion);
  const area=document.getElementById('inline-settings');area.replaceChildren();area.dataset.page='translation';area.setAttribute('aria-label','Translation');
  const pane=document.createElement('div');pane.className='translation-pane';area.append(pane);
  const heading=document.createElement('div');heading.className='translation-heading';
  const title=document.createElement('h2');title.textContent='Translation';heading.append(dictionaryBackButton(),title);pane.append(heading);
  const connection=document.createElement('details');connection.className='metadata-selector translation-connection';
  const summary=document.createElement('summary');summary.textContent='Model & connection';connection.append(summary);
  const settings=document.createElement('div');settings.className='translation-provider-settings';connection.append(settings);pane.append(connection);
  const providerRow=document.createElement('label');providerRow.className='translation-field';providerRow.textContent='Provider';
  const provider=document.createElement('select');provider.id='translation-provider';
  for(const item of config.providers){const option=document.createElement('option');option.value=item.id;option.textContent=item.label;provider.append(option);}
  provider.value=config.provider;providerRow.append(provider);settings.append(providerRow);
  const fields=document.createElement('div');fields.id='translation-provider-fields';settings.append(fields);
  const message=document.createElement('p');message.id='translation-connection-status';message.className='settings-intro';message.setAttribute('role','status');settings.append(message);
  provider.onchange=()=>{translationDraft.provider=provider.value;translationModels=[];translationModelsRequest=null;renderTranslationProvider();};
  const grid=document.createElement('div');grid.className='translation-editors';pane.append(grid);
  grid.dataset.layout=config.layout||'columns';
  const inputCard=document.createElement('section');inputCard.className='stats-surface translation-editor';
  const inputHead=document.createElement('div');inputHead.className='translation-editor-heading';
  const source=document.createElement('span');source.id='translation-source-language';source.textContent=translationState.language||'Detect automatically';inputHead.append(source);inputCard.append(inputHead);
  const input=document.createElement('textarea');input.id='translation-input';input.setAttribute('aria-label','Text to translate');input.placeholder='Text to translate';input.value=translationState.text;input.maxLength=50000;inputCard.append(input);grid.append(inputCard);
  const outputCard=document.createElement('section');outputCard.className='stats-surface translation-editor';
  const outputHead=document.createElement('div');outputHead.className='translation-editor-heading';
  const target=document.createElement('select');target.id='translation-target';target.setAttribute('aria-label','Translate into');
  for(const [code,label] of config.languages){const option=document.createElement('option');option.value=code;option.textContent=label;target.append(option);}target.value=translationState.target;outputHead.append(target);
  const copy=document.createElement('button');copy.type='button';copy.id='translation-copy';copy.textContent='Copy';copy.onclick=()=>{if(translationState.output)app.translation_copy(translationState.output);};outputHead.append(copy);outputCard.append(outputHead);
  const output=document.createElement('textarea');output.id='translation-output';output.readOnly=true;output.setAttribute('aria-label','Translated text');output.placeholder='Translation';output.value=translationState.output;outputCard.append(output);grid.append(outputCard);
  const actions=document.createElement('div');actions.className='translation-actions';
  const run=document.createElement('button');run.type='button';run.id='translation-run';run.textContent='Translate (Ctrl+Enter)';run.setAttribute('aria-keyshortcuts','Control+Enter Meta+Enter');run.onclick=startTranslation;
  const layoutButton=document.createElement('button');layoutButton.type='button';layoutButton.id='translation-layout';
  const updateLayoutButton=()=>{const columns=grid.dataset.layout==='columns';layoutButton.title=columns?'Stack text areas':'Place text areas side by side';layoutButton.setAttribute('aria-label',layoutButton.title);layoutButton.innerHTML='<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="'+(columns?'M3 12h18':'M12 4v16')+'"/></svg>';};
  updateLayoutButton();layoutButton.onclick=()=>{const layout=grid.dataset.layout==='columns'?'rows':'columns';grid.dataset.layout=layout;translationDraft.layout=layout;updateLayoutButton();app.translation_save(JSON.stringify({layout}),response=>{const result=JSON.parse(response);if(!result.error)translationConfig.layout=result.layout;});};
  const cancel=document.createElement('button');cancel.type='button';cancel.id='translation-cancel';cancel.textContent='Cancel';cancel.onclick=cancelTranslation;actions.append(run,layoutButton,cancel);pane.append(actions);
  const status=document.createElement('p');status.id='translation-status';status.className='settings-intro';status.setAttribute('role','status');pane.append(status);
  target.onchange=()=>{translationState.target=target.value;translationDraft.target=target.value;cancelTranslation();};
  input.oninput=()=>{
    translationState.text=input.value;if(translationState.busy)cancelTranslation();clearTimeout(translationDetectTimer);
    const request=translationId();translationState.detectRequest=request;
    if(!input.value.trim()){translationState.language='';source.textContent='Detect automatically';return;}
    translationDetectTimer=setTimeout(()=>app.translation_detect(request,input.value),250);
  };
  pane.addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!event.isComposing&&event.keyCode!==229&&!event.repeat){event.preventDefault();run.click();}});
  renderTranslationProvider();updateTranslationView();animatePaneContent(area);
  if(['ollama','lmstudio'].includes(config.provider)&&!translationDraft.profiles[config.provider].model){
    const id=translationId();translationModelsRequest={id,provider:config.provider};app.translation_models(id);
  }
}
function renderTranslationProvider(){
  const area=document.getElementById('translation-provider-fields');if(!area)return;area.replaceChildren();
  const key=translationDraft.provider,profile=translationDraft.profiles[key];
  if(['ollama','lmstudio'].includes(key)){const note=document.createElement('p');note.className='settings-intro';note.textContent='Connects to an already-running server.';area.append(note);}
  function field(label,value,changed,type='text',id=''){
    const row=document.createElement('label');row.className='translation-field';row.textContent=label;
    const input=document.createElement('input');input.type=type;input.value=value||'';if(id)input.id=id;input.oninput=()=>changed(input.value);row.append(input);area.append(row);return input;
  }
  if(key!=='codex')field('Server URL',profile.url,value=>profile.url=value,'url','translation-url');
  const model=field('Model',profile.model,value=>profile.model=value,'text','translation-model');model.placeholder=key==='codex'?'Default Codex model':'Choose or enter a model';model.setAttribute('list','translation-models');
  const list=document.createElement('datalist');list.id='translation-models';for(const name of translationModels){const option=document.createElement('option');option.value=name;list.append(option);}area.append(list);
  if(key!=='codex'){
    const secret=field('API key','',value=>{if(value)profile.api_key=value;else delete profile.api_key;},'password','translation-api-key');
    secret.autocomplete='off';secret.placeholder=profile.key_saved?'Saved · leave blank to keep':(['ollama','lmstudio'].includes(key)?'Optional':'API key');
  }
  const actions=document.createElement('div');actions.className='translation-connection-actions';area.append(actions);
  const models=document.createElement('button');models.type='button';models.textContent='Load models';models.id='translation-load-models';
  models.onclick=()=>saveTranslationConfig(()=>{models.disabled=true;document.getElementById('translation-connection-status').textContent='Loading models…';const id=translationId();translationModelsRequest={id,provider:key};app.translation_models(id);});actions.append(models);
  const save=document.createElement('button');save.type='button';save.textContent='Save connection';save.onclick=()=>saveTranslationConfig(()=>document.getElementById('translation-connection-status').textContent='Connection saved.');actions.append(save);
  if(key==='codex'){
    const account=document.createElement('p');account.className='translation-account';account.textContent=profile.connected?'Connected · '+profile.account+' via Codex CLI':(translationConfig.codex_available?'Uses your existing Codex login. Browser sign-in opens if needed.':'Install Codex CLI to connect your ChatGPT account.');area.prepend(account);
    const connect=document.createElement('button');connect.type='button';connect.id='translation-codex-connect';connect.textContent=profile.connected?'Reconnect':'Connect account';
    connect.onclick=()=>{connect.disabled=true;document.getElementById('translation-connection-status').textContent='Signing in…';app.translation_codex_connect(translationId());};actions.prepend(connect);
    if(profile.connected){const disconnect=document.createElement('button');disconnect.type='button';disconnect.textContent='Disconnect';disconnect.onclick=()=>app.translation_codex_disconnect(result=>{translationConfig=JSON.parse(result);translationDraft.profiles.codex=structuredClone(translationConfig.profiles.codex);renderTranslationProvider();});actions.append(disconnect);}
  }else if(profile.key_saved){
    const clear=document.createElement('button');clear.type='button';clear.textContent='Remove saved key';clear.onclick=()=>{profile.api_key='';saveTranslationConfig(()=>{profile.key_saved=false;renderTranslationProvider();});};actions.append(clear);
  }
}
function saveTranslationConfig(next){
  translationDraft.target=translationState.target;
  app.translation_save(JSON.stringify(translationDraft),response=>{
    const result=JSON.parse(response);
    if(result.error){document.getElementById('translation-connection-status').textContent=result.error;return;}
    translationConfig=result;
    for(const [key,profile] of Object.entries(result.profiles)){delete translationDraft.profiles[key].api_key;Object.assign(translationDraft.profiles[key],profile);}
    const secret=document.getElementById('translation-api-key');if(secret){secret.value='';if(result.profiles[result.provider].key_saved)secret.placeholder='Saved · leave blank to keep';}
    next?.();
  });
}
function updateTranslationView(){
  const run=document.getElementById('translation-run');if(!run)return;
  run.disabled=translationState.busy;run.innerHTML=translationState.busy?'Translating…':'Translate <span class="translation-shortcut">(Ctrl+Enter)</span>';document.getElementById('translation-cancel').hidden=!translationState.busy;
  document.getElementById('translation-status').textContent=translationState.notice;
  document.getElementById('translation-output').value=translationState.output;
  document.getElementById('translation-source-language').textContent=translationState.language||'Detect automatically';
  document.getElementById('translation-copy').disabled=!translationState.output;
}
function startTranslation(){
  if(translationState.busy)return;
  if(!translationState.text.trim()){translationState.notice='Enter text to translate.';updateTranslationView();return;}
  saveTranslationConfig(()=>{
    translationState.request=translationId();translationState.busy=true;translationState.notice='';updateTranslationView();
    app.translation_run(translationState.request,translationState.text,translationState.target);
  });
}
function cancelTranslation(){
  if(translationState.busy)app.translation_cancel();translationState.request='';translationState.busy=false;translationState.notice='';updateTranslationView();
}
function translationResult(kind,id,result){
  if(kind==='detect'){
    if(id!==translationState.detectRequest)return;translationState.language=result.name||'';updateTranslationView();return;
  }
  if(kind==='translate'){
    if(id!==translationState.request)return;translationState.busy=false;translationState.notice=result.error||'';
    if(!result.error){translationState.output=result.translation;translationState.language=result.source_language||translationState.language;}updateTranslationView();return;
  }
  const status=document.getElementById('translation-connection-status');
  if(kind==='models'){
    if(id!==translationModelsRequest?.id||translationDraft.provider!==translationModelsRequest.provider)return;
    const button=document.getElementById('translation-load-models');if(button)button.disabled=false;
    if(result.error){if(status)status.textContent=result.error;return;}
    translationModels=result.models;const profile=translationDraft.profiles[translationDraft.provider];
    if(!profile.model&&translationModels.length)profile.model=translationModels.find(name=>name.startsWith('translategemma'))||translationModels[0];
    renderTranslationProvider();if(status)status.textContent=translationModels.length?'Models loaded.':'No models found. Enter a model name.';
  }
  if(kind==='account'){
    if(result.settings){translationConfig=result.settings;translationDraft.profiles.codex=structuredClone(result.settings.profiles.codex);}renderTranslationProvider();if(status)status.textContent=result.error||result.message||'';
  }
}
