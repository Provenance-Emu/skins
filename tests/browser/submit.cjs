// Browser flow test for docs/submit.html in Chromium and WebKit: the page's module script reads a skin
// through the shared docs/js/skin/zip.js (info.json one folder down, with the comments the apps ignore)
// and previews its metadata; an archive it cannot read falls back to the "server-side" message.
// Expects the site served at BASE (CI: python3 -m http.server on docs/).
const assert = require("node:assert/strict");
const { chromium, webkit } = require("playwright");
const { zipSync, strToU8 } = require("fflate");

const BASE = process.env.BASE_URL || "http://localhost:8765";
const info = `{
  // Delta ignores comment lines
  "name": "Submit Test", "identifier": "com.example.submittest",
  "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
  "representations": {},
}`;
const skin = Buffer.from(zipSync({ "Submit Test.deltaskin/info.json": strToU8(info) }));
const notZip = Buffer.from("<html>not a skin</html>");
const cors = { "access-control-allow-origin": "*", "content-type": "application/zip" };

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.route("https://skins.test.invalid/good.deltaskin", r => r.fulfill({ body: skin, headers: cors }));
  await page.route("https://skins.test.invalid/bad.deltaskin", r => r.fulfill({ body: notZip, headers: cors }));

  await page.goto(`${BASE}/submit.html`);
  await page.fill("#skin-url", "https://skins.test.invalid/good.deltaskin");
  await page.click("#fetch-btn");
  await page.locator("#preview-box.visible").waitFor();
  const meta = await page.locator("#preview-meta").textContent();
  assert.match(meta, /Submit Test/, `${name}: name read from info.json`);
  assert.match(meta, /Game Boy Advance/, `${name}: system from gameTypeIdentifier`);

  await page.fill("#skin-url", "https://skins.test.invalid/bad.deltaskin");
  await page.click("#fetch-btn");
  await page.waitForFunction(() => document.getElementById("alert-error").textContent.includes("Could not auto-extract"));

  assert.deepEqual(errors, [], `${name}: no page errors`);
  await browser.close();
  console.log(`${name}: ok`);
}

(async () => {
  await run("chromium", chromium);
  await run("webkit", webkit);
})().catch(e => { console.error(e); process.exit(1); });
