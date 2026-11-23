// The picker on a line page (docs/l/<id>.html): specs/2026-11-23-skin-lines-design.md §4, §7.
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const { chromium, webkit } = require('playwright');
const { line, members, routeCommon } = require('./lines-fixture.cjs');
const base = process.env.BASE_URL || 'http://localhost:8765';

// The real generator renders the page; only the member data is the fixture's.
const html = execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(path.join(__dirname, '../../scripts'))})
import generate_line_pages as lp
line, members = json.loads(sys.stdin.read())
print(lp.generate_line_page(line, lp.default_member_of(line, members)))
`], { input: JSON.stringify([line, members]), encoding: 'utf8' });

(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch();
    try {
      const errors = [];
      const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1100, height: 900 } });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await routeCommon(page);
      await page.route('**/l/a-pad.html*', route => route.fulfill({ contentType: 'text/html', body: html }));
      const shown = () => page.locator('#line-selected').getAttribute('data-skin-id');
      const pressed = axis => page.locator(`[data-axis="${axis}"] [aria-pressed="true"]`).getAttribute('data-value');
      const pick = (axis, value) => page.locator(`[data-axis="${axis}"] [data-value="${value}"]`).click();
      const until = id => page.waitForFunction(want => document.getElementById('line-selected').dataset.skinId === want, id);

      // 1. opens on the default file, one control per axis
      await page.goto(`${base}/l/a-pad.html`);
      await until('a1');
      assert.deepEqual(await page.locator('.line-axis').evaluateAll(n => n.map(f => f.dataset.axis)), ['device', 'game', 'hand', 'colour']);
      assert.equal(await pressed('device'), 'island');
      assert.match(await page.locator('#line-download').getAttribute('href'), /a1\.manicskin$/);
      assert.match(await page.locator('#line-img').getAttribute('src'), /a1\.png$/);
      assert.match(page.url(), /\?skin=a1$/);
      // colour with a swatch is a labelled chip; one without shows its name
      assert.equal(await page.locator('[data-axis="colour"] [data-value="red"]').getAttribute('aria-label'), 'Red');
      assert.equal((await page.locator('[data-axis="colour"] [data-value="blue"]').textContent()).trim(), 'Blue');
      // 2. left-handed
      await pick('hand', 'left');
      await until('b1');
      assert.match(page.url(), /\?skin=b1$/);
      assert.match(await page.locator('#line-skin-page').getAttribute('href'), /\/s\/b1\.html$/);
      // 3. Tate has no left-handed file: the hand falls back and "Left-handed" is marked
      await pick('game', 'tate');
      await until('d1');
      assert.equal(await pressed('hand'), 'right');
      const left = page.locator('[data-axis="hand"] [data-value="left"]');
      assert.match(await left.getAttribute('class'), /is-unavailable/);
      assert.equal(await left.getAttribute('title'), 'Left-handed: changes other options');
      assert.equal(await left.isEnabled(), true);
      assert.equal(await pressed('device'), 'island');            // d1 serves island and notch; island was asked for
      // 7. the layout's other colour
      const all = page.locator('#line-download-all');
      assert.deepEqual(JSON.parse(await all.getAttribute('data-download-all')),
        ['https://example.com/d1.manicskin', 'https://example.com/d2.manicskin']);
      assert.match(await all.textContent(), /All colours for this layout \(2\)/);
      assert.equal(await all.isVisible(), true);
      // 4. colour
      await pick('colour', 'blue');
      await until('d2');
      assert.match(await page.locator('#line-download').getAttribute('href'), /d2\.manicskin$/);
      // a marked value still works: the other options follow it
      await pick('hand', 'left');
      await until('b1');
      assert.equal(await pressed('game'), 'horizontal');
      await pick('game', 'tate');
      await pick('colour', 'blue');
      await until('d2');
      // 6. a plain visit later restores the last selection
      await page.goto(`${base}/l/a-pad.html`);
      await until('d2');
      // 5. a shared link wins over the stored selection
      await page.goto(`${base}/l/a-pad.html?skin=e2`);
      await until('e2');
      assert.equal(await pressed('device'), 'ipad');
      assert.equal(await pressed('game'), 'tate');
      assert.equal(await pressed('colour'), 'blue');
      assert.match(await page.locator('#line-download').getAttribute('href'), /e2\.manicskin$/);
      assert.equal(await all.isVisible(), false);                 // e2 is alone in its layout
      // an unknown ?skin= falls back to the stored selection
      await page.goto(`${base}/l/a-pad.html?skin=nope`);
      await until('d2');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      assert.deepEqual(errors, []);
      await page.screenshot({ path: `/tmp/line-page-${engine.name()}.png`, animations: 'disabled' });

      // the left hand chosen above is remembered across lines: a fresh visit with no stored line
      await page.evaluate(() => localStorage.removeItem('emuskins.line.a-pad'));
      await page.goto(`${base}/l/a-pad.html`);
      await until('b1');
      assert.equal(await page.locator('[data-axis="hand"] .auto').isVisible(), true);

      // an iPad opens on the iPad file, marked as chosen for it
      const ipad = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 820, height: 1180 },
        userAgent: 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' });
      const tablet = await ipad.newPage();
      await routeCommon(tablet);
      await tablet.route('**/l/a-pad.html*', route => route.fulfill({ contentType: 'text/html', body: html }));
      await tablet.goto(`${base}/l/a-pad.html`);
      await tablet.waitForFunction(() => document.getElementById('line-selected').dataset.skinId === 'e1');
      assert.equal(await tablet.locator('[data-axis="device"] .auto').isVisible(), true);
      assert.equal(await tablet.locator('#line-download-all').isVisible(), false);   // iOS installs one file at a time
      await ipad.close();

      // 8. without JavaScript the page still names the line and offers the default file
      const plain = await browser.newContext({ javaScriptEnabled: false, serviceWorkers: 'block' });
      const nojs = await plain.newPage();
      await nojs.route('**/l/a-pad.html*', route => route.fulfill({ contentType: 'text/html', body: html }));
      await nojs.goto(`${base}/l/a-pad.html`);
      assert.equal((await nojs.locator('h1').textContent()).trim(), 'Toy Pad');
      assert.match(await nojs.locator('#line-download').getAttribute('href'), /a1\.manicskin$/);
      assert.equal(await nojs.locator('#line-options').isVisible(), false);
      await plain.close();
      // the member file failing to load leaves the default on offer and throws nothing
      const broken = await context.newPage();
      const brokenErrors = [];
      broken.on('pageerror', error => brokenErrors.push(error.message));
      await broken.route('**/lines/a-pad.json*', route => route.fulfill({ status: 404, body: 'nope' }));
      await broken.route('**/l/a-pad.html*', route => route.fulfill({ contentType: 'text/html', body: html }));
      await broken.goto(`${base}/l/a-pad.html`);
      await broken.waitForTimeout(300);
      assert.match(await broken.locator('#line-download').getAttribute('href'), /a1\.manicskin$/);
      assert.deepEqual(brokenErrors, []);
    } finally { await browser.close(); }
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
