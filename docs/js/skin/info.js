/* EmuSkins — the info.json model of the shared skin stack (docs/js/skin/).

   An info.json is a plain object graph. Nothing here knows the full schema:
   unknown keys (keyboardOverlay, haptic, states, whatever Delta adds next)
   come out of a parse → patch → stringify round trip exactly as they went in,
   because edits are patches on the raw dictionary (the way SkinKit's
   DeltaSkinExporter.patchItems does it), not a typed model re-encoded.

   Pure ES module: no DOM, no network. Used by the editor, the RetroArch
   converter and the merge tool.

   One JavaScript limit: objects order integer-like keys ("1", "2") before
   other keys. info.json has none today (device, display type and orientation
   names are words), so key order survives the round trip.
*/

// ── Parsing ──────────────────────────────────────────────────────────────

/** Strip line and block comments and trailing commas that sit outside
    strings, like SkinKit's sanitizeJSON. Delta's parser ignores them, so skins
    in the wild have them. Strings are copied through untouched. */
export function stripComments(text) {
  let out = "", inString = false, escaped = false, lineComment = false, blockComment = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (lineComment) {
      if (ch === "\n" || ch === "\r") { lineComment = false; out += ch; }
      continue;
    }
    if (blockComment) {
      if (ch === "*" && text[i + 1] === "/") { blockComment = false; i++; }
      continue;
    }
    if (inString) {
      out += ch;
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') { inString = true; out += ch; }
    else if (ch === "/" && text[i + 1] === "/") { lineComment = true; i++; }
    else if (ch === "/" && text[i + 1] === "*") { blockComment = true; i++; }
    else if (ch === ",") {
      // A comma followed only by whitespace/comments and then } or ] is dropped.
      let j = i + 1;
      while (j < text.length) {
        if (/\s/.test(text[j])) j++;
        else if (text[j] === "/" && text[j + 1] === "/") { while (j < text.length && text[j] !== "\n") j++; }
        else if (text[j] === "/" && text[j + 1] === "*") { const e = text.indexOf("*/", j + 2); j = e < 0 ? text.length : e + 2; }
        else break;
      }
      if (text[j] === "}" || text[j] === "]") continue;
      out += ch;
    }
    else out += ch;
  }
  return out;
}

export function parseInfo(text) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  return JSON.parse(stripComments(text));
}

/** info.json text as the editor writes it: 2-space indent, no comments, trailing newline. */
export function stringifyInfo(info, indent = 2) {
  return JSON.stringify(info, null, indent) + "\n";
}

/** A deep copy that shares nothing with the original. */
export function cloneInfo(info) {
  return JSON.parse(JSON.stringify(info));
}

// ── Patches ──────────────────────────────────────────────────────────────

const isObject = v => v !== null && typeof v === "object";

/** The value at a path (array of keys and indexes), or undefined. */
export function getIn(info, path) {
  let cur = info;
  for (const key of path) {
    if (!isObject(cur) || !Object.prototype.hasOwnProperty.call(cur, key)) return undefined;
    cur = cur[key];
  }
  return cur;
}

const FORBIDDEN_KEYS = new Set(["__proto__", "constructor", "prototype"]);

function walkTo(root, path, create) {
  let cur = root;
  for (const key of path) {
    if (FORBIDDEN_KEYS.has(key)) throw new Error(`Refusing to patch through "${key}".`);
    if (!isObject(cur[key])) {
      if (!create) return undefined;
      cur[key] = {};
    }
    cur = cur[key];
  }
  return cur;
}

/** Apply patches to a copy of info and return it; the argument is not touched.
    ops: { op: "set", path, value } | { op: "remove", path } | { op: "merge", path, value }
    "set" creates missing objects along the path; "merge" shallow-merges an
    object into the one at path (created when absent); "remove" deletes a key
    or splices an array index and ignores a path that is not there. */
export function patchInfo(info, ops) {
  const out = cloneInfo(info);
  for (const { op, path, value } of ops) {
    if (!Array.isArray(path) || !path.length) throw new Error("A patch needs a non-empty path.");
    const parent = walkTo(out, path.slice(0, -1), op !== "remove");
    const key = path[path.length - 1];
    if (FORBIDDEN_KEYS.has(key)) throw new Error(`Refusing to patch "${key}".`);
    if (op === "set") parent[key] = cloneInfo(value === undefined ? null : value);
    else if (op === "merge") parent[key] = Object.assign(isObject(parent[key]) ? parent[key] : {}, cloneInfo(value));
    else if (op === "remove") {
      if (!parent) continue;
      if (Array.isArray(parent)) { if (key >= 0 && key < parent.length) parent.splice(key, 1); }
      else delete parent[key];
    } else throw new Error(`Unknown patch op "${op}".`);
  }
  return out;
}

// ── Layouts ──────────────────────────────────────────────────────────────

/** Keys of the app's OrientationRepresentations. A dict with any of them is a
    layout; the app decodes `assets` with decodeIfPresent, so a layout without
    it loads and draws nothing. (Same set as link_health.py's LAYOUT_KEYS.) */
export const LAYOUT_KEYS = ["assets", "items", "screens", "mappingSize", "extendedEdges",
  "translucent", "gameScreenFrame", "backgroundAnimation"];

/** Every layout in a representations tree, which nests device → display type
    → orientation: [{ path: ["iphone","edgeToEdge","portrait"], layout }].
    Anything with a layout key is a layout, wherever it sits, as the apps read it.
    `assets` of a layout may be missing or not an object; that is the caller's to judge. */
export function listLayouts(representations, path = []) {
  if (!isObject(representations) || Array.isArray(representations)) return [];
  if (LAYOUT_KEYS.some(k => Object.prototype.hasOwnProperty.call(representations, k))) {
    return [{ path, layout: representations }];
  }
  const out = [];
  for (const key of Object.keys(representations)) out.push(...listLayouts(representations[key], path.concat(String(key))));
  return out;
}

// ── Inputs ───────────────────────────────────────────────────────────────

/** The input names to offer for a skin's gameTypeIdentifier, from the parsed
    inputs.json: [{ group, inputs }] in picker order (buttons, directions,
    start/select, sticks, frontend). A game type the table has no buttons for
    gets the table's `default` set. Names outside the table are still valid
    input; the picker accepts free text too. */
export function knownInputs(table, gameTypeIdentifier) {
  const id = String(gameTypeIdentifier || "").toLowerCase();
  const key = Object.keys(table.gameTypes || {}).find(k => k.toLowerCase() === id);
  const entry = key ? table.gameTypes[key] : null;
  return [
    { group: "buttons", inputs: (entry && entry.buttons) || table.default || [] },
    { group: "directions", inputs: table.directions || [] },
    { group: "start / select", inputs: table.startSelect || [] },
    { group: "sticks", inputs: table.sticks || [] },
    { group: "frontend", inputs: table.frontend || [] },
  ];
}
