const assert = require("node:assert/strict");
const { chromium, webkit } = require("playwright");

const base = process.env.BASE_URL || "http://localhost:8765";

async function run(engine) {
  const browser = await engine.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, serviceWorkers: "block" });
    // Geometry and preset switching should also work when font loading is unavailable.
    await page.route("https://cdn.jsdelivr.net/npm/opentype.js@*/**", route => route.abort());
    await page.goto(base + "/bezels/?bezel=candy-cabinet&shape=4:3");
    const canvas = page.getByRole("img", { name: "Candy Cabinet bezel preview at 4:3" });
    await canvas.waitFor();
    assert.equal(await canvas.evaluate(node => node.height), 900);
    assert.equal(await page.locator("#bezel-choice option").count(), 7);

    await page.getByLabel("Bezel", { exact: true }).selectOption("living-room-tv");
    await page.getByLabel("Display shape").selectOption("21:9");
    const wide = page.getByRole("img", { name: "Living Room TV bezel preview at 21:9" });
    await wide.waitFor();
    assert.equal(await wide.evaluate(node => node.height), 514);
    assert.match(page.url(), /bezel=living-room-tv&shape=21%3A9$/);
    assert.equal(await page.getByRole("link", { name: "Download artwork JSON" }).getAttribute("href"),
      "living-room-tv.skin.json");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  } finally {
    await browser.close();
  }
}

(async () => {
  for (const engine of [chromium, webkit]) await run(engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
