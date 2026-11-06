/* EmuSkins — the document the skin editor edits (docs/js/editor/).

   A SkinDoc is an opened skin: the info.json object plus the archive's files.
   The files are not copied up front. `base` reads them from the archive on
   demand and `overrides` holds what the editor has replaced (bytes) or removed
   (null). Edits to `info` go through patchInfo (history.js), so keys the editor
   never looked at come out as they went in.

   The editor's entry point takes this shape, not a zip, so the merge tool
   (SkinKit#77) can hand over a skin it built in memory: see openSkin() in
   docs/js/edit-page.js.
*/

export class SkinDoc {
  /**
   *   info        the parsed info.json
   *   names       file names relative to the info.json folder, info.json excluded
   *   read        async (name) => Uint8Array of a base file, or null
   *   label       what to call the skin in the UI (a file name)
   */
  constructor({ info, names, read, label = "" }) {
    this.info = info;
    this.baseNames = names.filter(n => n !== "info.json");
    this.readBase = read;
    this.label = label;
    this.overrides = new Map();   // name → Uint8Array | null (removed)
    this.stamps = new Map();      // name → changes so far, for cache keys
    this.originalIdentifier = info && typeof info.identifier === "string" ? info.identifier : "";
  }

  /** Every file the exported archive holds (info.json aside), in archive order, new files last. */
  fileNames() {
    const out = this.baseNames.filter(n => this.overrides.get(n) !== null);
    for (const [n, v] of this.overrides) if (v !== null && !this.baseNames.includes(n)) out.push(n);
    return out;
  }

  hasFile(name) {
    return this.overrides.has(name) ? this.overrides.get(name) !== null : this.baseNames.includes(name);
  }

  async readFile(name) {
    if (this.overrides.has(name)) return this.overrides.get(name);
    return this.baseNames.includes(name) ? this.readBase(name) : null;
  }

  /** Changes to a file so far: part of a cache key for anything drawn from it. */
  stamp(name) {
    return this.stamps.get(name) || 0;
  }

  /** Put the override map back the way it was: `previous` maps name → the old entry (undefined = none). */
  restoreOverrides(previous) {
    for (const [name, value] of previous) {
      if (value === undefined) this.overrides.delete(name); else this.overrides.set(name, value);
      this.stamps.set(name, this.stamp(name) + 1);
    }
  }

  /** Apply { set: {name: bytes}, remove: [names] }; returns the previous entries for restoreOverrides(). */
  applyFiles(files) {
    const previous = new Map();
    const touch = (name, value) => {
      if (!previous.has(name)) previous.set(name, this.overrides.has(name) ? this.overrides.get(name) : undefined);
      this.overrides.set(name, value);
      this.stamps.set(name, this.stamp(name) + 1);
    };
    for (const [name, bytes] of Object.entries((files && files.set) || {})) touch(name, bytes);
    for (const name of (files && files.remove) || []) touch(name, null);
    return previous;
  }
}

/** The files map writeSkin() takes: every file of the document with its current bytes. */
export async function exportFiles(doc) {
  const out = {};
  for (const name of doc.fileNames()) out[name] = await doc.readFile(name);
  return out;
}
