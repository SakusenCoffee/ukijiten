const settingsSectionState={};
function rememberSection(section,key){section.addEventListener('toggle',()=>{
  if(settingsSectionState[key]===section.open)return;
  settingsSectionState[key]=section.open;if(app)app.section_preference(key,section.open);
});}
function makeSettingsSection(title,key){
  const section=document.createElement('details');section.className='settings-section';section.dataset.section=key;section.open=!!settingsSectionState[key];
  const summary=document.createElement('summary');summary.textContent=title;section.append(summary);
  rememberSection(section,key);return section;
}
function folderPickerControl(choose,remove,kind,values){
  const group=imagePickerControl(choose,kind,values);group.classList.add('folder-picker-control');group.dataset.folderPicker='true';
  group.querySelector('.image-visibility').id=kind+'-folder-toggle';
  remove.hidden=false;remove.classList.add('image-remove');group.querySelector('.image-remove').replaceWith(remove);
  updateImagePicker(group,values);return group;
}
const imageEyeIcon='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/><path class="eye-slash" d="m3 3 18 18"/></svg>';
function updateImagePicker(group,values){
  const kind=group.dataset.imageKind,key=kind==='avatar'?'avatar':'background_image',hidden=!!values[kind+'_hidden'];
  const eye=group.querySelector('.image-visibility');eye.setAttribute('aria-pressed',String(!hidden));eye.classList.toggle('image-hidden',hidden);eye.title=(hidden?'Show ':'Hide ')+kind+' image';eye.setAttribute('aria-label',eye.title);
  eye.disabled=!values[key];group.querySelector('.image-remove').disabled=!(group.dataset.folderPicker?values[kind+'_folder']:values[key]);
}
function imagePickerControl(choose,kind,values){
  const group=document.createElement('div');group.className='image-picker-control';group.dataset.imageKind=kind;
  const eye=document.createElement('button');eye.type='button';eye.className='image-visibility';eye.id=kind==='avatar'?'avatar-image-toggle':'background-image-toggle';eye.innerHTML=imageEyeIcon;
  eye.onclick=()=>{const key=kind+'_hidden';motion[key]=!motion[key];values[key]=motion[key];updateImagePicker(group,values);app.preference(key,JSON.stringify(motion[key]));};
  const remove=document.createElement('button');remove.type='button';remove.className='image-remove';remove.id='remove-'+kind+'-image';remove.textContent='×';remove.title='Remove '+kind+' image';remove.setAttribute('aria-label',remove.title);remove.onclick=()=>app.remove_image(kind);
  group.append(choose,eye,remove);updateImagePicker(group,values);return group;
}
function previewSettingsSection(section){
  const summary=section.querySelector(':scope > summary'),first=summary.nextElementSibling,title=summary.textContent;
  if(!first)return;
  const group=document.createElement('section');group.className='settings-preview-group';
  const heading=document.createElement('button');heading.type='button';heading.className='settings-preview-heading';heading.textContent=summary.textContent;
  heading.onclick=toggleExpanded;
  summary.replaceChildren();summary.setAttribute('aria-label','Expand '+title);
  const footer=document.createElement('button');footer.type='button';footer.className='settings-preview-footer';footer.onclick=toggleExpanded;
  section.before(group);
  const corners=section.querySelector('.pane-corner-controls');
  if(corners){
    const tools=document.createElement('div');tools.className='settings-source-buttons settings-image-tools';
    const crop=section.querySelector('#edit-avatar-image,#edit-background-image');
    if(crop)tools.append(crop);tools.append(corners);
    group.append(heading,first,tools,section,footer);
  }else group.append(heading,first,section,footer);
  const sync=()=>{for(const button of [heading,footer]){button.setAttribute('aria-expanded',String(section.open));button.setAttribute('aria-label',(section.open?'Collapse ':'Expand ')+title);}footer.textContent='Collapse';footer.hidden=!section.open;group.classList.toggle('expanded',section.open);};
  let animation;
  function toggleExpanded(){
    const before=group.getBoundingClientRect().height;
    animation?.cancel();section.open=!section.open;sync();
    const after=group.getBoundingClientRect().height;
    if(!matchMedia('(prefers-reduced-motion: reduce)').matches){
      animation=group.animate([{height:before+'px'},{height:after+'px'}],{duration:210,easing:'cubic-bezier(.2,.7,.2,1)'});
    }
  }
  summary.onclick=event=>{event.preventDefault();toggleExpanded();};
  section.addEventListener('toggle',sync);sync();
}
function collapseSettingsSections(area,prefix){
  for(const heading of [...area.querySelectorAll(':scope > h3')]){
    if(heading.textContent==='Dictionaries')continue;
    const section=makeSettingsSection(heading.textContent,prefix+'-'+heading.textContent.toLowerCase().replaceAll(/[^a-z0-9]+/g,'-'));
    let next=heading.nextElementSibling;heading.replaceWith(section);
    while(next&&next.tagName!=='H3'&&next.tagName!=='DETAILS') {const following=next.nextElementSibling;section.append(next);next=following;}
  }
}
function dictionaryBackButton() {
  const button=document.createElement('button');button.className='dictionary-back-icon';button.title='Back to dictionary';button.setAttribute('aria-label','Back to dictionary');button.onclick=closeSettings;
  button.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 8V3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8M4 17h7M8 7h3M8 10h3"/><circle cx="17" cy="14" r="4"/><path d="m20 17 2 2"/></svg>';
  return button;
}
function isWordDictionary(dictionary){return !dictionary.frequency&&!dictionary.pitch&&!dictionary.kanji&&!dictionary.kanji_frequency;}
function appendCharacterSelectors(area,values,dictionaries,main){
  for(const [kind,title] of [['kanji','Kanji / Hanzi dictionaries'],['kanji_frequency','Kanji / Hanzi frequency']]){
    const candidates=dictionaries.filter(dictionary=>dictionary[kind]);if(!candidates.length)continue;
    const group=makeSettingsSection(title,(main?'dictionary-':'popup-')+kind);
    group.className='metadata-selector';group.dataset.kind=kind;
    const list=document.createElement('div');list.className='metadata-source-list';group.append(list);
    for(const dictionary of candidates){
      const row=document.createElement('div');row.className='settings-row metadata-source-row';row.dataset.characterSource=dictionary.path;
      const label=document.createElement('label');label.className='popup-dictionary-label';
      const name=document.createElement('span');name.textContent=dictionary.title;
      const input=document.createElement('input');input.type='checkbox';input.checked=main?dictionary.enabled:!values.disabled_paths.includes(dictionary.path);
      input.setAttribute('aria-label','Enable '+dictionary.title);
      input.onchange=()=>main?app.dictionary_action('toggle',JSON.stringify({id:dictionary.id,enabled:input.checked})):app.popup_preference('dictionary',JSON.stringify({path:dictionary.path,enabled:input.checked}));
      label.append(name,input);row.append(label);
      if(main){
        const buttons=document.createElement('div');buttons.className='popup-order-buttons';
        const remove=document.createElement('button');remove.textContent='×';remove.title='Remove dictionary';remove.setAttribute('aria-label','Remove '+dictionary.title);
        remove.onclick=()=>app.dictionary_action('remove',JSON.stringify(dictionary.id));buttons.append(remove);row.append(buttons);
      }
      list.append(row);
    }
    area.append(group);
  }
}
function appendMetadataSelectors(area,values,dictionaries,prefix,save) {
  for(const [key,label,capability] of [[prefix+'frequency_paths','Frequency dictionaries','frequency'],[prefix+'pitch_paths','Pitch accent dictionaries','pitch']]) {
    const orderKey=prefix+capability+'_order';
    const rank=new Map((values[orderKey]?.length?values[orderKey]:values[key]||[]).map((path,index)=>[path,index]));
    const group=document.createElement('details');group.className='metadata-selector';const stateKey='metadata-'+prefix+capability;group.open=!!settingsSectionState[stateKey];group.dataset.kind=capability;rememberSection(group,stateKey);
    const summary=document.createElement('summary');summary.textContent=label;group.append(summary);
    const list=document.createElement('div');list.className='metadata-source-list';group.append(list);
    const candidates=dictionaries.filter(dictionary=>dictionary[capability]).sort((a,b)=>(rank.get(a.path)??rank.size)-(rank.get(b.path)??rank.size));
    if(!candidates.length){const empty=document.createElement('p');empty.className='settings-intro';empty.textContent='Add a '+(capability==='pitch'?'pitch accent':'frequency')+' dictionary in Dictionaries.';list.append(empty);}
    const persist=()=>{values[orderKey]=[...list.children].map(row=>row.dataset.path);save(orderKey,values[orderKey]);};
    let dragging=null;
    for(const dictionary of candidates){
      const row=document.createElement('div');row.className='settings-row metadata-source-row';row.dataset.path=dictionary.path;row.draggable=true;
      const label=document.createElement('label');label.className='popup-dictionary-label';
      const name=document.createElement('span');name.textContent=dictionary.title;
      const input=document.createElement('input');input.type='checkbox';input.checked=(values[key]||[]).includes(dictionary.path);input.dataset.metadataKey=key;input.dataset.path=dictionary.path;
      input.onchange=()=>{const selected=new Set(values[key]||[]);if(input.checked)selected.add(dictionary.path);else selected.delete(dictionary.path);values[key]=[...selected];save(key,values[key]);};
      label.append(name,input);row.append(label);
      const moves=document.createElement('div');moves.className='popup-order-buttons';
      for(const [text,direction] of [['↑',-1],['↓',1]]){
        const button=document.createElement('button');button.textContent=text;button.title=direction<0?'Move up':'Move down';button.setAttribute('aria-label',button.title+' — '+dictionary.title);
        button.onclick=()=>{if(direction<0&&row.previousElementSibling)list.insertBefore(row,row.previousElementSibling);if(direction>0&&row.nextElementSibling)list.insertBefore(row.nextElementSibling,row);persist();};moves.append(button);
      }
      row.append(moves);list.append(row);
      row.ondragstart=event=>{dragging=row;event.dataTransfer.setData('text/plain',dictionary.path);};
      row.ondragover=event=>{if(dragging&&dragging!==row)event.preventDefault();};
      row.ondrop=event=>{event.preventDefault();if(dragging&&dragging!==row){list.insertBefore(dragging,event.clientY>row.getBoundingClientRect().top+row.offsetHeight/2?row.nextSibling:row);persist();}};
      row.ondragend=()=>dragging=null;
    }
    area.append(group);
  }
}
let scannerConfig = {};
let scanHotkeyListening=false;
let cancelScanHotkeyCapture=()=>{};
function setPopupPreferences(values) { Object.assign(settingsSectionState,values.section_states||{});scannerConfig = values; window.dispatchEvent(new Event('popup-preferences')); }
function showPopupSettings(values, dictionaries) {
  clearTimeout(timer); closeSettings(); showSettings(motion);
  setPopupPreferences(values);
  const area=document.getElementById('inline-settings');area.replaceChildren();
  area.dataset.page='popup';
  const back=document.createElement('button');back.textContent='← Dictionaries';back.onclick=()=>app.dictionaries();const navigation=document.createElement('div');navigation.className='settings-navigation';navigation.append(back,dictionaryBackButton());area.append(navigation);
  const title=document.createElement('h2');title.textContent='Popup settings';area.append(title);
  function section(title){const h=document.createElement('h3');h.textContent=title;area.append(h);}
  function save(key,value){scannerConfig[key]=value;app.popup_preference(key,JSON.stringify(value));}
  function row(title,key,type,min,max){
    const label=document.createElement('label');label.className='settings-row settings-'+type;
    const caption=document.createElement('span');caption.textContent=title;label.append(caption);
    const input=document.createElement('input');input.type=type;input.value=values[key]??'';input.checked=!!values[key];input.id='popup-'+key;
    if(type==='color')connectColorPicker(input,'popup');
    if(min!==undefined){input.min=min;input.max=max;}
    input.onchange=()=>{if(!input.checkValidity())return;save(key,type==='checkbox'?input.checked:['number','range'].includes(type)?Number(input.value):input.value);};
    label.append(input);if(type==='range'){const output=document.createElement('span');output.textContent=input.value+'%';input.oninput=()=>{output.textContent=input.value+'%';save(key,Number(input.value));};label.append(output);}area.append(label);return input;
  }
  section('Scanning');
  row('Enable hover scanning','enabled','checkbox');
  const hotkeyRow=document.createElement('div');hotkeyRow.className='settings-row';
  const hotkeyLabel=document.createElement('span');hotkeyLabel.textContent='Scan input';
  const hotkeyButtons=document.createElement('div');hotkeyButtons.className='settings-source-buttons';
  const record=document.createElement('button');record.id='popup-hotkey-record';
  const clear=document.createElement('button');clear.textContent='Clear';
  const display=()=>{record.textContent=scannerConfig.scan_hotkey?.length?scannerConfig.scan_hotkey.map(key=>key.replace('Control','Ctrl').replace(/^Key/,'').replace(/^Digit/,'').replace('Mouse0','Left mouse').replace('Mouse1','Middle mouse').replace('Mouse2','Right mouse').replace('Mouse3','Mouse back').replace('Mouse4','Mouse forward')).join(' + '):'Hover';};
  display();
  record.onclick=()=>{
    cancelScanHotkeyCapture();scanHotkeyListening=true;record.textContent='Press a key or mouse button…';
    let captured=[];
    const normalized=event=>['Shift','Control','Alt','Meta'].includes(event.key)?event.key:event.code;
    const cleanup=()=>{document.removeEventListener('keydown',down,true);document.removeEventListener('keyup',up,true);document.removeEventListener('mousedown',mouse,true);document.removeEventListener('contextmenu',block,true);window.removeEventListener('blur',cancel);scanHotkeyListening=false;display();};
    const cancel=()=>cleanup();
    const commit=()=>{save('scan_hotkey',captured);cleanup();};
    const down=event=>{
      event.preventDefault();event.stopImmediatePropagation();
      if(event.key==='Escape'){cleanup();return;}
      captured=['Control','Alt','Shift','Meta'].filter(key=>event.getModifierState(key));
      const key=normalized(event);if(!captured.includes(key))captured.push(key);
      if(!['Shift','Control','Alt','Meta'].includes(key))commit();
    };
    const block=event=>{event.preventDefault();event.stopImmediatePropagation();};
    const mouse=event=>{block(event);captured=['Control','Alt','Shift','Meta'].filter(key=>event.getModifierState(key));captured.push('Mouse'+event.button);const button=event.button;const followup=next=>{if(next.button===button)block(next);};for(const type of ['click','auxclick','mouseup','contextmenu'])document.addEventListener(type,followup,true);setTimeout(()=>{for(const type of ['click','auxclick','mouseup','contextmenu'])document.removeEventListener(type,followup,true);},500);commit();};
    const up=event=>{event.preventDefault();event.stopImmediatePropagation();if(captured.length)commit();};
    cancelScanHotkeyCapture=cleanup;
    document.addEventListener('keydown',down,true);document.addEventListener('keyup',up,true);document.addEventListener('mousedown',mouse,true);document.addEventListener('contextmenu',block,true);window.addEventListener('blur',cancel);
  };
  clear.onclick=()=>{cancelScanHotkeyCapture();save('scan_hotkey',[]);display();};
  hotkeyButtons.append(record,clear);hotkeyRow.append(hotkeyLabel,hotkeyButtons);area.append(hotkeyRow);
  row('Scan delay (ms)','scan_delay','number',0,2000);row('Scan length (characters)','scan_length','number',1,48);
  section('Popup');row('Background color','background_color','color');row('Opacity (%)','opacity','range',0,100);row('Width (px)','popup_width','number',280,1200);row('Height (px)','popup_height','number',180,1000);
  appendMetadataSelectors(area,values,dictionaries,'',save);
  section('Dictionaries');
  const dictionaryOptions=document.createElement('div');dictionaryOptions.id='popup-dictionary-options';
  area.append(dictionaryOptions);
  const actions=document.createElement('div');actions.className='settings-source-buttons';dictionaryOptions.append(actions);
  const list=document.createElement('div');list.id='popup-dictionary-list';dictionaryOptions.append(list);
  const order=new Map((values.dictionary_order||[]).map((path,index)=>[path,index]));
  dictionaries.sort((a,b)=>(order.get(a.path)??order.size)-(order.get(b.path)??order.size));
  const toggles=[];
  const persistOrder=()=>save('dictionary_order',[...list.children].map(row=>row.dataset.path));
  let dragging=null;
  for(const dictionary of dictionaries.filter(isWordDictionary)){
    const row=document.createElement('div');row.className='settings-row popup-dictionary-row';row.dataset.path=dictionary.path;row.draggable=true;
    const label=document.createElement('label');label.className='popup-dictionary-label';
    const name=document.createElement('span');name.textContent=dictionary.title;
    const input=document.createElement('input');input.type='checkbox';input.checked=!values.disabled_paths.includes(dictionary.path);
    input.onchange=()=>app.popup_preference('dictionary',JSON.stringify({path:dictionary.path,enabled:input.checked}));
    label.append(name,input);row.append(label);toggles.push(input);
    const moves=document.createElement('div');moves.className='popup-order-buttons';
    for(const [text,direction] of [['↑',-1],['↓',1]]){
      const button=document.createElement('button');button.textContent=text;button.title=direction<0?'Move dictionary up':'Move dictionary down';button.setAttribute('aria-label',button.title+' — '+dictionary.title);
      button.onclick=()=>{if(direction<0&&row.previousElementSibling)list.insertBefore(row,row.previousElementSibling);if(direction>0&&row.nextElementSibling)list.insertBefore(row.nextElementSibling,row);persistOrder();};moves.append(button);
    }
    row.append(moves);list.append(row);
    row.ondragstart=event=>{dragging=row;event.dataTransfer.setData('text/plain',dictionary.path);event.dataTransfer.effectAllowed='move';};
    row.ondragover=event=>{if(dragging&&dragging!==row)event.preventDefault();};
    row.ondrop=event=>{event.preventDefault();if(dragging&&dragging!==row){const after=event.clientY>row.getBoundingClientRect().top+row.offsetHeight/2;list.insertBefore(dragging,after?row.nextSibling:row);persistOrder();}};
    row.ondragend=()=>dragging=null;
  }
  for(const [text,enabled] of [['Enable all',true],['Disable all',false]]){
    const button=document.createElement('button');button.textContent=text;button.onclick=()=>{for(const input of toggles){input.checked=enabled;input.onchange();}};actions.append(button);
  }
  appendCharacterSelectors(area,values,dictionaries,false);
  collapseSettingsSections(area,'popup');
}

