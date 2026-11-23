// The toy line from fixtures/lines/resolve-cases.json as catalog entries, plus one ordinary
// family and two single skins. Shared by lines-browse.cjs and line-page.cjs.
const fs = require('node:fs');
const path = require('node:path');
const doc = JSON.parse(fs.readFileSync(path.join(__dirname, '../../fixtures/lines/resolve-cases.json'), 'utf8'));
const line = doc.line;
const entry = (id, name, extra = {}) => ({
  id, name, systems: ['mame'], author: 'Designer', source: 'designer/pads', creator: 'designer',
  downloadURL: `https://example.com/${id}.manicskin`, thumbnailURL: `https://example.com/${id}.png`,
  addedAt: '2026-11-01', ...extra,
});
const members = doc.members.map(m => entry(m.id, m.name, {
  groupId: m.groupId, groupOrder: m.groupOrder, options: m.options, lineId: line.id,
  variantLabel: m.options.colour === 'red' ? 'Red' : 'Blue',
  screenshotURLs: [`https://example.com/${m.id}-landscape.png`], fileSize: 1048576,
  addedAt: m.id === 'e2' ? '2026-11-20' : '2026-11-01',
}));
const others = [
  entry('f1', 'Paw — Doom', { groupId: 'paw', groupOrder: 0, variantLabel: 'Doom', addedAt: '2026-11-10' }),
  entry('f2', 'Paw — AvP', { groupId: 'paw', groupOrder: 1, variantLabel: 'AvP', addedAt: '2026-11-10' }),
  entry('s1', 'Lone Wolf', { addedAt: '2026-11-05' }),
  entry('s2', 'Plain Jane', { addedAt: '2026-11-04' }),
];
const skins = [...members, ...others];
const catalog = { version: 3, lastUpdated: '2026-11-23T00:00:00Z', totalSkins: skins.length, lines: [line], skins };
const lineFile = { line, members };
const png = '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="300"><rect width="200" height="300" fill="#578"/></svg>';
async function routeCommon(page) {
  await page.route('**/catalog*.json', route => route.fulfill({ json: catalog }));
  await page.route('**/featured.json', route => route.fulfill({ json: { picks: [] } }));
  await page.route('**/creators.json', route => route.fulfill({ json: { creators: [] } }));
  await page.route('**/lines/a-pad.json*', route => route.fulfill({ json: lineFile }));
  await page.route('https://example.com/*.png', route => route.fulfill({ contentType: 'image/svg+xml', body: png }));
}
module.exports = { line, members, skins, catalog, lineFile, routeCommon };
