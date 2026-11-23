// Estimate the visible tint over the default dark underlay. Transparent desktop content
// is painted by the compositor and cannot be sampled by this web page.
function contrastLuminance(rgb) {
  const linear=rgb.map(value=>{const c=value/255;return c<=.04045?c/12.92:Math.pow((c+.055)/1.055,2.4);});
  return linear[0]*.2126+linear[1]*.7152+linear[2]*.0722;
}
function contrastRatio(a,b) {
  const x=contrastLuminance(a),y=contrastLuminance(b);
  return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
}
function contrastRGB(hex) {return [1,3,5].map(index=>parseInt(hex.slice(index,index+2),16));}
function readableColor(hex,background) {
  const original=contrastRGB(hex);
  if(contrastRatio(original,background)>=4.5)return hex;
  const target=contrastRatio([0,0,0],background)>contrastRatio([255,255,255],background)?0:255;
  for(let amount=.01;amount<=1.001;amount+=.01){
    const mixed=original.map(value=>Math.round(value*(1-amount)+target*amount));
    if(contrastRatio(mixed,background)>=4.5)return 'rgb('+mixed.join(',')+')';
  }
  return target===0?'#000000':'#ffffff';
}
function textContrastPalette(color,opacity=100) {
  const rgb=contrastRGB(color),alpha=Math.max(0,Math.min(1,opacity/100));
  const background=rgb.map(value=>Math.round(value*alpha+32*(1-alpha)));
  const light=contrastRatio([0,0,0],background)>contrastRatio([255,255,255],background);
  const palette=light?{text:'#17202a',muted:'#465365',accent:'#812c7a'}:{text:'#f3f0f7',muted:'#adb5c8',accent:'#dba6d9'};
  for(const key of ['text','muted','accent'])palette[key]=readableColor(palette[key],background);
  palette.line=light?'rgba(25,35,45,.23)':'rgba(210,215,240,.16)';
  palette.scheme=light?'light':'dark';
  return palette;
}
function applyTextContrast(color) {
  const root=document.documentElement;
  const mode=motion.text_color_mode||'automatic';
  const automatic=mode==='automatic';
  // Recompute on every application, including switching back from a manual color.
  const palette=automatic?textContrastPalette(color,motion.panel_darkness??100):mode==='black'?{
    text:'#000000',muted:'#000000',accent:'#000000',line:'rgba(25,35,45,.23)',scheme:'light'
  }:{
    text:'#ffffff',muted:'#ffffff',accent:'#ffffff',line:'rgba(210,215,240,.16)',scheme:'dark'
  };
  for(const key of ['text','muted','accent','line'])root.style.setProperty('--'+key,palette[key]);
  root.dataset.contrastScheme=palette.scheme;
  root.dataset.automaticContrast=String(automatic);
}
if(typeof module!=='undefined'&&module.exports)module.exports={contrastLuminance,contrastRatio,textContrastPalette};
