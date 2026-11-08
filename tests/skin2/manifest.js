/* The fixture manifest: a SHA-256 per vendored file and one over the whole set (shared by
   vendor-fixtures.mjs, which writes it, and fixtures.test.js, which checks it). */

import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

export function listFiles(dir) {
  const out = [];
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...listFiles(p));
    else out.push(p);
  }
  return out;
}

export function manifestFor(dir) {
  const files = {};
  for (const p of listFiles(dir)) {
    const rel = relative(dir, p).split("\\").join("/");
    if (rel === "MANIFEST.json") continue;
    files[rel] = createHash("sha256").update(readFileSync(p)).digest("hex");
  }
  const all = createHash("sha256");
  for (const [rel, hash] of Object.entries(files)) all.update(`${hash}  ${rel}\n`);
  return { files, sha256: all.digest("hex") };
}
