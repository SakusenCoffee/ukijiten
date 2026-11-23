let kanjiGridPreferences=null,kanjiGridRevision=0;
const kanjiGridPalettes={dark:[[125,48,40],[132,116,43],[46,134,95]],kanjigrid:[[230,46,46],[230,223,46],[46,230,53],[46,230,230]],blue:[[51,69,95],[87,135,191],[158,217,243]]};
function kanjiPreferences(){
  if(!kanjiGridPreferences)kanjiGridPreferences=Object.assign({fields:[],interval:180,show_unseen:true,show_missing:true,show_other:true,tooltips:true,sort:'score',group:'none',deck:'combined',tile_size:30,palette:'dark',text_color:'automatic',options_open:false},readingStats?.kanji_grid_options||ankiInsightsData?.options||{});
  return kanjiGridPreferences;
}
function saveKanjiOption(key,value){
  const preferences=kanjiPreferences();preferences[key]=value;
  app.stats_kanji_preferences(JSON.stringify(preferences),response=>{
    const result=JSON.parse(response);if(result.error){const error=document.getElementById('kanji-grid-error');if(error)error.textContent=result.error;return;}
    if(key==='fields'){resetAnkiInsights();return;}
    if(key==='options_open')return;
    ++kanjiGridRevision;renderAnkiInsights();
  });
}
function kanjiOptionsMarkup(){
  const p=kanjiPreferences();
  const select=(key,label,options)=>`<label>${label}<select data-kanji-option="${key}">${options.map(([value,text])=>`<option value="${value}" ${p[key]===value?'selected':''}>${text}</option>`).join('')}</select></label>`;
  const check=(key,label)=>`<label class="kanji-grid-check"><input type="checkbox" data-kanji-option="${key}" ${p[key]?'checked':''}>${label}</label>`;
  return `<details id="kanji-grid-options" ${p.options_open?'open':''}><summary>Grid options</summary><div class="kanji-grid-option-fields">
    ${select('group','Group by',[['none','Jōyō / other'],['grade','School grade'],['jlpt','JLPT study levels'],['decks','Selected deck']])}
    ${select('sort','Sort by',[['score','Strength'],['unicode','Character'],['seen','Seen card count'],['unseen','Unseen card count'],['original','Reference order']])}
    <label>Strong interval (days)<input type="number" min="1" max="65536" data-kanji-option="interval" value="${p.interval}"></label>
    <label>Tile size (px)<input type="number" min="18" max="60" data-kanji-option="tile_size" value="${p.tile_size}"></label>
    ${select('palette','Colors',[['dark','Muted'],['kanjigrid','Kanji Grid'],['blue','Blue']])}
    ${select('text_color','Tile text',[['automatic','Automatic'],['black','Black'],['white','White']])}
    <label class="kanji-grid-fields">Fields (comma-separated)<input type="text" id="kanji-grid-fields" value="${statsEscape(p.fields.join(', '))}" list="kanji-grid-field-names" placeholder="First field of each note type"><datalist id="kanji-grid-field-names">${(ankiInsightsData.available_fields||[]).map(name=>`<option value="${statsEscape(name)}"></option>`).join('')}</datalist></label>
    ${check('show_missing','Show missing Jōyō')}${check('show_unseen','Show unseen cards')}${check('show_other','Show other kanji')}
    </div><p id="kanji-grid-error" role="alert"></p></details>`;
}
function bindKanjiGridOptions(){
  const deck=document.getElementById('kanji-grid-deck');if(deck)deck.onchange=()=>saveKanjiOption('deck',deck.value);
  const section=document.getElementById('kanji-grid-options');if(!section)return;
  section.ontoggle=()=>{if(section.open!==kanjiPreferences().options_open)saveKanjiOption('options_open',section.open);};
  for(const input of section.querySelectorAll('[data-kanji-option]'))input.onchange=()=>{
    if(!input.checkValidity())return;
    saveKanjiOption(input.dataset.kanjiOption,input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value);
  };
  document.getElementById('kanji-grid-fields').onchange=event=>saveKanjiOption('fields',event.target.value.split(',').map(field=>field.trim()).filter(Boolean));
}
function kanjiTile(cell,p){
  const strength=cell.seen?1-1/Math.pow(1+cell.interval/p.interval,2):0;
  let rgb=cell.missing?[32,38,45]:[67,79,91];
  if(cell.seen){
    const stops=kanjiGridPalettes[p.palette]||kanjiGridPalettes.dark;const at=Math.min(stops.length-1,strength*(stops.length-1));const low=Math.floor(at),high=Math.min(low+1,stops.length-1),fraction=at-low;
    rgb=stops[low].map((value,index)=>Math.round(value*(1-fraction)+stops[high][index]*fraction));
  }
  const foreground=p.text_color==='black'?'#000':p.text_color==='white'?'#fff':contrastRatio([0,0,0],rgb)>contrastRatio([255,255,255],rgb)?'#000':'#fff';
  const title=cell.missing?`${cell.char} · Not in this deck`:`${cell.char} · ${cell.seen} seen cards · ${cell.unseen} unseen · ${cell.interval} days average`;
  return `<span class="anki-kanji-cell ${cell.missing?'is-missing':''}" data-char="${cell.char}" data-status="${cell.missing?'missing':cell.seen?'seen':'unseen'}" style="background:rgb(${rgb.join(',')});color:${foreground}" title="${statsEscape(title)}">${cell.char}</span>`;
}
function kanjiGridMarkup(){
  const data=ankiInsightsData,p=kanjiPreferences(),catalog=data.catalog||{joyo:'',groups:{}};
  const reference=[...catalog.joyo],joyo=new Set(reference);
  const sort=entries=>{
    const result=[...entries];
    if(p.sort==='score')result.sort((a,b)=>b.interval-a.interval||b.seen-a.seen);
    if(p.sort==='unicode')result.sort((a,b)=>a.char.codePointAt(0)-b.char.codePointAt(0));
    if(p.sort==='seen')result.sort((a,b)=>b.seen-a.seen||b.interval-a.interval);
    if(p.sort==='unseen')result.sort((a,b)=>b.unseen-a.unseen||b.seen-a.seen);
    return result;
  };
  const visible=cell=>cell.missing?p.show_missing:cell.seen||p.show_unseen;
  const blocks=group=>{
    const known=new Map(group.kanji.map(cell=>[cell.char,cell]));
    const base=reference.map(char=>known.get(char)||{char,seen:0,unseen:0,interval:0,missing:true});
    const other=group.kanji.filter(cell=>!joyo.has(cell.char));
    const seen=base.filter(cell=>cell.seen).length,present=base.filter(cell=>!cell.missing).length;
    let sets=[];
    if(p.group==='decks')sets=[{name:'Deck kanji',entries:group.kanji.filter(cell=>p.show_other||joyo.has(cell.char))}];
    else if(p.group==='none')sets=[{name:'Jōyō kanji',entries:base},{name:'Other kanji',entries:p.show_other?other:[]}];
    else{
      const entries=[...base,...(p.show_other?other:[])],used=new Set();
      for(const grouping of catalog.groups[p.group]||[]){
        const characters=new Set([...grouping.characters]);
        const selected=entries.filter(cell=>characters.has(cell.char)&&!used.has(cell.char));
        selected.forEach(cell=>used.add(cell.char));sets.push({name:grouping.name,entries:selected});
      }
      sets.push({name:'Other kanji',entries:entries.filter(cell=>!used.has(cell.char))});
    }
    return `<section class="anki-kanji-deck" data-deck="${statsEscape(group.deck)}"><h5>${statsEscape(group===data.combined?'All decks':group.deck)} <span>${statsNumber(seen)} / ${statsNumber(reference.length)} Jōyō seen · ${statsNumber(present)} in deck</span></h5>${group.fields.length?`<p class="anki-insight-note">${group.fields.map(statsEscape).join(' · ')}</p>`:''}${sets.filter(set=>set.entries.some(visible)).map(set=>`<div class="kanji-reference-group" data-kanji-set="${set.name==='Jōyō kanji'?'joyo':set.name==='Deck kanji'?'deck':'other'}"><h6>${statsEscape(set.name)}</h6><div class="anki-kanji-grid" style="--kanji-size:${p.tile_size}px">${sort(set.entries).filter(visible).map(cell=>kanjiTile(cell,p)).join('')}</div></div>`).join('')}</section>`;
  };
  const colors=kanjiGridPalettes[p.palette]||kanjiGridPalettes.dark;
  const selected=data.decks.find(group=>'deck:'+group.deck===p.deck);
  const groups=selected?[selected]:[data.combined];
  const selection=selected?p.deck:'combined';
  const deckSelector=`<div class="anki-graph-filters"><label>Deck <select id="kanji-grid-deck"><option value="combined" ${selection==='combined'?'selected':''}>All decks</option>${data.decks.map(group=>`<option value="${statsEscape('deck:'+group.deck)}" ${selection==='deck:'+group.deck?'selected':''}>${statsEscape(group.deck)}</option>`).join('')}</select></label></div>`;
  return `<div class="anki-insight-heading"><h4>Kanji heatmaps</h4>${deckSelector}</div>${kanjiOptionsMarkup()}<p class="anki-insight-note">${p.group==='decks'?'Deck kanji':statsNumber(reference.length)+' Jōyō kanji'} · average review interval · ${statsNumber(p.interval)}-day color scale</p><div class="anki-kanji-legend"><i style="background:#20262d"></i>Missing <i style="background:#434f5b"></i>Unseen <i style="background:rgb(${colors[0].join(',')})"></i>Short interval <i style="background:rgb(${colors[colors.length-1].join(',')})"></i>Long interval</div>`+groups.map(blocks).join('');
}
