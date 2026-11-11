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

(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch();
    try {
      for (const test of [testTutorial, testPlayground]) {
        const context = await browser.newContext({ serviceWorkers: "block" });
        await test(await context.newPage());
        await context.close();
      }
    } finally {
      await browser.close();
    }
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
