// validate.js against link_health.py: both are checked against the same expected verdicts in
// tests/fixtures/skin-stack/validate-cases.json (the Python side is tests/test_skin_stack_validate.py),
// over synthetic broken skins, fixtures/variants/ and the members of fixtures/merge/.
//   cd tests/js && npm ci && npm test

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, existsSync } from "node:fs";
import { join } from "node:path";

import { JSZip, ROOT, cases, caseFiles, zipFiles, fixtureBytes } from "./helpers.js";
import { classifyArchive, findAsset, validate, computeVariants, innerSkinPaths } from "../../../docs/js/skin/validate.js";

/** What link_health.check_url does with an archive: names in stored order, root info.json text on demand. */
async function classifyBytes(data) {
  const zip = await JSZip.loadAsync(data);
  const names = Object.keys(zip.files);
  const infoFile = zip.file("info.json");
  const text = infoFile ? await infoFile.async("string") : null;
  return classifyArchive(names, () => text);
}

const withoutError = r => { const { error, ...rest } = r; return rest; };

for (const c of cases.cases) {
  test(`case ${c.name} agrees with link_health.py`, async () => {
    const got = await classifyBytes(await zipFiles(caseFiles(c)));
    assert.deepEqual(withoutError(got), c.expected);
    if (c.expected.result === "bad_info_json") assert.ok(got.error, "bad_info_json says why");
  });
}

for (const f of cases.fixtures) {
  test(`fixture ${f.path} agrees with link_health.py`, async () => {
    assert.deepEqual(withoutError(await classifyBytes(await fixtureBytes(f))), f.expected);
  });
}

test("every fixture archive and merge member is covered by the cases file", () => {
  const listed = new Set(cases.fixtures.map(f => f.path));
  const found = [];
  const walk = dir => {
    for (const e of readdirSync(join(ROOT, dir), { withFileTypes: true })) {
      const p = `${dir}/${e.name}`;
      if (e.isDirectory()) walk(p);
      else if (/\.(deltaskin|manicskin)$/.test(e.name)) found.push(p);
    }
  };
  walk("fixtures/variants");
  for (const family of readdirSync(join(ROOT, "fixtures", "merge"))) {
    const members = join(ROOT, "fixtures", "merge", family, "members");
    if (existsSync(members)) for (const m of readdirSync(members)) found.push(`fixtures/merge/${family}/members/${m}`);
  }
  assert.ok(found.length >= 20, "found the fixtures");
  assert.deepEqual(found.filter(p => !listed.has(p)), [], "add new fixtures to validate-cases.json (see its note)");
});

test("findAsset resolves like Archive.entry(matchingAssetNamed:)", () => {
  const files = ["info.json", "Art/IPhone_Portrait.PDF", "landscape.png", "a.svg"];
  assert.equal(findAsset(files, "info.json"), "info.json");
  assert.equal(findAsset(files, "iphone_portrait.pdf"), "Art/IPhone_Portrait.PDF");
  assert.equal(findAsset(files, "x/y/ART/iphone_portrait.pdf"), "Art/IPhone_Portrait.PDF");
  assert.equal(findAsset(files, "landscape.pdf"), "landscape.png");
  assert.equal(findAsset(files, "a.png"), "a.svg");
  assert.equal(findAsset(files, "missing.pdf"), null);
  assert.equal(findAsset(files, ""), null);
  assert.equal(findAsset(files, "dir/"), null);
});

test("innerSkinPaths lists skin files and skin folders once", () => {
  assert.deepEqual(innerSkinPaths(["a.DeltaSkin", "B.manicskin/info.json", "B.manicskin/x.png", "c.txt"]), ["a.DeltaSkin", "B.manicskin/"]);
});

test("computeVariants lists alt, themes and per-game overrides in that order, trimmed and de-duplicated", () => {
  assert.deepEqual(computeVariants({ gameOverrides: { Doom: {} }, themes: [{ id: " d ", name: " Dark " }, { id: "d" }, { id: "" }, 3], altRepresentations: { iphone: {} } }), [
    { kind: "alt", key: "alt", label: "Alternate layout" },
    { kind: "theme", key: "d", label: "Dark" },
    { kind: "game", key: "Doom", label: "Doom" },
  ]);
  assert.deepEqual(computeVariants({ altRepresentations: {} }), []);
  assert.deepEqual(computeVariants(null), []);
});

// ── Findings ─────────────────────────────────────────────────────────────

const verdictOf = name => cases.cases.find(c => c.name === name).expected;
const summarize = r => r.findings.map(f => `${f.severity}: ${f.title}`);

test("a healthy skin validates with only the info finding", () => {
  const r = validate(verdictOf("healthy"), { info: { debug: false }, names: ["info.json", "a.png", "b.png"] });
  assert.equal(r.isValid, true);
  assert.deepEqual(summarize(r), ["info: Skin is valid"]);
});

test("a skin without a debug flag gets the same warning the Swift validator gives, and stays valid", () => {
  const r = validate(verdictOf("healthy"), { info: {}, names: ["info.json", "a.png", "b.png"] });
  assert.equal(r.isValid, true);
  assert.deepEqual(summarize(r), ["warning: Missing 'debug' field"]);
});

test("the broken skins come out invalid, each with a suggestion", () => {
  for (const [name, title] of [
    ["no-info-json", "Missing info.json"],
    ["nested-folder", "info.json is inside a folder"],
    ["pack-of-skins", "Archive holds other skins"],
    ["bad-json", "Invalid JSON in info.json"],
    ["no-artwork-anywhere", "No artwork in any layout"],
  ]) {
    const r = validate({ ...verdictOf(name), error: "x" });
    assert.equal(r.isValid, false, name);
    assert.deepEqual(r.errors.map(f => f.title), [title], name);
    assert.ok(r.errors[0].suggestion, `${name} has a suggestion`);
  }
  assert.deepEqual(validate(verdictOf("missing-keys")).errors.map(f => f.title),
    ["Missing required field: identifier", "Missing required field: gameTypeIdentifier"]);
  assert.equal(validate({ result: "not_zip" }).errors[0].title, "Invalid archive");
});

test("partial artwork warns per layout but the skin stays valid", () => {
  const r = validate(verdictOf("partial-artwork"), { info: { debug: false } });
  assert.equal(r.isValid, true);
  assert.deepEqual(summarize(r), ["warning: No artwork for iphone/edgeToEdge/landscape"]);
});

test("a size that does not resolve warns when another size of the layout does", () => {
  const names = ["info.json", "big.png"];
  const info = { debug: false, representations: { iphone: { edgeToEdge: { portrait: { assets: { resizable: "gone.pdf", large: "big.png" } } } } } };
  const r = validate({ result: "ok", variants: [] }, { info, names });
  assert.deepEqual(summarize(r), ["warning: Missing asset: gone.pdf"]);
  assert.equal(r.isValid, true);
});
