const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { chromium, webkit } = require("playwright");
const { zipSync, strToU8 } = require("fflate");

const BASE = process.env.BASE_URL || "http://localhost:8765";
const url = "https://skins.test.invalid/preview.deltaskin";
const blocked = "https://deltastyles.com/files/skins/1/preview.deltaskin";
const source = readFileSync(`${__dirname}/../../fixtures/format2/gamecube-icube/skin.json`);
const archive = Buffer.from(zipSync({
  "info.json": strToU8(JSON.stringify({ format2: { source: "skin.json" } })),
  "skin.json": source,
}));
const catalog = { skins: [url, blocked].map((downloadURL, index) => ({
  id: `preview-${index}`, name: `Format 2 preview ${index}`, systems: ["gamecube"],
  source: "github", downloadURL, format2: true,
})) };

async function run(engine) {
  const browser = await engine.launch();
  try {
    const context = await browser.newContext({ serviceWorkers: "block" });
    await context.route("**/catalog.min.json", (route) => route.fulfill({ json: catalog }));
    await context.route("**/catalog.json", (route) => route.fulfill({ json: catalog }));
    await context.route(url, (route) => route.fulfill({
      body: archive, headers: { "access-control-allow-origin": "*", "content-type": "application/zip" },
    }));
    const page = await context.newPage();
    for (const [index, needsFile] of [[0, false], [1, true]]) {
      await page.goto(`${BASE}/index.html?skin=preview-${index}`);
      const preview = page.locator("[data-format2-preview]");
      await preview.locator("summary").click();
      if (needsFile) {
        await preview.locator("label").waitFor({ state: "visible" });
        await preview.locator("input").setInputFiles({
          name: "preview.deltaskin", mimeType: "application/zip", buffer: archive,
        });
      }
      const canvas = preview.locator("canvas");
      await canvas.waitFor({ state: "visible" });
      assert.equal(await canvas.getAttribute("width"), "393");
      await preview.locator("select").selectOption("landscape");
      assert.equal(await canvas.getAttribute("width"), "852");
    }
  } finally {
    await browser.close();
  }
}

(async () => { for (const engine of [chromium, webkit]) await run(engine); })().catch((error) => { console.error(error); process.exitCode = 1; });
