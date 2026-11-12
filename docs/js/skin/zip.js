/* EmuSkins — skin archives for the shared skin stack (docs/js/skin/).

   JSZip 3.10.1 wrapped to read a .deltaskin / .manicskin and write a new one.
   The page loads JSZip with a pinned <script> tag (see retroarch.html and
   submit.html), which defines the global `JSZip`; Node callers (tests/js, the
   merge CLI) pass their own copy as `opts.JSZip`. This module imports nothing
   from the network and touches no DOM.

   Reading follows the rules the tools already use:
     - info.json at the archive root, else exactly one folder down (the rule
       repack_skins.py and SkinLibrary.skinFolder use). Where it sits is kept
       in `prefix`, so asset names resolve relative to it.
     - `//` comments and trailing commas are stripped the way the apps do
       before parsing (see info.js stripComments), and a UTF-8 BOM is ignored.
   Writing puts info.json at the root of the new archive, pretty-printed.
*/

import { parseInfo, stringifyInfo } from "./info.js";
import { isJunk } from "./validate.js";

/** One skin should be well under this; a bigger file is probably a pack of skins. */
export const MAX_ARCHIVE_BYTES = 80 * 1024 * 1024;

/** Why an archive could not be read: code is "no_zip_library" | "too_large" |
    "not_zip" | "no_info_json" | "bad_info_json". */
export class SkinReadError extends Error {
  constructor(code, message, detail = {}) {
    super(message);
    this.name = "SkinReadError";
    this.code = code;
    Object.assign(this, detail);
  }
}

function jszip(opts) {
  const lib = (opts && opts.JSZip) || globalThis.JSZip;
  if (!lib) throw new SkinReadError("no_zip_library", "JSZip is not loaded.");
  return lib;
}

/** Where info.json sits: the root one, else the shallowest one a single folder
    down, else null. `names` are entry names; the result is the entry name.
    Other candidates (a pack of skins) come back as `alternates`. */
export function findInfoPath(names) {
  const files = names.filter(n => !n.endsWith("/") && !isJunk(n));
  if (files.includes("info.json")) return { path: "info.json", prefix: "", alternates: [] };
  const down = files.filter(n => /^[^/]+\/info\.json$/.test(n)).sort();
  if (!down.length) return null;
  return { path: down[0], prefix: down[0].slice(0, -"info.json".length), alternates: down.slice(1) };
}

/**
 * Read a skin archive.
 *   data   ArrayBuffer | Uint8Array | Blob/File | Buffer
 *   opts   { JSZip, label }  (label names the file in error messages)
 * Returns {
 *   zip,         the JSZip object
 *   names,       every entry name, directories included, as stored
 *   files,       the file entries only (no directories, no __MACOSX / .DS_Store)
 *   infoPath, prefix, alternates   where info.json was found (see findInfoPath)
 *   rawInfo,     info.json text as stored
 *   info,        parsed info.json (comments stripped)
 *   entries,     files relative to the info.json folder: what asset names resolve against
 * }
 * Throws SkinReadError.
 */
export async function readSkin(data, opts = {}) {
  const JSZip = jszip(opts);
  const size = data.byteLength != null ? data.byteLength : data.size;
  if (size > MAX_ARCHIVE_BYTES) {
    throw new SkinReadError("too_large", `${opts.label || "The file"} is ${Math.round(size / 1048576)} MB.`, { size });
  }
  let zip;
  try {
    zip = await JSZip.loadAsync(data);
  } catch (e) {
    throw new SkinReadError("not_zip", `${opts.label || "The file"} is not a zip archive.`);
  }
  const names = Object.keys(zip.files);
  const files = names.filter(n => !zip.files[n].dir && !isJunk(n));
  const found = findInfoPath(names);
  if (!found) throw new SkinReadError("no_info_json", "No info.json in the archive.", { names });
  // A directory that reads fine can still hold an entry whose data is corrupt (a bad deflate stream).
  let rawInfo;
  try {
    rawInfo = await zip.file(found.path).async("string");
  } catch (e) {
    throw new SkinReadError("bad_info_json", `info.json could not be read: ${e.message}`);
  }
  let info;
  try {
    info = parseInfo(rawInfo);
  } catch (e) {
    throw new SkinReadError("bad_info_json", `info.json could not be parsed: ${e.message}`, { rawInfo });
  }
  const entries = files.filter(n => n.startsWith(found.prefix)).map(n => n.slice(found.prefix.length));
  return { zip, names, files, infoPath: found.path, prefix: found.prefix, alternates: found.alternates, rawInfo, info, entries };
}

/** Bytes of an entry by name relative to the info.json folder, or null. */
export async function readEntry(skin, name, type = "uint8array") {
  const file = skin.zip.file(skin.prefix + name) || skin.zip.file(name);
  return file ? file.async(type) : null;
}

/**
 * Write a skin archive.
 *   files  { "path": string | Uint8Array | ArrayBuffer | Blob }  info.json is added from `info`
 *   info   the info.json object; written pretty-printed at the root
 *   opts   { JSZip, type: "blob" | "uint8array" | "arraybuffer" (default "uint8array") }
 * Deflate compression, entries in the order given (info.json first, as the
 * spec's examples and the apps' own exporter do).
 */
export async function writeSkin(files, info, opts = {}) {
  const JSZip = jszip(opts);
  const zip = new JSZip();
  zip.file("info.json", stringifyInfo(info));
  for (const [path, content] of Object.entries(files)) {
    if (path === "info.json") continue;
    zip.file(path, content);
  }
  return zip.generateAsync({ type: opts.type || "uint8array", compression: "DEFLATE" });
}

/** The archive of an opened skin with info.json replaced by `info`. Other
    entries, including the ones the editor never looked at, are copied as stored. */
export async function rewriteSkin(skin, info, opts = {}) {
  const JSZip = jszip(opts);
  const out = new JSZip();
  out.file("info.json", stringifyInfo(info));
  for (const name of skin.files) {
    if (name === skin.infoPath || !name.startsWith(skin.prefix)) continue;
    const rel = name.slice(skin.prefix.length);
    out.file(rel, await skin.zip.file(name).async("uint8array"));
  }
  return out.generateAsync({ type: opts.type || "uint8array", compression: "DEFLATE" });
}

/** Package original skin archives with private review metadata. */
export async function createSubmissionBundle(files, { author, sourceURL }) {
  const JSZip = jszip();
  const bundle = new JSZip();
  const entries = files.map((file, index) => ({
    name: file.name,
    path: `skin-${index + 1}.${file.name.split(".").at(-1).toLowerCase()}`,
  }));
  bundle.file("submission.json", JSON.stringify({ author, sourceURL, permission: true, files: entries }));
  entries.forEach(({ path }, index) => bundle.file(path, files[index]));
  return bundle.generateAsync({ type: "blob", compression: "STORE" });
}
