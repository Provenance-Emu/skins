#!/usr/bin/env node
/* Vendors SkinKit's Format 2.0 fixtures into fixtures/format2/ and writes MANIFEST.json (a SHA-256 per file and
   one over the whole set), which tests/skin2/fixtures.test.js checks.

     node tests/skin2/vendor-fixtures.mjs <SkinKit>/Tests/Format2Fixtures [<SkinKit commit>]

   The fixtures are recorded by SkinKit's Swift renderer (`SKIN2_RECORD=1 xcrun swift test`); this repo never
   edits them by hand. After a SkinKit change, run this script, review the diff and open a PR. */

import { cpSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { manifestFor } from "./manifest.js";

const here = dirname(fileURLToPath(import.meta.url));
const dest = resolve(here, "../../fixtures/format2");
const [source, commit = "unknown"] = process.argv.slice(2);
if (!source) {
  console.error("usage: vendor-fixtures.mjs <SkinKit>/Tests/Format2Fixtures [<SkinKit commit>]");
  process.exit(2);
}

rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });
cpSync(resolve(source), dest, { recursive: true });
const { files, sha256 } = manifestFor(dest);
const manifest = { source: "Provenance-Emu/SkinKit Tests/Format2Fixtures", commit, sha256, files };
writeFileSync(join(dest, "MANIFEST.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(`vendored ${Object.keys(files).length} files, sha256 ${sha256}`);
