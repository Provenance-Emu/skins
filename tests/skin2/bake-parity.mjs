import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import pixelmatch from "pixelmatch";
import { decodePNG, tolerance } from "./helpers.js";

const [swift, typescript, fixture] = process.argv.slice(2);
assert.ok(swift && typescript, "usage: node bake-parity.mjs <Swift fixture output> <TypeScript fixture output>");

const archives = (root) => readdirSync(root).sort().flatMap((fixture) =>
  readdirSync(join(root, fixture)).filter((name) => name.endsWith(".deltaskin")).sort()
    .map((name) => join(fixture, name)));
const list = (archive) => execFileSync("unzip", ["-Z1", archive], { encoding: "utf8" }).trim().split("\n").sort();
const read = (archive, file) => execFileSync("unzip", ["-p", archive, file], { maxBuffer: 64 * 1024 * 1024 });

const output = mkdtempSync(join(tmpdir(), "skin2-bake-parity-"));
function rasterize(bytes) {
  const pdf = join(output, "page.pdf");
  const prefix = join(output, "page");
  writeFileSync(pdf, bytes);
  execFileSync("pdftocairo", ["-png", "-transp", "-singlefile", "-r", "144", pdf, prefix]);
  return readFileSync(prefix + ".png");
}

let imageCount = 0;
const errors = [];
try {
  const names = archives(swift).filter((name) => !fixture || name.startsWith(fixture + "/"));
  assert.ok(names.length > 0, "No fixture bundles found");
  assert.deepEqual(archives(typescript).filter((name) => !fixture || name.startsWith(fixture + "/")), names);
  for (const name of names) {
    const a = join(swift, name), b = join(typescript, name);
    const entries = list(a);
    assert.deepEqual(list(b), entries, name);
    for (const file of entries) {
      const left = read(a, file), right = read(b, file);
      const isPDF = file.endsWith(".pdf");
      if (!isPDF && file !== "preview.png") {
        assert.ok(left.equals(right), `${name}/${file}: bytes differ`);
        continue;
      }
      const x = await decodePNG(isPDF ? rasterize(left) : left);
      const y = await decodePNG(isPDF ? rasterize(right) : right);
      assert.deepEqual([x.width, x.height], [y.width, y.height], `${name}/${file}`);
      const fraction = pixelmatch(x.data, y.data, null, x.width, x.height, { threshold: 0.1, includeAA: true })
        / (x.width * x.height);
      const limit = tolerance(name.split("/")[0]);
      if (fraction > limit) errors.push(`${name}/${file}: ${(fraction * 100).toFixed(3)}% differs`);
      imageCount++;
    }
  }
  console.log(`${names.length} archives with byte-identical metadata and source assets. Compared ${imageCount} rendered images.`);
  if (errors.length) {
    console.error(`${errors.length} images exceed the §9.3 tolerance.\n${errors.join("\n")}`);
    process.exitCode = 1;
  }
} finally {
  rmSync(output, { recursive: true, force: true });
}
