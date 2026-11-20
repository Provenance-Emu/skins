const assert = require('node:assert/strict');
const { chromium, webkit } = require('playwright');
const base = process.env.BASE_URL || 'http://localhost:8765';
const skins = ['Blue', 'Red', 'Green', ...Array.from({length: 19}, (_, i) => `Color ${i + 4}`)].map((label, i) => ({
  id: (i + 1).toString(16).padStart(16, '0'), name: `Arcade — ${label}`, variantLabel: label,
  systems: ['mame'], author: 'Designer', source: 'github', groupId: 'family', groupOrder: i,
  downloadURL: `https://example.com/${label}.manicskin`,
  thumbnailURL: `https://example.com/${label}.png`,
  screenshotURLs: [`https://example.com/${label}-landscape.png`, `https://example.com/${label}-ipad.png`],
}));
const authorHtml = `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="../style.css"></head><body>
<main><h1>Designer</h1></main><div id="skin-modal" class="modal-overlay" role="dialog" aria-label="Skin detail"><div id="modal-content" class="modal-card"></div></div>
<script>window.CATALOG_OVERRIDE=${JSON.stringify(skins)}</script><script src="../js/browse.js"></script></body></html>`;
(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch();
    try {
      const errors = [];
      const page = await browser.newPage({ serviceWorkers: 'block', viewport: { width: 390, height: 844 } });
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/authors/designer.html*', route => route.fulfill({ contentType: 'text/html', body: authorHtml }));
      await page.route('**/catalog*.json', route => route.fulfill({ json: { skins: route.request().url().includes('catalog.min') ? skins.map(({screenshotURLs, ...skin}) => skin) : skins } }));
      await page.route('https://example.com/*.png', route => route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="300"><rect width="200" height="300" fill="#578"/></svg>' }));
      await page.goto(`${base}/index.html?skin=${skins[1].id}`);
      await page.locator('.family-child').first().waitFor();
      await page.locator('.gallery-thumbnail').nth(2).waitFor();
      assert.equal((await page.locator('.family-child[aria-pressed="true"]').innerText()).trim(), 'Red');
      assert.match(await page.locator('#gallery-img').getAttribute('src'), /Red.png/);
      assert.equal(await page.locator('.gallery-thumbnail').count(), 3);
      await page.getByRole('button', { name: 'Preview 3', exact: true }).click();
      assert.match(await page.locator('#gallery-img').getAttribute('src'), /Red-ipad/);
      await page.getByRole('button', { name: 'Green', exact: true }).click();
      assert.match(await page.locator('#gallery-img').getAttribute('src'), /Green.png/);
      assert.match(await page.locator('.variant-download > .btn-primary').getAttribute('href'), /Green.manicskin/);
      assert.match(page.url(), new RegExp(skins[2].id));
      assert.equal(await page.locator('.gallery-thumbnail[aria-pressed="true"]').count(), 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.reload();
      await page.locator('.family-child').first().waitFor();
      assert.equal((await page.locator('.family-child[aria-pressed="true"]').innerText()).trim(), 'Green');
      await page.goto(`${base}/authors/designer.html?skin=${skins[1].id}`);
      await page.locator('.family-child').first().waitFor();
      assert.equal((await page.locator('.family-child[aria-pressed="true"]').innerText()).trim(), 'Red');
      await page.getByRole('button', { name: 'Green', exact: true }).click();
      await page.keyboard.press('ArrowLeft');
      assert.equal((await page.locator('.family-child[aria-pressed="true"]').innerText()).trim(), 'Red');
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `/tmp/variant-gallery-${engine.name()}.png`, fullPage: true, animations: "disabled" });
    } finally { await browser.close(); }
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
