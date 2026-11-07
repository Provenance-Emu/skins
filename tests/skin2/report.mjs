#!/usr/bin/env node
/* Prints, for every reference image (or for the fixtures named on the command line), how many pixels differ from
   SkinKit's recording: with pixelmatch counting anti-aliased pixels (what the tests use) and ignoring them. Failing
   renders leave their actual and diff images in $SKIN2_FAILURES (default: the system temp directory).

     node tests/skin2/report.mjs [fixture ...] */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { comparePNG, expectedDir, fixtureNames, referenceImages, renderReference, tolerance, writeFailure } from "./helpers.js";

const only = process.argv.slice(2);
let worst = 0;
for (const name of fixtureNames) {
  if (only.length > 0 && !only.includes(name)) continue;
  for (const ref of referenceImages(name)) {
    const path = join(expectedDir(name), ref.file);
    if (!existsSync(path)) {
      console.log(`MISSING ${name}/${ref.file}`);
      continue;
    }
    const expected = readFileSync(path);
    const actual = await renderReference(name, ref);
    const strict = await comparePNG(actual, expected, { wantDiff: true });
    const lenient = await comparePNG(actual, expected, { includeAA: false });
    const ok = strict.fraction <= tolerance(name);
    if (!ok) writeFailure(name, ref.file, actual, strict.diff);
    worst = Math.max(worst, strict.fraction / tolerance(name));
    console.log(`${ok ? "ok  " : "FAIL"} ${name} ${ref.file} ${(strict.fraction * 100).toFixed(3)} % (without AA ${(lenient.fraction * 100).toFixed(3)} %, limit ${tolerance(name) * 100} %)`);
  }
}
console.log(`worst: ${(worst * 100).toFixed(1)} % of the tolerance`);
