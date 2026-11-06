// Shared by the skin-stack tests: JSZip from node_modules, the repo paths, and
// archives built from fixture directories or from tests/fixtures/skin-stack/validate-cases.json.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import JSZip from "jszip";

export { JSZip };
export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
export const SKIN_DIR = join(ROOT, "docs", "js", "skin");
export const readJson = path => JSON.parse(readFileSync(path, "utf8"));
export const cases = readJson(join(ROOT, "tests", "fixtures", "skin-stack", "validate-cases.json"));

/** Entry names and bytes of a zip, in the stored order. */
export async function archiveNames(data) {
  return Object.keys((await JSZip.loadAsync(data)).files);
}

/** Zip a files map { path: string | Buffer }; a path ending in "/" is a directory entry. No implicit folders. */
export async function zipFiles(files) {
  const zip = new JSZip();
  for (const [path, content] of Object.entries(files)) {
    if (path.endsWith("/")) zip.file(path, "", { dir: true, createFolders: false });
    else zip.file(path, content, { createFolders: false });
  }
  return zip.generateAsync({ type: "nodebuffer" });
}

/** The files map a validate-cases.json case describes. */
export function caseFiles(c) {
  const out = {};
  for (const [path, content] of Object.entries(c.files)) out[path] = typeof content === "string" ? content : JSON.stringify(content.json);
  return out;
}

/** Zip a folder (every file, sorted, relative paths) as the Python tests do. */
export async function zipDir(dir) {
  const files = {};
  const walk = d => {
    for (const name of readdirSync(d).sort()) {
      const full = join(d, name);
      if (statSync(full).isDirectory()) walk(full);
      else files[relative(dir, full).split(sep).join("/")] = readFileSync(full);
    }
  };
  walk(dir);
  return zipFiles(files);
}

/** Zip bytes of a validate-cases.json fixture entry (a skin file, or a folder to zip). */
export async function fixtureBytes(f) {
  const full = join(ROOT, f.path);
  return f.zipDir ? zipDir(full) : readFileSync(full);
}
