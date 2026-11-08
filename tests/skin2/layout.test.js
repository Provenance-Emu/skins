/* Section 9.2/9.3: every fixture validates with no findings, and resolves on every trait set it bakes to exactly
   as expected/<trait>.layout.json records it (after the half-point rounding the resolver applies). */

import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, test } from "node:test";

import { expectedDir, fixtureNames, layoutRecords, skinText, validateText } from "./helpers.js";

describe("fixtures validate", () => {
  for (const name of fixtureNames) {
    test(name, () => {
      const report = validateText(skinText(name));
      assert.deepEqual(report.errors.map((i) => `${i.pointer}: ${i.message}`), []);
      assert.deepEqual(report.warnings.map((i) => `${i.pointer}: ${i.message}`), []);
    });
  }
});

describe("layout.json matches exactly", () => {
  for (const name of fixtureNames) {
    test(name, () => {
      const records = layoutRecords(name);
      const dir = expectedDir(name);
      const recorded = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith(".layout.json")).sort() : [];
      assert.deepEqual(Object.keys(records).sort(), recorded, "the set of recorded layout files differs");
      for (const [file, record] of Object.entries(records)) {
        const expected = JSON.parse(readFileSync(join(dir, file), "utf8"));
        // JSON round trip drops undefined keys, as the Swift encoder leaves nil optionals out.
        assert.deepEqual(JSON.parse(JSON.stringify(record)), expected, file);
      }
    });
  }
});
