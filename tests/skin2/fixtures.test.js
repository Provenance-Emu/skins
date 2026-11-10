/* The vendored SkinKit fixtures (fixtures/format2/) match their MANIFEST.json: every file's SHA-256, and the set
   as a whole. A change to a fixture, or a missing or extra file, fails here; update them with
   tests/skin2/vendor-fixtures.mjs from a SkinKit checkout, never by hand. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { fixtureNames, FIXTURES, SKIN2_JS } from "./helpers.js";
import { manifestFor } from "./manifest.js";

const manifest = JSON.parse(readFileSync(join(FIXTURES, "MANIFEST.json"), "utf8"));

test("every vendored file matches the manifest, and nothing else is there", () => {
  const actual = manifestFor(FIXTURES);
  assert.deepEqual(Object.keys(actual.files), Object.keys(manifest.files), "the set of files changed");
  const changed = Object.keys(manifest.files).filter((f) => actual.files[f] !== manifest.files[f]);
  assert.deepEqual(changed, [], "these files differ from the manifest");
  assert.equal(actual.sha256, manifest.sha256);
});

test("the manifest names the SkinKit commit the fixtures came from", () => {
  assert.match(manifest.commit, /^[0-9a-f]{40}$/);
});

test("the fixture set is complete", () => {
  assert.deepEqual(fixtureNames, [
    "dual-screen", "effects", "gamecube-icube", "layout", "paint", "paths", "shapes", "stacks-grids", "states", "std-keypad", "std-parts", "strokes", "text", "variants",
  ]);
});

test("the font the text fixture ships is the renderer's bundled bold face", () => {
  const shipped = readFileSync(join(FIXTURES, "text/assets/fonts/Outfit-Bold.ttf"));
  assert.ok(shipped.equals(readFileSync(join(SKIN2_JS, "fonts/Outfit-Bold.ttf"))));
});
