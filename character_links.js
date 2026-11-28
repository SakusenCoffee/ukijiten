function bindCharacterLinks(root, fromPopup=false) {
  root.addEventListener('click',event=>{
    const link=event.target.closest('a[data-character]');
    if(!link||!app||event.button!==0||event.ctrlKey||event.metaKey)return;
    const selection=window.getSelection();
    if(selection.toString()&&selection.containsNode(link,true))return;
    event.preventDefault();event.stopPropagation();
    const kind='character',data={character:link.dataset.character};
    if(fromPopup)app.detail_from_popup(kind,JSON.stringify(data));
    else openLookupDetail(Number(link.closest('[data-lookup-id]')?.dataset.lookupId||0),kind,data);
  });
}
