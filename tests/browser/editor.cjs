// Browser flow test for docs/edit.html in Chromium and WebKit: load a fixture skin, move a button with the
// mouse and with the keyboard, undo, rename, edit a layout field, replace artwork, download the .deltaskin
// and check the archive: the edits are in info.json, unknown keys survived, the artwork came along. Also the
// draft (offered after a reload, never applied on its own) and the read-only view on an iPhone.
// Expects the site served at BASE (CI: python3 -m http.server on docs/).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium, webkit, devices } = require("playwright");
const { zipSync, unzipSync, strToU8, strFromU8 } = require("fflate");

const BASE = process.env.BASE_URL || "http://localhost:8765";
const FIXTURE = path.join(__dirname, "..", "..", "fixtures", "variants", "sample-nes.deltaskin");
const PORTRAIT = ["representations", "iphone", "edgeToEdge", "portrait"];
const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=", "base64");

const at = (obj, keys) => keys.reduce((o, k) => o[k], obj);

/** The fixture with unknown keys added, so the test can see them come back. */
function skinWithUnknownKeys() {
  const files = unzipSync(fs.readFileSync(FIXTURE));
  const info = JSON.parse(strFromU8(files["info.json"]));
  info.keyboardOverlay = { rows: [["q", "w"]] };
  info.futureKey = [1, 2, { deep: true }];
  at(info, PORTRAIT).items[0].futureItemKey = "keep";
  files["info.json"] = strToU8(JSON.stringify(info));
  return { buffer: Buffer.from(zipSync(files)), info };
}

async function boxOf(page, selector) {
  const box = await page.locator(selector).boundingBox();
  assert.ok(box, `${selector} is on screen`);
  return box;
}

/** Downloads the skin and returns { name, info, files }. */
async function download(page) {
  const [file] = await Promise.all([page.waitForEvent("download"), page.click("#ed-download")]);
  const files = unzipSync(fs.readFileSync(await file.path()));
  return { name: file.suggestedFilename(), info: JSON.parse(strFromU8(files["info.json"])), files };
}

