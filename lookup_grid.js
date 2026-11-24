const lookupArea=document.getElementById('lookup-area');
const secondaryQuery=document.getElementById('secondary-query');
const secondaryResults=document.getElementById('secondary-results');
const lookupCells=new Map();
let activeLookup=0,lookupGridSignature='';
let divider=document.getElementById('lookup-divider');

function activeLookupQuery(){return lookupCells.get(activeLookup)?.input||query;}
function submitLookup(id){
  const cell=lookupCells.get(id);if(!cell||!app)return;
  clearTimeout(cell.timer);
  if(id===0)app.search(cell.input.value);
  else if(id===1)app.search_secondary(cell.input.value);
  else app.search_pane(id,cell.input.value);
}
function registerLookupCell(id,root){
  const input=root.querySelector('input'),output=root.querySelector('.results'),clear=root.querySelector('button:not(.search-icon)');
  root.dataset.lookupId=id;
  const cell={id,root,input,output,clear,timer:null,composing:false};lookupCells.set(id,cell);
  const content=document.createElement('div');content.className='lookup-content';
  output.before(content);content.append(output);cell.content=content;
  const close=document.createElement('button');close.type='button';close.className='lookup-close-pane';close.title='Close search pane';close.setAttribute('aria-label','Close search pane');close.hidden=true;
  close.onclick=event=>{event.stopPropagation();closeLookupPane(id);};root.append(close);cell.close=close;
  const history=root.querySelector('.search-icon');
  if(history){history.innerHTML=searchHistoryIcon;history.onclick=()=>openSearchHistory(id,history);}
  input.addEventListener('focus',()=>activeLookup=id);
  if(id===0)return cell;
  input.setAttribute('aria-label','Lookup '+(id+1));
  clear.hidden=!input.value;
  const changed=event=>{
    clear.hidden=!input.value;clearTimeout(cell.timer);showPanel();
    if(cell.composing||event?.isComposing)return;
    for(let i=0;i<input.value.length;i++){
      if(input.value[i]==='\\'){i++;continue;}
      if('*?'.includes(input.value[i]))return;
    }
    cell.timer=setTimeout(()=>submitLookup(id),180);
  };
  input.addEventListener('input',changed);
  input.addEventListener('compositionstart',()=>{cell.composing=true;clearTimeout(cell.timer);});
  input.addEventListener('compositionend',()=>{cell.composing=false;changed();});
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing&&!cell.composing&&event.keyCode!==229)submitLookup(id);});
  clear.onclick=()=>{input.value='';clear.hidden=true;submitLookup(id);input.focus();};
  output.addEventListener('click',event=>{
    const link=event.target.closest('a[href^="?query="]');if(!link)return;
    event.preventDefault();input.value=new URLSearchParams(link.getAttribute('href').slice(1)).get('query')||'';clear.hidden=!input.value;submitLookup(id);
  });
  output.addEventListener('mouseup',event=>{if(!event.target.closest('summary,.dictionary-collapse-defaults')&&!window.getSelection().toString())input.focus({preventScroll:true});});
  return cell;
}
registerLookupCell(0,document.getElementById('primary-lookup'));
registerLookupCell(1,document.getElementById('secondary-lookup'));
lookupArea.addEventListener('pointerdown',event=>{const pane=event.target.closest('[data-lookup-id]');if(pane)activeLookup=Number(pane.dataset.lookupId);});
function createLookupCell(id){
  if(lookupCells.has(id))return lookupCells.get(id);
  const root=document.createElement('section');root.className='lookup-pane';root.id='lookup-pane-'+id;
  root.innerHTML='<div class="searchbar"><button class="search-icon" type="button" title="Search history" aria-label="Search history" aria-haspopup="dialog" aria-expanded="false">⌕</button><input type="text" autocomplete="off"><button type="button" title="Clear search" aria-label="Clear search" hidden>×</button></div><div class="results"></div>';
  return registerLookupCell(id,root);
}
function normalizedLookupWeights(values,count){
  if(!Array.isArray(values)||values.length!==count||values.some(value=>!Number.isFinite(value)||value<=0))return Array(count).fill(1/count);
  const sum=values.reduce((a,b)=>a+b,0);return values.map(value=>value/sum);
}
function applyLookupGrid(){
  const grid=motion.lookup_grid||[[0]],rows=grid.length,columns=grid[0].length;
  motion.lookup_split=grid.flat().filter(id=>id!==null).length>1;
  document.getElementById('lookup-close-extras').hidden=!motion.lookup_split;
  for(const cell of lookupCells.values())cell.close.hidden=!motion.lookup_split;
  motion.lookup_column_weights=normalizedLookupWeights(motion.lookup_column_weights,columns);
  motion.lookup_row_weights=normalizedLookupWeights(motion.lookup_row_weights,rows);
  panel.classList.toggle('lookup-split',motion.lookup_split);
  lookupArea.style.gridTemplateColumns=motion.lookup_column_weights.map(value=>'minmax(140px,'+value+'fr)').join(' 8px ');
  lookupArea.style.gridTemplateRows=motion.lookup_row_weights.map(value=>'minmax(110px,'+value+'fr)').join(' 8px ');
  const signature=JSON.stringify(grid);
  if(signature===lookupGridSignature)return;
  lookupGridSignature=signature;
  const active=document.activeElement,fragment=document.createDocumentFragment(),visible=new Set(grid.flat().filter(id=>id!==null));
  grid.forEach((row,r)=>row.forEach((id,c)=>{
    if(id===null)return;
    const cell=createLookupCell(id);cell.root.hidden=false;cell.root.style.flex='';
    cell.close.hidden=!motion.lookup_split;
    cell.root.style.gridRow=String(r*2+1);cell.root.style.gridColumn=String(c*2+1);fragment.append(cell.root);
  }));
  for(let c=1;c<columns;c++)fragment.append(makeLookupDivider('column',c,grid));
  for(let r=1;r<rows;r++)fragment.append(makeLookupDivider('row',r,grid));
  // Retain the legacy second cell while hidden, preserving its query and DOM references.
  for(const [id,cell] of lookupCells)if(!visible.has(id)){
    clearTimeout(cell.timer);cell.root.hidden=true;
    if(id===0||id===1)fragment.append(cell.root);
    else {cell.root.remove();lookupCells.delete(id);}
  }
  if(columns===1){const hidden=document.createElement('div');hidden.id='lookup-divider';hidden.hidden=true;fragment.append(hidden);}
  lookupArea.replaceChildren(fragment);divider=document.getElementById('lookup-divider');
  if(!visible.has(activeLookup))activeLookup=0;
  if(active?.isConnected&&active.matches('input'))active.focus({preventScroll:true});
  document.getElementById('lookup-split').title='Add a column · '+columns+' '+(columns===1?'column':'columns');
  document.getElementById('lookup-add-row').title='Add a row · '+rows+' '+(rows===1?'row':'rows');
}
function addLookupDimension(axis){
  const grid=motion.lookup_grid.map(row=>[...row]);let next=grid.flat().reduce((highest,id)=>id===null?highest:Math.max(highest,id),-1)+1;
  if(axis==='column'){
    const width=grid[0].length+1;
    grid.forEach((row,index)=>{const cells=row.filter(id=>id!==null);cells.push(next++);while(cells.length<width)cells.push(null);grid[index]=cells;});motion.lookup_column_weights=Array(width).fill(1/width);
  } else {
    grid.push(Array.from({length:grid[0].length},()=>next++));motion.lookup_row_weights=Array(grid.length).fill(1/grid.length);
  }
  motion.lookup_grid=grid;applyLookupGrid();
  if(app){
    app.preference('lookup_grid',JSON.stringify(grid));
    const key=axis==='column'?'lookup_column_weights':'lookup_row_weights';app.preference(key,JSON.stringify(motion[key]));
  }
}
function resetLookupGrid(){
  motion.lookup_grid=[[0]];motion.lookup_column_weights=[1];motion.lookup_row_weights=[1];applyLookupGrid();
  if(app)app.preference('lookup_grid',JSON.stringify(motion.lookup_grid));
}
function closeLookupPane(id){
  if(motion.lookup_grid.flat().filter(cell=>cell!==null).length<=1)return;
  let removed=id;
  if(id===0){
    removed=motion.lookup_grid.flat().find(cell=>cell!==null&&cell!==0);
    const from=lookupCells.get(removed),first=lookupCells.get(0);
    first.input.value=from.input.value;
    const prefix=removed===1?'right-dict-':'pane-'+removed+'-dict-';
    first.output.innerHTML=from.output.innerHTML.replaceAll(prefix,'dict-');
    first.output.scrollTop=from.output.scrollTop;updateClearButton();
    if(app)app.search(first.input.value);
  }
  const closed=lookupCells.get(removed);clearTimeout(closed.timer);closed.input.value='';closed.output.replaceChildren();closed.clear.hidden=true;
  if(removed===1&&app)app.search_secondary('');
  const retained=[];const rowWeights=[];
  motion.lookup_grid.forEach((row,index)=>{
    const cells=row.filter(cell=>cell!==null&&cell!==removed);
    if(cells.length){retained.push(cells);rowWeights.push(motion.lookup_row_weights[index]);}
  });
  const columns=Math.max(...retained.map(row=>row.length));
  retained.forEach(row=>{while(row.length<columns)row.push(null);});
  motion.lookup_grid=retained;motion.lookup_row_weights=rowWeights;activeLookup=0;
  applyLookupGrid();
  if(app)app.preference('lookup_grid',JSON.stringify(retained));
}
function closeExtraLookups(){
  for(const [id,cell] of lookupCells)if(id!==0){clearTimeout(cell.timer);cell.input.value='';cell.output.replaceChildren();cell.clear.hidden=true;}
  if(app)app.search_secondary('');
  resetLookupGrid();activeLookup=0;query.focus({preventScroll:true});
}
function renderPaneResults(id,markup,expectedQuery){
  const cell=lookupCells.get(id);if(!cell||cell.root.hidden||cell.input.value.trim()!==expectedQuery)return;
  const prefix=id===1?'right-dict-':'pane-'+id+'-dict-';
  cell.output.innerHTML=markup.replaceAll('id="dict-','id="'+prefix).replaceAll('href="#dict-','href="#'+prefix);
  cell.output.scrollTop=0;updateDictionaryNavToggle(cell.output);showPanel();
}
function renderSecondaryResults(markup,expectedQuery){renderPaneResults(1,markup,expectedQuery);}
window.addEventListener('resize',()=>{for(const cell of lookupCells.values())if(!cell.root.hidden)updateDictionaryNavToggle(cell.output);});
function makeLookupDivider(axis,index,grid){
  const node=document.createElement('div');node.className='lookup-grid-divider';node.dataset.axis=axis;node.tabIndex=0;
  if(axis==='column'&&index===1)node.id='lookup-divider';
  node.setAttribute('role','separator');node.setAttribute('aria-orientation',axis==='column'?'vertical':'horizontal');
  node.setAttribute('aria-label','Resize lookup '+(axis==='column'?'columns':'rows'));
  node.style.gridColumn=axis==='column'?String(index*2):'1 / -1';node.style.gridRow=axis==='row'?String(index*2):'1 / -1';
  if(axis==='row')grid[index].forEach((cell,column)=>{
    if(cell===null&&grid[index-1][column]===null)return;
    const segment=document.createElement('span');segment.className='lookup-row-segment';segment.style.gridColumn=String(column*2+1);node.append(segment);
  });
  const key=axis==='column'?'lookup_column_weights':'lookup_row_weights';let dragging=null;
  const persist=()=>{if(app)app.preference(key,JSON.stringify(motion[key]));};
  node.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;event.preventDefault();node.setPointerCapture(event.pointerId);
    const row=axis==='column'?grid.find(cells=>cells[index-1]!==null&&cells[index]!==null):null;
    const before=lookupCells.get(axis==='column'?row[index-1]:grid[index-1][0]).root.getBoundingClientRect();
    const after=lookupCells.get(axis==='column'?row[index]:grid[index][0]).root.getBoundingClientRect();
    dragging={start:axis==='column'?event.clientX:event.clientY,before:axis==='column'?before.width:before.height,after:axis==='column'?after.width:after.height,weights:[...motion[key]]};
  });
  node.addEventListener('pointermove',event=>{
    if(!dragging)return;
    const total=dragging.before+dragging.after,min=axis==='column'?140:110;
    const size=Math.max(min,Math.min(total-min,dragging.before+(axis==='column'?event.clientX:event.clientY)-dragging.start));
    const mass=dragging.weights[index-1]+dragging.weights[index];motion[key]=[...dragging.weights];
    motion[key][index-1]=mass*size/total;motion[key][index]=mass*(total-size)/total;applyLookupGrid();
  });
  const finish=()=>{if(dragging){dragging=null;persist();}};
  node.addEventListener('pointerup',finish);node.addEventListener('pointercancel',finish);
  node.addEventListener('keydown',event=>{
    const backward=axis==='column'?'ArrowLeft':'ArrowUp',forward=axis==='column'?'ArrowRight':'ArrowDown';
    if(![backward,forward,'Home'].includes(event.key))return;event.preventDefault();
    const values=[...motion[key]],mass=values[index-1]+values[index];
    const ratio=event.key==='Home'?.5:Math.max(.05,Math.min(.95,values[index-1]/mass+(event.key===forward?.03:-.03)));
    values[index-1]=mass*ratio;values[index]=mass*(1-ratio);motion[key]=values;applyLookupGrid();persist();
  });
  return node;
}
// Compatibility for existing two-column divider shortcuts and saved ratios.
function changeLookupRatio(value){
  motion.lookup_ratio=Math.max(.15,Math.min(.85,value));motion.lookup_column_weights=[motion.lookup_ratio,1-motion.lookup_ratio];applyLookupGrid();
}
document.getElementById('lookup-split').onclick=()=>addLookupDimension('column');
document.getElementById('lookup-add-row').onclick=()=>addLookupDimension('row');
document.getElementById('lookup-close-extras').onclick=closeExtraLookups;
applyLookupLayout();
if(motion.navbar_auto_hide)hideNavbar();
