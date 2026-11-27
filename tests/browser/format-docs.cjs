const assert = require("node:assert/strict");
const { chromium, webkit } = require("playwright");

const base = process.env.BASE_URL || "http://localhost:8765";

/** The tutorial's finished controller draws when scrolled to, in both orientations, and shows its source. */
async function testTutorial(page) {
  await page.goto(base + "/format/tutorial.html");
  const example = page.locator('figure[data-skin-example="examples/gamecube.json"]');
  await example.scrollIntoViewIfNeeded();
  const canvas = example.getByRole("img");
  await canvas.waitFor({ state: "visible" });
  assert.equal(await canvas.getAttribute("width"), "393");
  await example.getByRole("button", { name: "Landscape" }).click();
  await example.locator('canvas[data-orientation="landscape"]').waitFor({ state: "visible" });
  assert.equal(await canvas.getAttribute("width"), "852");
  assert.match(await example.locator(".example-source").textContent(), /"use": "std\.stick"/);


  const themed = page.locator('figure[data-skin-example="examples/gamecube-themed.json"]');
  await themed.scrollIntoViewIfNeeded();
  await themed.getByRole("img").waitFor({ state: "visible" });
  const before = await themed.locator("canvas").evaluate((node) => node.toDataURL());
  await themed.getByRole("combobox", { name: "Theme" }).selectOption("spice");
  await page.waitForFunction((old) => document
    .querySelector('figure[data-skin-example="examples/gamecube-themed.json"] canvas').toDataURL() !== old, before);
}

/** A selection made while an example's render waits in the queue is not cached under the earlier selection. */
async function testQueuedSelection(page) {
  // Tall enough that all six examples load at once, so the last one's first render queues behind five others.
  await page.setViewportSize({ width: 1280, height: 4000 });
  await page.goto(base + "/format/examples.html");
  const last = page.locator('figure[data-skin-example="examples/effects.json"]');
  await last.getByRole("button", { name: "Landscape" }).click();
  await last.locator('canvas[data-orientation="landscape"]').waitFor({ state: "visible" });
  await last.getByRole("button", { name: "Portrait" }).click();
  await last.locator('canvas[data-orientation="portrait"]').waitFor({ state: "visible" });
  assert.equal(await last.locator("canvas").getAttribute("width"), "393");
}

/** The playground loads an example, reports a broken source with a pointer that selects it, and repairs requires. */
async function testPlayground(page) {
  const statusStarts = (text) => page.waitForFunction(
    (start) => document.querySelector("#pg-status").textContent.startsWith(start), text);
  await page.goto(base + "/format/playground.html?example=gamecube-themed");
  const editor = page.locator("#pg-source");
  await page.locator("#pg-device canvas").waitFor({ state: "visible" });
  await statusStarts("Valid.");
  assert.equal(await page.locator("#pg-theme").isVisible(), true);

  const source = await editor.inputValue();
  await editor.fill(source.replace('"tokens",', "").replace('"input": "z"', '"input": "zz"'));
  await statusStarts("2 errors");
  const issues = page.locator("#pg-issues li");
  assert.equal(await issues.count(), 2);
  await issues.nth(1).getByRole("button").click();
  const selected = await editor.evaluate((node) => node.value.slice(node.selectionStart, node.selectionEnd));
  assert.match(selected, /"input": "zz"/);

  await page.getByRole("button", { name: "Update requires" }).click();
  await statusStarts("1 error");
  assert.match(await editor.inputValue(), /"tokens",/);

  await page.getByRole("button", { name: "Landscape" }).click();
  await page.locator('#pg-device canvas[data-orientation="landscape"]').waitFor({ state: "visible" });
  assert.equal(await page.locator("#pg-status").getAttribute("data-state"), "error");

  // A reload keeps the draft.
  await page.goto(base + "/format/playground.html");
  await page.locator("#pg-device canvas").waitFor({ state: "visible" });
  assert.match(await editor.inputValue(), /"input": "zz"/);
}

/** The panel example: its capability switch removes the panel and the "sample frame" caption, and its shelf
    switch changes the picture. The playground shows the same switches. */
async function testPanels(page) {
  await page.goto(base + "/format/examples.html");
  const example = page.locator('figure[data-skin-example="examples/dreamcast-vmu.json"]');
  await example.scrollIntoViewIfNeeded();
  await example.getByRole("img").waitFor({ state: "visible" });
  const image = () => example.locator("canvas").evaluate((node) => node.toDataURL());
  const changed = (old) => page.waitForFunction((before) => document
    .querySelector('figure[data-skin-example="examples/dreamcast-vmu.json"] canvas').toDataURL() !== before, old);
  const caption = example.locator(".example-sample");
  const capability = example.getByRole("checkbox", { name: "picture.vmu.p1" });
  assert.equal(await capability.isChecked(), true);
  assert.equal(await caption.textContent(), "sample frame");
  assert.equal(await caption.isVisible(), true);

  const withPanel = await image();
  await capability.uncheck();
  await changed(withPanel);
  assert.equal(await caption.isVisible(), false);
  await capability.check();
  await page.waitForFunction((want) => document
    .querySelector('figure[data-skin-example="examples/dreamcast-vmu.json"] canvas').toDataURL() === want, withPanel);
  assert.equal(await caption.isVisible(), true);

  // The shelf exists in landscape; in portrait the panel is fixed and the switch is disabled.
  const shelf = example.getByRole("checkbox", { name: "Visual Memory open" });
  assert.equal(await shelf.isDisabled(), true);
  await example.getByRole("button", { name: "Landscape" }).click();
  await example.locator('canvas[data-orientation="landscape"]').waitFor({ state: "visible" });
  assert.equal(await shelf.isDisabled(), false);
  assert.equal(await shelf.isChecked(), true);
  const open = await image();
  await shelf.uncheck();
  await changed(open);
  assert.equal(await caption.isVisible(), true);

  await page.goto(base + "/format/playground.html?example=dreamcast-vmu");
  await page.locator("#pg-device canvas").waitFor({ state: "visible" });
  await page.waitForFunction(() => document.querySelector("#pg-status").textContent.startsWith("Valid."));
  const pg = page.locator("#pg-switches");
  assert.equal(await pg.isVisible(), true);
  assert.equal(await page.locator("#pg-sample").isVisible(), true);
  const before = await page.locator("#pg-device canvas").evaluate((node) => node.toDataURL());
  await pg.getByRole("checkbox", { name: "picture.vmu.p1" }).uncheck();
  await page.waitForFunction((old) => document.querySelector("#pg-device canvas").toDataURL() !== old, before);
  assert.equal(await page.locator("#pg-sample").isVisible(), false);
  // A skin with no capabilities or shelves shows no switches.
  await page.goto(base + "/format/playground.html?example=gamecube");
  await page.locator("#pg-device canvas").waitFor({ state: "visible" });
  await page.waitForFunction(() => document.querySelector("#pg-status").textContent.startsWith("Valid."));
  assert.equal(await page.locator("#pg-switches").isVisible(), false);
}

(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch();
    try {
      for (const test of [testTutorial, testQueuedSelection, testPlayground, testPanels]) {
        const context = await browser.newContext({ serviceWorkers: "block" });
        await test(await context.newPage());
        await context.close();
      }
    } finally {
      await browser.close();
    }
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