async function run(name, engine) {
  const browser = await engine.launch({ headless: true });
  const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  const { buffer, info: original } = skinWithUnknownKeys();

  await page.goto(`${BASE}/edit.html`);
  assert.ok(await page.locator("#ed-workspace").isHidden(), `${name}: no editor before a skin is loaded`);
  await page.setInputFiles("#ed-file", { name: "sample-nes.deltaskin", mimeType: "application/zip", buffer });
  await page.locator("#ed-workspace").waitFor({ state: "visible" });
  await page.locator('[data-item="0"]').waitFor();
  assert.equal(await page.locator("[data-item]").count(), at(original, PORTRAIT).items.length, `${name}: one box per button`);
  assert.equal(await page.locator("[data-screen]").count(), 1, `${name}: the screen is drawn`);
  assert.equal(await page.inputValue("#ed-trait"), "iphone/edgeToEdge/portrait", `${name}: starts on the iPhone portrait frame`);
  await page.waitForFunction(() => document.getElementById("ed-bg").width > 1);
  assert.equal(await page.locator("#ed-bg").evaluate(c => c.getContext("2d").getImageData(0, 0, c.width, c.height).data.some((v, i) => i % 4 === 3 && v > 0)), true, `${name}: the artwork is drawn behind the boxes`);

  // Select a button and drag it with the mouse: the frame in the panel follows, snapped to whole points.
  const before = at(original, PORTRAIT).items[4].frame;     // the "a" button
  const scale = (await boxOf(page, '[data-item="4"]')).width / before.width;
  await page.click('[data-item="4"]');
  assert.equal(await page.inputValue('[data-fid="item.frame.x"]'), String(before.x), `${name}: panel shows the frame`);
  const box = await boxOf(page, '[data-item="4"]');
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx - 30, cy - 20, { steps: 6 });
  await page.mouse.up();
  const dragged = {
    x: Number(await page.inputValue('[data-fid="item.frame.x"]')), y: Number(await page.inputValue('[data-fid="item.frame.y"]')),
  };
  assert.ok(Math.abs(dragged.x - (before.x - 30 / scale)) <= 12, `${name}: dragged left by about 30px (${dragged.x} vs ${before.x - 30 / scale})`);
  assert.ok(dragged.y < before.y, `${name}: dragged up`);
  assert.equal(await page.inputValue('[data-fid="item.frame.w"]'), String(before.width), `${name}: a move keeps the size`);

  // Keyboard nudges: 1 point, 10 with shift; they join into one undo step.
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Shift+ArrowDown");
  assert.equal(await page.inputValue('[data-fid="item.frame.x"]'), String(dragged.x + 1), `${name}: ArrowRight nudges 1`);
  assert.equal(await page.inputValue('[data-fid="item.frame.y"]'), String(dragged.y + 10), `${name}: Shift+ArrowDown nudges 10`);
  await page.click("#ed-undo");
  assert.equal(await page.inputValue('[data-fid="item.frame.x"]'), String(dragged.x), `${name}: undo takes back the whole burst of nudges`);
  await page.click('[data-item="4"]');                   // back on the canvas, so the shortcut reaches it
  await page.keyboard.press("Control+z");
  assert.equal(await page.inputValue('[data-fid="item.frame.x"]'), String(before.x), `${name}: Ctrl+Z undoes the drag too`);
  await page.click("#ed-redo");
  assert.equal(await page.inputValue('[data-fid="item.frame.x"]'), String(dragged.x), `${name}: redo moves it again`);

  // Type an exact frame in the panel, rename the skin, give it its own identifier, set a layout field.
  await page.fill('[data-fid="item.frame.x"]', String(before.x + 17));
  await page.press('[data-fid="item.frame.x"]', "Enter");
  await page.waitForFunction(x => document.querySelector('[data-fid="item.frame.x"]').value === String(x), before.x + 17);
  const movedY = Number(await page.inputValue('[data-fid="item.frame.y"]'));
  await page.fill('[data-fid="skin.name"]', "Edited NES");
  await page.press('[data-fid="skin.name"]', "Enter");
  assert.ok(await page.locator("#ed-identifier-warning").isVisible(), `${name}: warns while the identifier is the loaded skin's`);
  await page.fill('[data-fid="skin.identifier"]', "com.example.edited.nes");
  await page.press('[data-fid="skin.identifier"]', "Enter");
  await page.locator("#ed-identifier-warning").waitFor({ state: "detached" });
  await page.waitForFunction(() => document.getElementById("ed-p-check-title").textContent === "Check — ok");

  const out = await download(page);
  assert.equal(out.name, "com.example.edited.nes.deltaskin", `${name}: named for the identifier, .deltaskin for a Delta game type`);
  assert.equal(out.info.name, "Edited NES", `${name}: the rename is in info.json`);
  assert.equal(out.info.identifier, "com.example.edited.nes");
  const item = at(out.info, PORTRAIT).items[4];
  assert.deepEqual(item.frame, { ...before, x: before.x + 17, y: movedY }, `${name}: the moved frame is in info.json`);

  // Only that button, the name and the identifier differ; unknown keys survive.
  const expected = JSON.parse(JSON.stringify(original));
  expected.name = "Edited NES";
  expected.identifier = "com.example.edited.nes";
  Object.assign(at(expected, PORTRAIT).items[4].frame, item.frame);
  assert.deepEqual(out.info, expected, `${name}: nothing else in info.json changed`);
  assert.deepEqual(out.info.keyboardOverlay, original.keyboardOverlay, `${name}: unknown top-level key kept`);
  assert.equal(at(out.info, PORTRAIT).items[0].futureItemKey, "keep", `${name}: unknown item key kept`);
  const artwork = Object.keys(unzipSync(fs.readFileSync(FIXTURE))).filter(n => n.endsWith(".png"));
  for (const f of artwork) assert.ok(out.files[f], `${name}: ${f} is in the download`);

  // Replace artwork with a different extension: the file and every reference to it are renamed.
  const entry = at(original, PORTRAIT).assets.large;
  await page.setInputFiles('[data-replace="large"]', { name: "new-art.jpg", mimeType: "image/jpeg", buffer: png });
  await page.waitForFunction(() => document.querySelector('[data-fid="layout.assets.large"]').value.endsWith(".jpg"));
  const replaced = await download(page);
  const newName = at(replaced.info, PORTRAIT).assets.large;
  assert.equal(newName, entry.replace(/\.png$/i, ".jpg"), `${name}: same name, new extension`);
  assert.equal(at(replaced.info, PORTRAIT).assets.small, newName, `${name}: every size that pointed at the old file follows`);
  assert.ok(replaced.files[newName] && !replaced.files[entry], `${name}: the new file is in, the old one is out`);
  assert.deepEqual(Array.from(replaced.files[newName]), Array.from(png), `${name}: the new file's bytes are the ones chosen`);
  await page.click("#ed-undo");
  await page.waitForFunction(e => document.querySelector('[data-fid="layout.assets.large"]').value === e, entry);

  // A skin that fails the check does not download until asked a second time.
  const broken = JSON.parse(JSON.stringify(original));
  delete broken.identifier;
  const brokenSkin = Buffer.from(zipSync({ ...unzipSync(fs.readFileSync(FIXTURE)), "info.json": strToU8(JSON.stringify(broken)) }));
  const page2 = await context.newPage();
  await page2.goto(`${BASE}/edit.html`);
  await page2.setInputFiles("#ed-file", { name: "broken.deltaskin", mimeType: "application/zip", buffer: brokenSkin });
  await page2.locator("#ed-p-check").waitFor();
  await page2.waitForFunction(() => /error/.test(document.getElementById("ed-p-check-title").textContent));
  assert.match(await page2.locator("#ed-p-check").innerText(), /Missing required field: identifier/, `${name}: the check names the missing field`);
  let downloaded = false;
  page2.on("download", () => { downloaded = true; });
  await page2.click("#ed-download");
  await page2.locator("#ed-download-anyway").waitFor({ state: "visible" });
  await page2.waitForTimeout(300);
  assert.equal(downloaded, false, `${name}: nothing downloaded while the check has errors`);
  await Promise.all([page2.waitForEvent("download"), page2.click("#ed-download-anyway")]);
  await page2.close();

  // Draft: saved after an edit; after a reload it is offered, not applied.
  await page.waitForFunction(() => document.body.dataset.draftSaved);
  await page.reload();
  assert.ok(await page.locator("#ed-workspace").isHidden(), `${name}: the draft is not opened on its own`);
  await page.locator("#ed-draft.visible").waitFor();
  await page.click("#ed-draft-restore");
  await page.locator("#ed-workspace").waitFor({ state: "visible" });
  assert.equal(await page.inputValue('[data-fid="skin.name"]'), "Edited NES", `${name}: the draft brings the edits back`);

  // Draft through a source link (?url=): the edits are offered again for that same link, not silently dropped.
  const linked = "https://skins.example.test/linked.deltaskin";
  await context.route(linked, route => route.fulfill({ status: 200, contentType: "application/zip", headers: { "access-control-allow-origin": "*" }, body: buffer }));
  const page3 = await context.newPage();
  page3.on("pageerror", e => errors.push(e.message));
  await page3.goto(`${BASE}/edit.html?url=${encodeURIComponent(linked)}`);
  await page3.locator('[data-item="0"]').waitFor();
  assert.notEqual(await page3.inputValue('[data-fid="skin.name"]').catch(() => null), "Edited NES", `${name}: a draft of a dropped file is not offered for a source link`);
  await page3.fill('[data-fid="skin.name"]', "Via link");
  await page3.press('[data-fid="skin.name"]', "Enter");
  await page3.waitForFunction(() => document.body.dataset.draftSaved);
  await page3.waitForTimeout(800);
  await page3.reload();
  await page3.locator("#ed-draft.visible").waitFor();
  assert.ok(await page3.locator("#ed-workspace").isHidden(), `${name}: the linked source waits for the answer`);
  await page3.click("#ed-draft-restore");
  await page3.locator("#ed-workspace").waitFor({ state: "visible" });
  assert.equal(await page3.inputValue('[data-fid="skin.name"]'), "Via link", `${name}: the draft comes back through the source link`);
  await page3.reload();
  await page3.locator("#ed-draft.visible").waitFor();
  await page3.click("#ed-draft-discard");
  await page3.locator('[data-item="0"]').waitFor();
  assert.notEqual(await page3.inputValue('[data-fid="skin.name"]'), "Via link", `${name}: discarding opens the original`);
  await page3.close();

  assert.deepEqual(errors, [], `${name}: no page errors`);
  await browser.close();

  // iPhone: the page opens read-only.
  const phone = await engine.launch({ headless: true });
  const phoneCtx = await phone.newContext({ ...devices["iPhone 13"], acceptDownloads: true });
  const p = await phoneCtx.newPage();
  await p.goto(`${BASE}/edit.html`);
  await p.setInputFiles("#ed-file", { name: "sample-nes.deltaskin", mimeType: "application/zip", buffer });
  await p.locator('[data-item="0"]').waitFor();
  assert.ok(await p.locator("#ed-readonly").isVisible(), `${name}: iPhone sees the read-only notice`);
  assert.ok(await p.locator("#ed-download").isDisabled() && await p.locator("#ed-add-item").isDisabled(), `${name}: iPhone cannot edit or download`);
  await p.click('[data-item="0"]');
  assert.ok(await p.locator('[data-fid="item.frame.x"]').isDisabled(), `${name}: iPhone panels are disabled`);
  assert.equal(await p.locator(".ed-handle").count(), 0, `${name}: iPhone shows no resize handles`);
  await phone.close();
  console.log(`${name}: ok`);
}

(async () => {
  for (const [name, engine] of Object.entries({ chromium, webkit })) await run(name, engine);
})().catch(e => { console.error(e); process.exit(1); });
