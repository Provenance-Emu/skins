const assert = require("node:assert/strict");
const { chromium, webkit } = require("playwright");

const base = process.env.BASE_URL || "http://localhost:8765";
const skins = [
  { id: "old", name: "Alpha", addedAt: "2024-01-01", lastUpdated: "2025-03-01", systems: ["snes"] },
  { id: "new", name: "Zulu", addedAt: "2025-01-01", lastUpdated: "2025-01-01", systems: ["gba"] },
].map(skin => ({ source: "github", ...skin }));

async function run(engine) {
  const browser = await engine.launch();
  try {
    const page = await browser.newPage({ serviceWorkers: "block" });
    await page.route("**/catalog.min.json", route => route.fulfill({ json: { skins } }));
    const sort = page.getByRole("combobox", { name: "Sort order" });
    const cards = page.locator(".card-name");
    const visit = async (query = "") => {
      await page.goto(base + "/index.html" + query);
      await cards.first().waitFor();
    };

    await visit();
    assert.equal(await sort.inputValue(), "added");
    assert.deepEqual(await cards.allTextContents(), ["Zulu", "Alpha"]);
    await page.getByRole("button", { name: "Remember preferences" }).click();
    await sort.selectOption("az");
    await page.locator('#system-chips [data-system="gba"]').click();

    await visit("?sort=added");
    assert.equal(await sort.inputValue(), "added");
    assert.deepEqual(await cards.allTextContents(), ["Zulu", "Alpha"]);
    await page.reload();
    await cards.first().waitFor();
    assert.equal(await sort.inputValue(), "added");
    assert.deepEqual(await cards.allTextContents(), ["Zulu", "Alpha"]);

    await visit("?sort=newest");
    assert.equal(await sort.inputValue(), "newest");
    assert.deepEqual(await cards.allTextContents(), ["Alpha", "Zulu"]);

    await visit();
    assert.equal(await sort.inputValue(), "az");
    assert.deepEqual(await cards.allTextContents(), ["Zulu"]);
    await page.getByRole("button", { name: "Storage preferences" }).click();
    await page.getByRole("button", { name: "No thanks" }).click();

    await visit();
    assert.equal(await sort.inputValue(), "added");
    assert.deepEqual(await cards.allTextContents(), ["Zulu", "Alpha"]);
    assert.equal(await page.getByRole("button", { name: "Remember preferences" }).isVisible(), false);
  } finally {
    await browser.close();
  }
}

(async () => {
  for (const engine of [chromium, webkit]) await run(engine);
})().catch(error => { console.error(error); process.exitCode = 1; });
