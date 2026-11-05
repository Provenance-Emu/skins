// Browser flow test for docs/retroarch.html in Chromium and WebKit: catalog lookup and fetch, the
// download-then-drop fallback for hosts that block cross-site reads, PNG and PDF artwork, and that the
// zip follows the selected device. Expects the site served at BASE (CI: python3 -m http.server on docs/).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium, webkit } = require("playwright");
const { zipSync, unzipSync, strToU8, strFromU8 } = require("fflate");

const BASE = process.env.BASE_URL || "http://localhost:8765";
const layout = { mappingSize: { width: 100, height: 100 }, assets: { resizable: "art.png" },
  items: [{ frame: { x: 10, y: 10, width: 20, height: 20 }, inputs: ["a"] }] };
const info = { name: "Flow Test", identifier: "com.example.flowtest", gameTypeIdentifier: "com.rileytestut.delta.game.gba",
  representations: { iphone: { edgeToEdge: { portrait: layout } }, ipad: { standard: { landscape: layout } },
    tv: { standard: { landscape: layout } } } };
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=", "base64");
const skin = Buffer.from(zipSync({ "info.json": strToU8(JSON.stringify(info)), "art.png": png }));

const pdf = "%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n" +
  "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Resources << >> >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF";
const pdfInfo = structuredClone(info);
for (const device of Object.values(pdfInfo.representations))
  for (const display of Object.values(device)) for (const l of Object.values(display)) l.assets = { resizable: "art.pdf" };
const pdfSkin = Buffer.from(zipSync({ "info.json": strToU8(JSON.stringify(pdfInfo)), "art.pdf": strToU8(pdf) }));

const catalog = { skins: [
  { id: "open", name: "Open host", downloadURL: "https://skins.test.invalid/flow.deltaskin" },
  { id: "blocked", name: "Blocked host", downloadURL: "https://deltastyles.com/files/skins/1/flow.deltaskin" },
] };

/** Waits for a finished render, downloads the zip and returns its files by base name. */
async function download(page) {
  await page.waitForFunction(() => !document.getElementById("ra-download").disabled);
  const [file] = await Promise.all([page.waitForEvent("download"), page.click("#ra-download")]);
  const zip = unzipSync(fs.readFileSync(await file.path()));
  return Object.fromEntries(Object.entries(zip).map(([name, data]) => [name.split("/").pop(), data]));
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  const page = await browser.newPage({ acceptDownloads: true });
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.route("**/catalog.min.json", r => r.fulfill({ json: catalog }));
  await page.route("https://skins.test.invalid/**", r =>
    r.fulfill({ body: skin, headers: { "access-control-allow-origin": "*", "content-type": "application/zip" } }));

  // ?skin= looks the skin up in the catalog and fetches it.
  await page.goto(`${BASE}/retroarch.html?skin=open`);
  await page.locator("#ra-result").waitFor({ state: "visible" });
  assert.deepEqual((await page.locator("#ra-device option").allTextContents()).length, 3, `${name}: three devices`);
  let files = await download(page);
  const cfgName = Object.keys(files).find(f => f.endsWith(".cfg"));
  assert.ok(cfgName && strFromU8(files[cfgName]).includes("overlay0_descs"), `${name}: cfg has descriptors`);
  assert.ok(files["README.txt"], `${name}: README in the zip`);
  assert.ok(Object.keys(files).some(f => f.endsWith(".png")), `${name}: rendered PNG in the zip`);
  assert.match(strFromU8(files[cfgName]), /# Layouts: iphone, portrait/, `${name}: iPhone layout by default`);

  // Switching device converts again, and the zip follows the new choice.
  await page.selectOption("#ra-device", "tv");
  files = await download(page);
  const tvCfg = Object.keys(files).find(f => f.endsWith(".cfg"));
  assert.match(tvCfg, /-tv\.cfg$/, `${name}: the zip is named for the TV`);
  assert.match(strFromU8(files[tvCfg]), /# Layouts: tv, landscape/, `${name}: the TV layout was converted`);

  // A host that blocks cross-site reads gets the two-step message; dropping the file converts it.
  await page.goto(`${BASE}/retroarch.html?skin=blocked`);
  await page.waitForFunction(() => document.getElementById("ra-status").textContent.includes("Two steps"));
  await page.setInputFiles("#ra-file", { name: "flow.deltaskin", mimeType: "application/zip", buffer: skin });
  await download(page);

  // A fetch that fails outright falls back the same way.
  await page.unroute("https://skins.test.invalid/**");
  await page.route("https://skins.test.invalid/**", r => r.abort());
  await page.goto(`${BASE}/retroarch.html?skin=open`);
  await page.waitForFunction(() => document.getElementById("ra-status").textContent.includes("Two steps"));

  // PDF artwork renders through pdf.js.
  await page.setInputFiles("#ra-file", { name: "pdf.manicskin", mimeType: "application/zip", buffer: pdfSkin });
  files = await download(page);
  assert.ok(Object.keys(files).some(f => f.endsWith(".png")), `${name}: PDF rendered to PNG`);
  assert.ok(!(await page.locator("#ra-render-error").isVisible()), `${name}: no render errors`);

  assert.deepEqual(errors, [], `${name}: no page errors`);
  await browser.close();
  console.log(`${name}: ok`);
}

(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine);
})().catch(e => { console.error(e); process.exit(1); });
