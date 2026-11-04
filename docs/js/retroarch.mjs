import {unzipSync,zipSync,strToU8,strFromU8} from './vendor/fflate.mjs';
import {layouts,config,parseInfo} from './retroarch-core.mjs';
const $=id=>document.getElementById(id);
let files, choices, resultURL;
const status=text=>{$('status').textContent=text;};
function asset(name) {
  return Object.keys(files).find(k=>k===name)||Object.keys(files).find(k=>k.toLowerCase()===String(name).toLowerCase())||Object.keys(files).find(k=>k.split('/').pop().toLowerCase()===String(name).toLowerCase());
}
async function load(buffer) {
  $('convert').disabled=true; $('layout').disabled=true; $('result').hidden=true;
  if(buffer.byteLength>80*1024*1024) throw Error('This file is too large. Upload a single skin smaller than 80 MB.');
  files=unzipSync(new Uint8Array(buffer));
  const roots=Object.keys(files).filter(k=>/(^|\/)info.json$/.test(k)&&!k.startsWith('__MACOSX/'));
  if(roots.length!==1) throw Error('Upload one skin, rather than a pack of skins.');
  const root=roots[0], prefix=root.slice(0,-9);
  if(prefix) files=Object.fromEntries(Object.entries(files).filter(([k])=>k.startsWith(prefix)).map(([k,v])=>[k.slice(prefix.length),v]));
  choices=layouts(parseInfo(strFromU8(files['info.json'])));
  if(Object.values(files).reduce((n,v)=>n+v.byteLength,0)>160*1024*1024) throw Error('The extracted skin is too large for browser conversion.');
  if(!choices.length) throw Error('This skin has no supported iPhone, iPad or TV layouts.');
  $('layout').replaceChildren(...choices.map((l,i)=>new Option(l.label,i)));
  $('layout').disabled=false; $('convert').disabled=false; status('Choose a layout, then convert.');
}
$('file').onchange=async e=>{
  const file=e.target.files[0];
  if(!file) return;
  try{await load(await file.arrayBuffer());}catch(e){status(e.message);}
};
$('layout').onchange=()=>{
  $('result').hidden=true;
  status('Layout changed. Convert this layout to save its ZIP.');
};
async function render(layout) {
  const d=layout.data, a=d.assets;
  const name=typeof a==='string'?a:a?.resizable||a?.large||a?.medium||a?.small||Object.values(a||{}).find(v=>typeof v==='string');
  const path=asset(name);
  if(!path) throw Error('The artwork for this layout is missing. Choose another layout.');
  if(!Number.isFinite(d.mappingSize.width)||!Number.isFinite(d.mappingSize.height)||Math.min(d.mappingSize.width,d.mappingSize.height)<=0) throw Error('Invalid layout dimensions.');
  const canvas=document.createElement('canvas');
  const scale=Math.min(2,4096/Math.max(d.mappingSize.width,d.mappingSize.height));
  canvas.width=Math.round(d.mappingSize.width*scale);canvas.height=Math.round(d.mappingSize.height*scale);
  const ctx=canvas.getContext('2d');
  if(/\.pdf$/i.test(path)) {
    const pdfjs=await import('./vendor/pdf.mjs');
    pdfjs.GlobalWorkerOptions.workerSrc=new URL('./vendor/pdf.worker.mjs',import.meta.url).href;
    const pdf=await pdfjs.getDocument({data:files[path].slice(),isEvalSupported:false}).promise;
    try {const page=await pdf.getPage(1), base=page.getViewport({scale:1});
      await page.render({canvasContext:ctx,viewport:page.getViewport({scale:1}),transform:[canvas.width/base.width,0,0,canvas.height/base.height,0,0],background:'rgba(0,0,0,0)'}).promise;
    } finally {await pdf.destroy();}
  } else {
    const url=URL.createObjectURL(new Blob([files[path]],{type:/\.svg$/i.test(path)?'image/svg+xml':'image/png'}));
    try {const img=new Image();img.src=url;await img.decode();ctx.drawImage(img,0,0,canvas.width,canvas.height);}finally{URL.revokeObjectURL(url);}
  }
  const screens=d.screens?.map(s=>s.outputFrame)||[d.gameScreenFrame];
  for(const f of screens) if(f) ctx.clearRect(f.x*scale,f.y*scale,f.width*scale,f.height*scale);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));
  if(!blob) throw Error('Could not export this artwork.');
  return new Uint8Array(await blob.arrayBuffer());
}
$('convert').onclick=async()=>{
  $('convert').disabled=true;$('result').hidden=true;status('Converting…');
  try {
    const l=choices[Number($('layout').value)], warnings=new Set();
    const cfg=config(l,warnings), png=await render(l);
    const notes=`EmuSkins RetroArch overlay\nLayout: ${l.label}\nExtract this folder into RetroArch overlays. Select overlay.cfg under Settings > On-Screen Overlay > Overlay Preset.\nGame screen placement must be configured separately. DS screen arrangement and touchscreen input are not converted.\nApple TV: transfer the folder using RetroArch file transfer; use a controller.\n${[...warnings].join('\n')}\n`;
    const zip=zipSync({'overlay.cfg':strToU8(cfg),'overlay.png':png,'README.txt':strToU8(notes)});
    if(resultURL) URL.revokeObjectURL(resultURL);
    resultURL=URL.createObjectURL(new Blob([zip],{type:'application/zip'}));
    $('result').href=resultURL;$('result').download=`retroarch-${l.device}-${l.display}-${l.orientation}.zip`;$('result').hidden=false;
    status('Ready. Tap Save RetroArch ZIP.\n'+[...warnings].join('\n'));
  }catch(e){status(e.message);}finally{$('convert').disabled=false;}
};
const id=new URLSearchParams(location.search).get('skin');
if(id) {
  try {
    const response=await fetch('catalog.json');if(!response.ok) throw Error();
    const catalog=await response.json(), skin=catalog.skins.find(s=>s.id===id);
    if(!skin) throw Error('Skin not found. Upload its file below.');
    $('source').textContent=skin.name;
    const link=document.createElement('a');link.href=skin.downloadURL;link.textContent='Download original skin';link.rel='noopener';$('source').append(' · ',link);
    status('Loading skin…');
    const r=await fetch(skin.downloadURL,{signal:AbortSignal.timeout(30000)});if(!r.ok) throw Error();
    await load(await r.arrayBuffer());
  }catch(e){status('Automatic loading was unavailable. Download the original skin, then upload it above. '+(e.message||''));}
}
