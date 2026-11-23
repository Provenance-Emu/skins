// A line shows as one card on the browse page (specs/2026-11-23-skin-lines-design.md §7).
const assert = require('node:assert/strict');
const { chromium, webkit } = require('playwright');
const { routeCommon } = require('./lines-fixture.cjs');
const base = process.env.BASE_URL || 'http://localhost:8765';
const stub = '<!doctype html><title>line page</title><h1>Toy Pad</h1>';

(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch();
    try {
      const errors = [];
      const page = await browser.newPage({ serviceWorkers: 'block', viewport: { width: 1200, height: 900 } });
      page.on('pageerror', error => errors.push(error.message));
      await routeCommon(page);
      await page.route('**/l/a-pad.html*', route => route.fulfill({ contentType: 'text/html', body: stub }));
      // The search box is debounced: wait for the grid to show what the query should give.
      const search = async (text, hrefEnd) => {
        await page.locator('#search').fill(text);
        await page.waitForFunction(end => {
          const cards = document.querySelectorAll('#skin-grid .skin-card');
          const line = document.querySelector('#skin-grid .line-card');
          if (cards.length !== 1) return false;
          return end === null ? !line : !!line && line.dataset.href.endsWith(end);
        }, hrefEnd);
      };
      await page.goto(`${base}/index.html`);
      await page.locator('.line-card').waitFor();
      // 1. one card for the line, one family, two singles
      assert.equal(await page.locator('#skin-grid .skin-card').count(), 4);
      assert.equal(await page.locator('.line-card').count(), 1);
      // 2. title and badge; the card never says "line"
      const card = page.locator('.line-card');
      assert.equal((await card.locator('.card-name').textContent()).trim(), 'Toy Pad');
      assert.equal((await card.locator('.line-badge').textContent()).trim(), '6 layouts · 2 colours');
      assert.doesNotMatch(await card.textContent(), /\bline\b/i);
      assert.match(await card.getAttribute('data-href'), /\/l\/a-pad\.html$/);
      assert.match(await card.locator('.card-thumb img').getAttribute('src'), /a1\.png/);   // the default member
      // 3. counts are designs first
      assert.equal((await page.locator('#results-count').innerText()).trim(), '4 designs · 12 skins');
      assert.equal((await page.locator('#stat-total').innerText()).trim(), '4');
      assert.equal(await page.locator('#stat-total').getAttribute('title'), '12 files');
      assert.equal((await page.locator('.stat-label').first().innerText()).trim().toLowerCase(), 'designs');
      // 7. the default sort is by date added: e2 is the newest file, so the line comes first
      assert.equal(await page.locator('#skin-grid .skin-card').first().getAttribute('data-line-id'), 'a-pad');
      // 4. an option label finds the line once, opened on the matching file
      await search('left', '/l/a-pad.html?skin=b1');
      assert.match(await page.locator('.line-card').getAttribute('data-href'), /\/l\/a-pad\.html\?skin=b1$/);
      assert.match(await page.locator('.line-card .card-thumb img').getAttribute('src'), /b1\.png/);
      // 5. several words, each from a different option
      await search('tate blue', '?skin=d2');
      assert.match(await page.locator('.line-card').getAttribute('data-href'), /\?skin=d2$/);
      // the line's own name still finds it, on its default
      await search('toy pad', '/l/a-pad.html');
      assert.match(await page.locator('.line-card').getAttribute('data-href'), /\/l\/a-pad\.html$/);
      // an ordinary search is unchanged
      await search('lone', null);
      assert.equal(await page.locator('.line-card').count(), 0);
      // clicking the card goes to the line page, not the modal
      await search('toy pad', '/l/a-pad.html');
      assert.match(await page.locator('.line-card .card-name a').getAttribute('href'), /\/l\/a-pad\.html$/);
      await page.locator('.line-card .card-tags').click();
      await page.waitForURL(/\/l\/a-pad\.html$/);
      // 6. a shared ?skin= link for a member lands on the line page with that file
      await page.goto(`${base}/index.html?skin=c1`);
      await page.waitForURL(/\/l\/a-pad\.html\?skin=c1$/);
      // an author page does not embed line members; LINE_MEMBERS sends their old links on
      const authorHtml = `<!doctype html><html><body><main><h1>Designer</h1></main>
<div id="skin-modal" class="modal-overlay"><div id="modal-content" class="modal-card"></div></div>
<script>window.CATALOG_OVERRIDE=[];window.LINE_MEMBERS={"c1":"a-pad"};</script><script src="../js/browse.js"></script></body></html>`;
      await page.route('**/authors/designer.html*', route => route.fulfill({ contentType: 'text/html', body: authorHtml }));
      await page.goto(`${base}/authors/designer.html?skin=c1`);
      await page.waitForURL(/\/l\/a-pad\.html\?skin=c1$/);
      // an ordinary skin's link still opens the modal on the browse page
      await page.goto(`${base}/index.html?skin=s1`);
      await page.locator('#skin-modal.open, #skin-modal[style*="flex"], #skin-modal:not([hidden]) #modal-content *').first().waitFor();
      assert.match(page.url(), /index\.html\?skin=s1/);
      assert.deepEqual(errors, []);
      // lines.js blocked or failed: the page still works, with the line's families as cards
      const bare = await browser.newPage({ serviceWorkers: 'block', viewport: { width: 1200, height: 900 } });
      const bareErrors = [];
      bare.on('pageerror', error => bareErrors.push(error.message));
      await routeCommon(bare);
      await bare.route('**/js/lines.js*', route => route.abort());
      await bare.goto(`${base}/index.html`);
      await bare.locator('#skin-grid .skin-card').first().waitFor();
      assert.equal(await bare.locator('#skin-grid .skin-card').count(), 9);    // 6 line families + paw + 2 singles
      assert.equal(await bare.locator('.line-card').count(), 0);
      assert.deepEqual(bareErrors, []);
      await bare.close();
      await page.screenshot({ path: `/tmp/lines-browse-${engine.name()}.png`, animations: 'disabled' });
    } finally { await browser.close(); }
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
