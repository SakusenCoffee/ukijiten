let searchHistoryPopup=null,searchHistoryAnchor=null,searchHistoryPane=0,searchHistoryOldest=false,searchHistoryRequest=0;
const searchHistoryIcon='<svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="9" r="5.5"/><path d="m13 13 4 4m1-9 2 3 2-3"/></svg>';
function closeSearchHistory(){
  searchHistoryRequest++;
  searchHistoryPopup?.remove();searchHistoryPopup=null;
  searchHistoryAnchor?.setAttribute('aria-expanded','false');searchHistoryAnchor=null;
}
function openSearchHistory(pane,anchor){
  if(searchHistoryAnchor===anchor){closeSearchHistory();return;}
  closeSearchHistory();showPanel();searchHistoryPane=pane;searchHistoryAnchor=anchor;
  anchor.setAttribute('aria-expanded','true');
  const popup=document.createElement('div');popup.className='search-history-popup';popup.setAttribute('role','dialog');popup.setAttribute('aria-label','Search history');
  const sort=document.createElement('button');sort.type='button';sort.className='search-history-sort';
  const list=document.createElement('div');list.className='search-history-list';
  const load=()=>{
    sort.textContent=searchHistoryOldest?'↑ Oldest first':'↓ Newest first';
    const request=++searchHistoryRequest;
    app.search_history(searchHistoryOldest,response=>{
      if(request!==searchHistoryRequest||searchHistoryPopup!==popup)return;
      const rows=JSON.parse(response);list.replaceChildren();list.scrollTop=0;let shown=0;
      const append=()=>{
        for(const row of rows.slice(shown,shown+60)){
          const item=document.createElement('button');item.type='button';item.className='search-history-entry';item.textContent=row.headword;
          item.title=row.query+' · '+new Date(row.searched).toLocaleString();
          item.onclick=()=>{
            const cell=lookupCells.get(searchHistoryPane);closeSearchHistory();if(!cell)return;
            cell.input.value=row.query;cell.clear.hidden=false;submitLookup(Number(cell.root.dataset.lookupId));cell.input.focus();
          };
          list.append(item);
        }
        shown+=60;
      };
      if(rows.length)append();else{const empty=document.createElement('p');empty.textContent='No search history';list.append(empty);}
      list.onscroll=()=>{if(shown<rows.length&&list.scrollHeight-list.scrollTop-list.clientHeight<60)append();};
    });
  };
  sort.onclick=()=>{searchHistoryOldest=!searchHistoryOldest;load();};popup.append(sort,list);panel.append(popup);searchHistoryPopup=popup;
  const bounds=panel.getBoundingClientRect(),position=anchor.getBoundingClientRect();
  popup.style.left=Math.max(8,Math.min(position.left-bounds.left,bounds.width-Math.min(300,bounds.width-16)-8))+'px';
  popup.style.top=Math.min(position.bottom-bounds.top+5,bounds.height-80)+'px';
  popup.style.maxHeight=Math.max(60,bounds.bottom-position.bottom-16)+'px';load();
}
document.addEventListener('pointerdown',event=>{if(searchHistoryPopup&&!searchHistoryPopup.contains(event.target)&&!searchHistoryAnchor.contains(event.target))closeSearchHistory();},true);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&searchHistoryPopup){const anchor=searchHistoryAnchor;closeSearchHistory();anchor.focus();event.preventDefault();event.stopImmediatePropagation();}},true);
window.addEventListener('resize',closeSearchHistory);
window.addEventListener('blur',closeSearchHistory);