function showDictionarySettings(values,dictionaries,notice='') {
  clearTimeout(timer);closeSettings();showSettings(motion);
  const area=document.getElementById('inline-settings');area.replaceChildren();area.dataset.page='dictionaries';
  area.append(dictionaryBackButton());
  const title=document.createElement('h2');title.textContent='Dictionaries';area.append(title);
  const navigation=document.createElement('div');navigation.className='settings-source-buttons';
  const popup=document.createElement('button');popup.id='dictionary-popup-settings';popup.textContent='Popup settings';popup.onclick=()=>app.popup_settings();navigation.append(popup);
  const addButton=document.createElement('button');addButton.id='dictionary-add';addButton.textContent='Add dictionaries…';addButton.onclick=()=>app.dictionary_action('add','null');navigation.append(addButton);area.append(navigation);
  const collapse=document.createElement('button');collapse.id='dictionary-collapse-settings';collapse.textContent='Collapse defaults…';collapse.onclick=()=>app.collapse_settings();navigation.append(collapse);
  const status=document.createElement('p');status.className='settings-intro';status.id='dictionary-import-status';status.textContent=notice;status.hidden=!notice;status.setAttribute('role','status');area.append(status);
  appendMetadataSelectors(area,values,dictionaries,'main_', (key,value)=>app.popup_preference(key,JSON.stringify(value)));
  appendCharacterSelectors(area,values,dictionaries,true);
  const label=document.createElement('h3');label.textContent='Dictionaries';area.append(label);
  const actions=document.createElement('div');actions.className='settings-source-buttons';
  function action(text,fn){const button=document.createElement('button');button.textContent=text;button.onclick=fn;actions.append(button);return button;}
  action('Select all',()=>app.dictionary_action('all','true')).id='dictionary-select-all';
  action('Unselect all',()=>app.dictionary_action('all','false')).id='dictionary-unselect-all';area.append(actions);
  const list=document.createElement('div');list.id='main-dictionary-list';area.append(list);
  const persist=()=>{
    const visible=[...list.children].map(row=>Number(row.dataset.id));let index=0;
    const order=dictionaries.map(dictionary=>!isWordDictionary(dictionary)?dictionary.id:visible[index++]);
    app.dictionary_action('order',JSON.stringify(order));
  };
  let dragging=null;
  for(const dictionary of dictionaries.filter(isWordDictionary)){
    const row=document.createElement('div');row.className='settings-row popup-dictionary-row';row.dataset.id=dictionary.id;row.draggable=true;
    const label=document.createElement('label');label.className='popup-dictionary-label';
    const name=document.createElement('span');name.textContent=dictionary.title;name.title=dictionary.path;
    const input=document.createElement('input');input.type='checkbox';input.checked=dictionary.enabled;input.setAttribute('aria-label','Enable '+dictionary.title);
    input.onchange=()=>app.dictionary_action('toggle',JSON.stringify({id:dictionary.id,enabled:input.checked}));label.append(name,input);row.append(label);
    const buttons=document.createElement('div');buttons.className='popup-order-buttons';
    for(const [text,direction] of [['↑',-1],['↓',1]]) {
      const button=document.createElement('button');button.textContent=text;button.title=direction<0?'Move up':'Move down';button.setAttribute('aria-label',button.title+' — '+dictionary.title);
      button.onclick=()=>{if(direction<0&&row.previousElementSibling)list.insertBefore(row,row.previousElementSibling);if(direction>0&&row.nextElementSibling)list.insertBefore(row.nextElementSibling,row);persist();};buttons.append(button);
    }
    const remove=document.createElement('button');remove.textContent='×';remove.title='Remove dictionary';remove.setAttribute('aria-label','Remove '+dictionary.title);remove.onclick=()=>app.dictionary_action('remove',JSON.stringify(dictionary.id));buttons.append(remove);
    row.append(buttons);list.append(row);
    row.ondragstart=event=>{dragging=row;event.dataTransfer.setData('text/plain',String(dictionary.id));};
    row.ondragover=event=>{if(dragging&&dragging!==row)event.preventDefault();};
    row.ondrop=event=>{event.preventDefault();if(dragging&&dragging!==row){list.insertBefore(dragging,event.clientY>row.getBoundingClientRect().top+row.offsetHeight/2?row.nextSibling:row);persist();}};
    row.ondragend=()=>dragging=null;
  }
  collapseSettingsSections(area,'dictionary');
}

