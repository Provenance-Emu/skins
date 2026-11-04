const {chromium,webkit}=require('playwright');
const fs=require('fs');
const {pathToFileURL}=require('url');
const path=require('path');
(async()=>{
 const {zipSync,strToU8,unzipSync,strFromU8}=await import(pathToFileURL(path.resolve(__dirname,'../../docs/js/vendor/fflate.mjs')).href);
 const data={mappingSize:{width:100,height:100},assets:{resizable:'art.png'},items:[{frame:{x:10,y:10,width:20,height:20},inputs:['a']}]};
 const info={representations:{iphone:{edgeToEdge:{portrait:data}},ipad:{standard:{landscape:data}},tv:{standard:{landscape:data}}}};
 const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=','base64');
 const skin=zipSync({'info.json':strToU8(JSON.stringify(info)),'art.png':png});
 for(const [name,engine] of Object.entries({chromium,webkit})){
  const browser=await engine.launch({headless:true}); const page=await browser.newPage();
  page.on('pageerror',e=>console.log(name,'PAGEERROR',e.message));
  await page.route('**/catalog.json',r=>r.fulfill({json:{skins:[{id:'test',name:'Test skin',downloadURL:'https://test.invalid/skin.deltaskin'}]}}));
  await page.route('https://test.invalid/**',r=>r.fulfill({body:Buffer.from(skin),headers:{'access-control-allow-origin':'*'}}));
  await page.goto('http://localhost:8765/convert.html?skin=test');
  await page.locator('#convert').waitFor(); await page.waitForFunction(()=>!document.querySelector('#convert').disabled);
  console.log(name,'automatic load',await page.locator('#layout option').allTextContents());
  for(let i=0;i<3;i++){
    await page.selectOption('#layout',String(i));
    if(!await page.locator('#result').isHidden()) throw Error('Previous layout download remains visible'); await page.click('#convert'); await page.waitForFunction(()=>!document.querySelector('#result').hidden);
    const [download]=await Promise.all([page.waitForEvent('download'),page.click('#result')]);
    const path=await download.path(); const zip=unzipSync(fs.readFileSync(path));
    if(!strFromU8(zip['overlay.cfg']).includes('overlay0_descs = 1')) throw Error('Invalid descriptors');
    console.log(name,'download',download.suggestedFilename(),Object.keys(zip));
  }
  await page.unroute('https://test.invalid/**'); await page.route('https://test.invalid/**',r=>r.abort());
  await page.reload();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Automatic loading was unavailable'));
  await page.setInputFiles('#file',{name:'test.deltaskin',mimeType:'application/zip',buffer:Buffer.from(skin)});
  await page.waitForFunction(()=>!document.querySelector('#convert').disabled); console.log(name,'upload fallback passed');
  const pdf='%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF';
  const pdfData=structuredClone(info);for(const device of Object.values(pdfData.representations))for(const display of Object.values(device))for(const l of Object.values(display))l.assets={resizable:'art.pdf'};
  await page.setInputFiles('#file',{name:'pdf.manicskin',mimeType:'application/zip',buffer:Buffer.from(zipSync({'info.json':strToU8(JSON.stringify(pdfData)),'art.pdf':strToU8(pdf)}))});
  await page.click('#convert');await page.waitForFunction(()=>!document.querySelector('#convert').disabled);
  console.log(name,'PDF',await page.locator('#status').textContent());
  if(await page.locator('#result').isHidden())throw Error('PDF conversion failed');
  await page.setInputFiles('#file',[]);
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
