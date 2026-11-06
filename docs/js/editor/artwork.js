/* EmuSkins — artwork references and "Replace artwork" (docs/js/editor/).

   Replacing a layout's artwork swaps the file in the archive. It keeps the old
   file name unless the new file has a different extension, in which case the
   file gets the same name with the new extension and every reference to the old
   one (in the base layouts and in themes, altRepresentations and gameOverrides)
   is updated. References resolve the lenient way the apps do (validate.js findAsset).

   Pure: planReplace() returns ops and file changes; the editor runs them as one
   undoable step.
*/

import { findAsset, ASSET_SIZE_KEYS } from "../skin/validate.js";

const isObject = v => v !== null && typeof v === "object";

/**
 * Every place info.json names an artwork file: strings under a size key
 * (resizable, large, medium, small — layout assets, themes, per-item assets) and
 * a thumbstick's image name. [{ path, value }].
 */
export function assetRefs(info) {
  const out = [];
  const walk = (node, path) => {
    if (Array.isArray(node)) { node.forEach((v, i) => walk(v, path.concat(i))); return; }
    if (!isObject(node)) return;
    for (const [key, v] of Object.entries(node)) {
      const here = path.concat(key);
      if (typeof v === "string") {
        if (ASSET_SIZE_KEYS.includes(key) || (key === "name" && path[path.length - 1] === "thumbstick")) out.push({ path: here, value: v });
      } else walk(v, here);
    }
  };
  walk(info, []);
  return out;
}

const baseName = p => p.slice(p.lastIndexOf("/") + 1);
const dirName = p => p.slice(0, p.lastIndexOf("/") + 1);
const extOf = p => { const b = baseName(p); const i = b.lastIndexOf("."); return i > 0 ? b.slice(i + 1).toLowerCase() : ""; };
const stemOf = p => { const b = baseName(p); const i = b.lastIndexOf("."); return i > 0 ? b.slice(0, i) : b; };

/**
 * Plan swapping the file `entry` (an archive name) for `newFileName`'s bytes.
 *   info, names   the document's info.json and its file names
 * Returns { writeAs, ops, remove }:
 *   writeAs  the archive name the new bytes go under
 *   ops      patchInfo ops (empty when the name is kept)
 *   remove   names to delete (the old file, when renamed)
 */
export function planReplace(info, names, entry, newFileName) {
  const newExt = extOf(newFileName);
  if (newExt === extOf(entry)) return { writeAs: entry, ops: [], remove: [] };

  // The new name: same folder and stem, new extension, and a -2, -3 ... suffix when that file exists.
  const taken = new Set(names.map(n => n.toLowerCase()));
  let writeAs = `${dirName(entry)}${stemOf(entry)}.${newExt}`;
  for (let n = 2; taken.has(writeAs.toLowerCase()); n++) writeAs = `${dirName(entry)}${stemOf(entry)}-${n}.${newExt}`;

  const ops = [];
  for (const ref of assetRefs(info)) {
    if (findAsset(names, ref.value) === entry) {
      ops.push({ op: "set", path: ref.path, value: dirName(ref.value) + baseName(writeAs) });
    }
  }
  return { writeAs, ops, remove: [entry] };
}