function showCollapseSettings(values,dictionaries) {
  clearTimeout(timer);closeSettings();showSettings(motion);
  const area=document.getElementById('inline-settings');area.replaceChildren();area.dataset.page='collapse-defaults';
  const back=document.createElement('button');back.textContent='← Dictionaries';back.onclick=()=>app.dictionaries();
  const navigation=document.createElement('div');navigation.className='settings-navigation';navigation.append(back,dictionaryBackButton());area.append(navigation);
  const heading=document.createElement('h2');heading.textContent='Collapsed by default';area.append(heading);
  const selected=new Set(values.main_collapsed_paths||[]);
  const candidates=dictionaries.filter(isWordDictionary);
  for(const [key,title,enabled] of [['in-use','In use',true],['other','Other dictionaries',false]]){
    const members=candidates.filter(dictionary=>!!dictionary.enabled===enabled);
    if(!enabled&&!members.length)continue;
    const section=document.createElement('section');section.dataset.collapseGroup=key;
    const label=document.createElement('h3');label.textContent=title;section.append(label);
    for(const dictionary of members){
      const row=document.createElement('label');row.className='settings-row';row.dataset.collapsePath=dictionary.path;
      const name=document.createElement('span');name.textContent=dictionary.title;
      const input=document.createElement('input');input.type='checkbox';input.checked=selected.has(dictionary.path);input.setAttribute('aria-label','Collapse '+dictionary.title+' by default');
      input.onchange=()=>{if(input.checked)selected.add(dictionary.path);else selected.delete(dictionary.path);app.popup_preference('main_collapsed_paths',JSON.stringify([...selected]));};
      row.append(name,input);section.append(row);
    }
    area.append(section);
  }
}
function updateDictionarySettings(values,dictionaries,notice) {
  const collapseArea=document.querySelector('#inline-settings[data-page=collapse-defaults]');
  if(collapseArea){const scroll=collapseArea.scrollTop;showCollapseSettings(values,dictionaries);document.getElementById('inline-settings').scrollTop=scroll;return;}
  const area=document.querySelector('#inline-settings[data-page=dictionaries]');if(!area)return;
  const scroll=area.scrollTop;const expanded=[...area.querySelectorAll('details')].map(group=>group.open);
  showDictionarySettings(values,dictionaries,notice);
  const next=document.getElementById('inline-settings');next.querySelectorAll('details').forEach((group,index)=>group.open=expanded[index]??true);next.scrollTop=scroll;
}
