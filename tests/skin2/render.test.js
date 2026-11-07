/* Section 9.3: every fixture renders at 2x to the recorded reference images. pixelmatch with threshold 0.1;
   at most 0.25 % of pixels may differ (1.0 % for effects, whose blur kernels differ). Failing renders leave
   the actual and diff images in $SKIN2_FAILURES (default: the system temp directory). */

import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, test } from "node:test";

import { SUPPORTED_FEATURES } from "../../docs/js/skin2/index.js";
import {
  comparePNG, decodePNG, expectedDir, fixtureDoc, fixtureNames, referenceImages, renderReference, tolerance, writeFailure,
} from "./helpers.js";

describe("the renderer supports every feature the fixtures require", () => {
  for (const name of fixtureNames) {
    test(name, () => {
      const missing = fixtureDoc(name).requires.filter((r) => !SUPPORTED_FEATURES.has(r));
      assert.deepEqual(missing, []);
    });
  }
});

for (const name of fixtureNames) {
  describe(`${name} renders to the recorded reference images`, () => {
    test("the set of reference images is the set to render", () => {
      const dir = expectedDir(name);
      const recorded = existsSync(dir) ? readdirSync(dir).filter((f) => f.endsWith("@2x.png")).sort() : [];
      assert.deepEqual(referenceImages(name).map((r) => r.file).sort(), recorded);
    });

    for (const ref of referenceImages(name)) {
      test(ref.file, async () => {
        const expected = readFileSync(join(expectedDir(name), ref.file));
        const actual = await renderReference(name, ref);
        const size = await decodePNG(expected);
        assert.deepEqual([actual.width, actual.height], [size.width, size.height], "image size");
        const { fraction } = await comparePNG(actual, expected);
        if (fraction > tolerance(name)) {
          const { diff } = await comparePNG(actual, expected, { wantDiff: true });
          const dir = writeFailure(name, ref.file, actual, diff);
          assert.fail(`${(fraction * 100).toFixed(3)} % of pixels differ (limit ${tolerance(name) * 100} %); actual and diff in ${dir}`);
        }
      });
    }
  });
}
