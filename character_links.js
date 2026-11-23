function bindCharacterLinks(root, fromPopup=false) {
  root.addEventListener('click',event=>{
    const link=event.target.closest('a[data-character]');
    if(!link||!app||event.button!==0||event.ctrlKey||event.metaKey)return;
    const selection=window.getSelection();
    if(selection.toString()&&selection.containsNode(link,true))return;
    event.preventDefault();event.stopPropagation();
    app.kanji_lookup(link.dataset.character,Math.round(event.clientX),Math.round(event.clientY),fromPopup);
  });
}
