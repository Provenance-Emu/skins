import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { STD_PARTS } from "../../docs/js/skin2/std-parts.js";
import { manifestFor } from "./manifest.js";

const root = process.env.SKIN2_REFERENCE;
assert.ok(root, "Set SKIN2_REFERENCE to a SkinKit checkout");
const vendored = manifestFor(fileURLToPath(new URL("../../fixtures/format2", import.meta.url)));
const upstream = manifestFor(join(root, "Tests/Format2Fixtures"));
assert.equal(vendored.sha256, upstream.sha256, "Refresh fixtures with tests/skin2/vendor-fixtures.mjs");

const library = JSON.parse(readFileSync(join(root, "Sources/SkinKit2Core/Resources/parts/std.json"), "utf8"));
assert.deepEqual(STD_PARTS, library.parts, "Refresh the standard parts from SkinKit's std.json");
