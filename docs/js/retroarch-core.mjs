// Independently implemented from Delta skin metadata and RetroArch's overlay format.
const buttons = {a:'a',b:'b',x:'x',y:'y',l:'l',r:'r',l2:'l2',r2:'r2',start:'start',select:'select',up:'up',down:'down',left:'left',right:'right',menu:'menu_toggle',z:'l2',cUp:'r_y_minus',cDown:'r_y_plus',cLeft:'r_x_minus',cRight:'r_x_plus'};
export function layouts(info) {
  const out=[];
  for(const [device, displays] of Object.entries(info.representations||{})) {
    if(!['iphone','ipad','tv','appletv'].includes(device)) continue;
    for(const [display, orientations] of Object.entries(displays))
      for(const orientation of ['portrait','landscape']) {
        const data=orientations[orientation];
        if(data?.mappingSize?.width>0 && data.mappingSize.height>0)
          out.push({device,display,orientation,data,label:`${device === 'iphone'?'iPhone':device === 'ipad'?'iPad':'Apple TV'} · ${display} · ${orientation}`});
      }
  }
  return out;
}
export function config(layout, warnings=new Set()) {
  const {width,height}=layout.data.mappingSize;
  const lines=['overlays = 1','overlay0_overlay = "overlay.png"','overlay0_full_screen = true','overlay0_normalized = true',`overlay0_aspect_ratio = ${width/height}`];
  const desc=[];
  for(const item of layout.data.items||[]) {
    const f=item.frame, input=item.inputs;
    if(!f || !(f.width>0 && f.height>0)) continue;
    let action;
    if(Array.isArray(input)) {
      const mapped=input.map(k=>buttons[k]);
      if(mapped.some(k=>!k)) warnings.add('Some controls cannot be mapped to RetroArch and were omitted.');
      action=mapped.filter(Boolean).join('|');
    } else if(input && typeof input==='object') {
      const values=Object.values(input);
      if(values.some(v=>String(v).startsWith('analogStick'))) action='analog_left';
      else if(['up','down','left','right'].every(k=>input[k]===k)) action='dpad_area';
      else warnings.add('Touchscreen or custom directional controls require manual setup and were omitted.');
    }
    if(!action) continue;
    desc.push(`overlay0_desc${desc.length} = "${action},${(f.x+f.width/2)/width},${(f.y+f.height/2)/height},rect,${f.width/2/width},${f.height/2/height}"`);
  }
  return [...lines,`overlay0_descs = ${desc.length}`,...desc,''].join('\n');
}
export function parseInfo(text) {
  // Preserve strings (including URLs) while stripping comments and trailing commas.
  return JSON.parse(text.replace(/"(?:\\.|[^"\\])*"|\/\/[^\n\r]*|\/\*[\s\S]*?\*\//g,m=>m.startsWith('"')?m:'').replace(/"(?:\\.|[^"\\])*"|,\s*(?=[}\]])/g,m=>m.startsWith('"')?m:''));
}
