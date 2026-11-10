const assert = require("node:assert/strict");
const { chromium, webkit } = require("playwright");

const base = process.env.BASE_URL || "http://localhost:8765";

async function testTutorial(engine) {
  const browser = await engine.launch();
  try {
    const page = await browser.newPage();
    await page.goto(base + "/format/tutorial.html");
    const example = page.locator('figure[data-skin-example="examples/gamecube.json"]');
    await example.getByRole("button", { name: "Render preview" }).click();
    const canvas = example.getByRole("img");
    await canvas.waitFor({ state: "visible" });
    assert.equal(await canvas.getAttribute("width"), "393");
    await example.getByRole("combobox", { name: "Preview orientation" }).selectOption("landscape");
    assert.equal(await canvas.getAttribute("width"), "852");
  } finally {
    await browser.close();
  }
}

(async () => {
  for (const engine of [chromium, webkit]) await testTutorial(engine);
})().catch((error) => { console.error(error); process.exitCode = 1; });
