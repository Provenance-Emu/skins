// Browser flow test for docs/retroarch.html in Chromium and WebKit: catalog lookup and fetch, the
// download-then-drop fallback for hosts that block cross-site reads, PNG and PDF artwork, that the
// zip follows the selected device, the install recipe naming the converted folder, the Provenance
// hand-off in its web view, and the "Get for RetroArch" button in the browse modal.
// Expects the site served at BASE (CI: python3 -m http.server on docs/).
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

// What Provenance's web view reports: an iPhone user agent without "Safari/".
const IN_APP_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148";
const SAFARI_UA = IN_APP_UA + " Safari/604.1";

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

/** The install recipe names the folder that was just converted, in every place the player types or picks it. */
async function checkRecipe(page, name, slug) {
  const texts = sel => page.locator(sel).allTextContents();
  for (const t of await texts(".ra-slug")) assert.equal(t, slug, `${name}: recipe folder name`);
  for (const t of await texts(".ra-zip")) assert.equal(t, `${slug}.zip`, `${name}: recipe zip name`);
  for (const t of await texts(".ra-preset")) assert.equal(t, `${slug}/${slug}.cfg`, `${name}: recipe preset path`);
  const snippet = await page.locator("#ra-snippet").textContent();
  assert.ok(snippet.includes(`input_overlay = "~/Documents/RetroArch/overlays/${slug}/${slug}.cfg"`), `${name}: cfg snippet path`);
  assert.ok(snippet.includes('input_overlay_enable = "true"'), `${name}: cfg snippet enables the overlay`);
  const install = await page.locator("#ra-install").innerText();
  assert.match(install, /18 taps/, `${name}: the tap count is on the page`);
  assert.match(install, /Open in RetroArch/, `${name}: says what Open in RetroArch does`);
  assert.match(install, /On My iPhone › RetroArch › RetroArch › overlays/, `${name}: Files path`);
  // The in-app steps and the Send button stay hidden in a browser.
  assert.ok(!(await page.locator("#ra-send").isVisible()), `${name}: no Send button in a browser`);
  assert.ok(!(await page.locator(".ra-app-only").first().isVisible()), `${name}: app-only steps hidden`);
  // The copy buttons are wired: a click gives feedback (the clipboard itself is not readable in every engine).
  const copy = page.locator('.ra-copy[data-copy="#ra-snippet"]');
  await copy.click();
  await page.waitForFunction(() => /Copied|Select it/.test(document.querySelector('.ra-copy[data-copy="#ra-snippet"]').textContent));
}

/** Inside Provenance's web view the page offers the app hand-off instead of a zip. */
async function checkInApp(name, engine) {
  const browser = await engine.launch({ headless: true });
  const context = await browser.newContext({ userAgent: IN_APP_UA, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.route("**/catalog.min.json", r => r.fulfill({ json: catalog }));
  await page.route("https://skins.test.invalid/**", r =>
    r.fulfill({ body: skin, headers: { "access-control-allow-origin": "*", "content-type": "application/zip" } }));
  await page.goto(`${BASE}/retroarch.html?skin=open`);
  await page.locator("#ra-result").waitFor({ state: "visible" });
  const send = page.locator("#ra-send");
  await send.waitFor({ state: "visible" });
  assert.equal(await send.getAttribute("href"), "provenance://skins/retroarch?skin=open", `${name}: in-app hand-off link`);
  assert.ok(!(await page.locator("#ra-download").isVisible()), `${name}: no zip download in the app`);
  assert.ok(await page.locator(".ra-app-only").first().isVisible(), `${name}: in-app step shown`);
  assert.ok(!(await page.locator(".ra-web-only").first().isVisible()), `${name}: Files steps hidden in the app`);
  assert.deepEqual(errors, [], `${name}: no page errors in the app`);
  await browser.close();
}

/** The browse modal's RetroArch button: the converter page in a browser, the app route in Provenance's web view. */
async function checkModal(name, engine) {
  const real = JSON.parse(fs.readFileSync(`${__dirname}/../../docs/catalog.min.json`, "utf8")).skins
    .find(s => !(s.tags || []).includes("mature") && !s.family);
  assert.ok(real, "the real catalog has a plain skin to open");
  const browser = await engine.launch({ headless: true });
  for (const [ua, label, href, text] of [
    [SAFARI_UA, "Safari", `retroarch.html?skin=${real.id}`, "Get for RetroArch"],
    [IN_APP_UA, "app", `provenance://skins/retroarch?skin=${real.id}`, "Send to RetroArch"],
  ]) {
    const context = await browser.newContext({ userAgent: ua, serviceWorkers: "block" });
    // Only the site itself: thumbnails and fonts live elsewhere and are not under test.
    await context.route(url => !url.href.startsWith(BASE), r => r.abort());
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    await page.goto(`${BASE}/index.html?skin=${real.id}`);
    const button = page.locator("#modal-content .modal-actions a", { hasText: "RetroArch" });
    await button.waitFor({ state: "visible" });
    assert.equal(await button.getAttribute("href"), href, `${name}: modal link in ${label}`);
    assert.match(await button.textContent(), new RegExp(text), `${name}: modal label in ${label}`);
    assert.deepEqual(errors, [], `${name}: no page errors in the ${label} modal`);
    await context.close();
  }
  await browser.close();
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
  await checkRecipe(page, name, cfgName.replace(/\.cfg$/, ""));

  // Switching device converts again, and the zip follows the new choice.
  await page.selectOption("#ra-device", "tv");
  files = await download(page);
  const tvCfg = Object.keys(files).find(f => f.endsWith(".cfg"));
  assert.match(tvCfg, /-tv\.cfg$/, `${name}: the zip is named for the TV`);
  assert.match(strFromU8(files[tvCfg]), /# Layouts: tv, landscape/, `${name}: the TV layout was converted`);
  await checkRecipe(page, name, tvCfg.replace(/\.cfg$/, ""));

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
  await checkInApp(name, engine);
  await checkModal(name, engine);
  console.log(`${name}: ok`);
}

(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine);
})().catch(e => { console.error(e); process.exit(1); });
