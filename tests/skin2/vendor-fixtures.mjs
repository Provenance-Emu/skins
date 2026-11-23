#!/usr/bin/env node
/* Vendors SkinKit's Format 2.0 fixtures into fixtures/format2/ and writes MANIFEST.json (a SHA-256 per file and
   one over the whole set), which tests/skin2/fixtures.test.js checks.

     node tests/skin2/vendor-fixtures.mjs <SkinKit>/Tests/Format2Fixtures [<SkinKit commit>]

   It also copies the published schema to docs/format/skin-2.0.schema.json and rewrites docs/js/skin2/std-parts.ts
   from the standard parts library of the same checkout (run `npm run build` afterwards), and copies the Dreamcast
   VMU fixture to docs/format/examples/ as the documentation's panel example.

   The fixtures are recorded by SkinKit's Swift renderer (`SKIN2_RECORD=1 xcrun swift test`); this repo never
   edits them by hand. After a SkinKit change, run this script, review the diff and open a PR. */

import { copyFileSync, cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
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

// The published schema and the standard parts library come from the same checkout, so the three stay in step.
const skinKit = resolve(source, "../..");
copyFileSync(join(skinKit, "docs/schema/skin-2.0.schema.json"), resolve(here, "../../docs/format/skin-2.0.schema.json"));
const std = JSON.parse(readFileSync(join(skinKit, "Sources/SkinKit2Core/Resources/parts/std.json"), "utf8"));
writeFileSync(resolve(here, "../../docs/js/skin2/std-parts.ts"),
  `// Vendored from SkinKit/Sources/SkinKit2Core/Resources/parts/std.json.\nimport type { JSONValue } from "./json.js";\n\n`
  + `export const STD_PARTS: Record<string, JSONValue> = ${JSON.stringify(std.parts, null, 2)};\n`);
// The documentation's panel example is the Dreamcast VMU fixture, with its drawn sample picture.
const examples = resolve(here, "../../docs/format/examples");
mkdirSync(join(examples, "pictures"), { recursive: true });
copyFileSync(join(dest, "dreamcast-vmu/skin.json"), join(examples, "dreamcast-vmu.json"));
copyFileSync(join(dest, "dreamcast-vmu/pictures/vmu.p1.png"), join(examples, "pictures/vmu.p1.png"));
console.log(`vendored the schema and ${Object.keys(std.parts).length} standard parts (${std.library} ${std.version})`);
