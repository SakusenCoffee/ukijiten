/* Native app scanner. No extension code, browser process, or external service. */
(()=>{
const held=new Set();let hoverTimer=null,lastText='',lastPointer=null,sequence=0;
const normalize=event=>['Shift','Control','Alt','Meta'].includes(event.key)?event.key:event.code;
const modifiers=event=>{
 for(const key of ['Shift','Control','Alt','Meta']){if(event.getModifierState(key))held.add(key);else held.delete(key);}
 if(typeof event.buttons==='number')for(const [button,mask] of [[0,1],[1,4],[2,2],[3,8],[4,16]]){
  if(event.buttons&mask)held.add('Mouse'+button);else held.delete('Mouse'+button);
 }
};
const active=()=>!(scannerConfig.scan_hotkey||[]).some(key=>!held.has(key));
const enabled=()=>scannerConfig.enabled&&!document.getElementById('inline-settings');
const hide=()=>{clearTimeout(hoverTimer);lastText='';sequence++;if(app)app.hide_hover();};
function characterAtPoint(entry,x,y){
 const caret=document.caretRangeFromPoint(x,y);
 if(!caret||caret.startContainer.nodeType!==Node.TEXT_NODE||!entry.contains(caret.startContainer))return null;
 const node=caret.startContainer,offset=caret.startOffset,candidates=[];
 function add(text,start){
  if(start<0||start>=text.length)return;
  if(start>0&&/[\uDC00-\uDFFF]/.test(text.data[start]))start--;
  const end=start+(text.data.codePointAt(start)>0xFFFF?2:1);
  candidates.push({node:text,start,end});
 }
 // Caret hit testing returns the nearest insertion point, which may be AFTER
 // the glyph under the pointer. Check the visible rectangles on either side.
 add(node,offset);add(node,offset-1);
 const walker=document.createTreeWalker(entry,NodeFilter.SHOW_TEXT);walker.currentNode=node;
 if(offset===0){const previous=walker.previousNode();if(previous)add(previous,previous.length-1);}
 walker.currentNode=node;
 if(offset===node.length){const next=walker.nextNode();if(next)add(next,0);}
 for(const candidate of candidates){
  const range=document.createRange();range.setStart(candidate.node,candidate.start);range.setEnd(candidate.node,candidate.end);
  for(const rect of range.getClientRects())if(x>=rect.left&&x<rect.right&&y>=rect.top&&y<rect.bottom)return candidate;
 }
 return null;
}
function scan(event){
 if(!enabled()||!active()||!event.target.closest('.entry')||event.target.closest('a,button,input'))return;
 const entry=event.target.closest('.entry'),hit=characterAtPoint(entry,event.clientX,event.clientY);
 if(!hit)return;
 const content=document.createRange();content.selectNodeContents(entry);content.setStart(hit.node,hit.start);
 const text=Array.from(content.toString()).slice(0,scannerConfig.scan_length||24).join('').split(/[\s。、！？「」『』（）()]/)[0];
 if(!text||!/^([\p{L}\p{N}])/u.test(text))return;
 if(text===lastText)return;lastText=text;clearTimeout(hoverTimer);const token=++sequence;
 hoverTimer=setTimeout(()=>{
  if(token!==sequence||!active()||!enabled()||!app)return;
  const chars=Array.from(text),candidates=[];
  for(let length=chars.length;length>0;length--)candidates.push({text:chars.slice(0,length).join(''),length});
  app.hover_lookup(JSON.stringify(candidates),Math.round(event.clientX),Math.round(event.clientY));
 },scannerConfig.scan_delay??60);
}
window.popupScanConsumes=event=>enabled()&&!!lastPointer&&(scannerConfig.scan_hotkey||[]).includes(normalize(event))&&(scannerConfig.scan_hotkey||[]).every(key=>key===normalize(event)||held.has(key)||(['Shift','Control','Alt','Meta'].includes(key)&&event.getModifierState(key)));
document.getElementById('lookup-area').addEventListener('pointermove',event=>{
 modifiers(event);lastPointer=event;scan(event);
});
document.addEventListener('pointerdown',event=>{
 if(scanHotkeyListening)return;
 const scanning=enabled()&&event.target.closest('.entry')&&(scannerConfig.scan_hotkey||[]).includes('Mouse'+event.button);
 if(!scanning&&app)app.outside_popup_click();
},true);
document.getElementById('lookup-area').addEventListener('pointerdown',event=>{
 if(!enabled())return;
 modifiers(event);held.add('Mouse'+event.button);lastPointer=event;
 if((scannerConfig.scan_hotkey||[]).includes('Mouse'+event.button)&&active()){
  event.preventDefault();scan(event);
 }
},true);
document.addEventListener('pointerup',event=>held.delete('Mouse'+event.button),true);
for(const type of ['mouseup','auxclick'])document.getElementById('lookup-area').addEventListener(type,event=>{if(enabled()&&(scannerConfig.scan_hotkey||[]).includes('Mouse'+event.button)&&event.button>=3)event.preventDefault();},true);
document.getElementById('lookup-area').addEventListener('contextmenu',event=>{if(enabled()&&(scannerConfig.scan_hotkey||[]).includes('Mouse2'))event.preventDefault();});
document.addEventListener('keydown',event=>{
 if(scanHotkeyListening||!enabled())return;
 modifiers(event);held.add(normalize(event));
 if(event.key==='Escape'){hide();return;}
 if(window.popupScanConsumes(event)&&active()){event.preventDefault();event.stopImmediatePropagation();scan(lastPointer);}
},true);
document.addEventListener('keyup',event=>held.delete(normalize(event)),true);
document.getElementById('lookup-area').addEventListener('pointerleave',()=>{lastPointer=null;hide();});
document.getElementById('lookup-area').addEventListener('scroll',hide,{passive:true,capture:true});
window.releasePopupScanKey=key=>held.delete(key);
window.clearPopupScanKeys=()=>held.clear();
window.resetPopupScan=()=>{clearTimeout(hoverTimer);lastText='';sequence++;};
window.addEventListener('popup-preferences',()=>{lastText='';clearTimeout(hoverTimer);});
})();
