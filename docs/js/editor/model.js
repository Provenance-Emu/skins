/* EmuSkins — what the editor knows about an info.json (docs/js/editor/).

   Helpers that read a skin's layouts and build patchInfo ops for the edits the
   panels and the canvas make. Nothing here rewrites the info.json object: every
   edit is a list of ops on one path, so the rest of the file (keyboardOverlay,
   haptic, themes, keys nobody has heard of) is left alone.

   Pure, no DOM.
*/

import { listLayouts, getIn, cloneInfo } from "../skin/info.js";

export const DEVICES = ["iphone", "ipad"];
export const DISPLAY_TYPES = ["standard", "edgeToEdge", "splitView"];
export const ORIENTATIONS = ["portrait", "landscape"];
export const SIZE_KEYS = ["resizable", "small", "medium", "large"];

// ── Traits (the device frame picker) ─────────────────────────────────────

/** Every layout of the base `representations`: [{ key: "iphone/edgeToEdge/portrait", path: [...], label }].
    The path is relative to `representations`; variant trees (themes, alt, game) are not editable here. */
export function listTraits(info) {
  return listLayouts(info && info.representations).map(({ path }) => ({
    key: path.join("/"), path, label: path.join(" · "),
  }));
}

export const layoutPathOf = trait => ["representations", ...(typeof trait === "string" ? trait.split("/") : trait.path)];

/** The layout object for a trait key, or null. */
export function getLayout(info, traitKey) {
  const layout = getIn(info, layoutPathOf(traitKey));
  return layout && typeof layout === "object" ? layout : null;
}

/** Trait keys that can still be added: device × display type × orientation, minus the existing ones. */
export function missingTraits(info) {
  const have = new Set(listTraits(info).map(t => t.key));
  const out = [];
  for (const d of DEVICES) for (const t of DISPLAY_TYPES) for (const o of ORIENTATIONS) {
    const key = `${d}/${t}/${o}`;
    if (!have.has(key)) out.push(key);
  }
  return out;
}

/** Ops that add layout `toKey` as a copy of the layout at `fromKey`. */
export function addLayoutOps(info, fromKey, toKey) {
  const from = getLayout(info, fromKey);
  if (!from) throw new Error(`No layout ${fromKey}.`);
  if (getLayout(info, toKey)) throw new Error(`${toKey} already exists.`);
  return [{ op: "set", path: layoutPathOf(toKey), value: cloneInfo(from) }];
}

// ── Frames ───────────────────────────────────────────────────────────────

/** Ops that set an item's frame. Merged into the existing frame object, so unknown keys in it stay. */
export const itemFrameOps = (traitKey, index, frame) =>
  [{ op: "merge", path: [...layoutPathOf(traitKey), "items", index, "frame"], value: pickFrame(frame) }];

/** Ops that set a screen's outputFrame or inputFrame. */
export const screenFrameOps = (traitKey, index, which, frame) =>
  [{ op: "merge", path: [...layoutPathOf(traitKey), "screens", index, which], value: pickFrame(frame) }];

const pickFrame = f => ({ x: f.x, y: f.y, width: f.width, height: f.height });

export const EDGE_KEYS = ["top", "bottom", "left", "right"];
export const pickEdges = e => Object.fromEntries(EDGE_KEYS.map(k => [k, Number(e && e[k]) || 0]));

/** Ops that set a single field at a path under a layout (mappingSize.width, items/2/extendedEdges, ...). */
export const layoutFieldOps = (traitKey, subPath, value) => [{ op: "set", path: [...layoutPathOf(traitKey), ...subPath], value }];

// ── Items ────────────────────────────────────────────────────────────────

export const DEFAULT_ITEM_SIZE = 60;

/** Ops that append a new button, centered in the mapping frame. */
export function addItemOps(info, traitKey) {
  const layout = getLayout(info, traitKey) || {};
  const m = layout.mappingSize || { width: 400, height: 800 };
  const item = {
    inputs: [],
    frame: { x: Math.round((m.width - DEFAULT_ITEM_SIZE) / 2), y: Math.round((m.height - DEFAULT_ITEM_SIZE) / 2), width: DEFAULT_ITEM_SIZE, height: DEFAULT_ITEM_SIZE },
    extendedEdges: { top: 4, bottom: 4, left: 4, right: 4 },
  };
  return [{ op: "set", path: [...layoutPathOf(traitKey), "items"], value: [...(layout.items || []), item] }];
}

/** Ops that remove item `index`. */
export const removeItemOps = (traitKey, index) => [{ op: "remove", path: [...layoutPathOf(traitKey), "items", index] }];

/** "a, b ,c" → ["a","b","c"]. */
export const parseInputs = text => String(text || "").split(/[\s,]+/).map(s => s.trim()).filter(Boolean);

/** An item's inputs for display. Array inputs are the editable kind; the object form
    (a d-pad's {"up": "up", ...}) is shown but written back untouched. */
export function describeInputs(inputs) {
  if (Array.isArray(inputs)) return { editable: true, text: inputs.join(", ") };
  if (inputs && typeof inputs === "object") {
    return { editable: false, text: Object.entries(inputs).map(([k, v]) => `${k}: ${v}`).join(", ") };
  }
  return { editable: true, text: "" };
}

// ── Skin fields, export, environment ─────────────────────────────────────

export const skinFieldOps = (key, value) => [{ op: "set", path: [key], value }];

/** `<identifier>.deltaskin`, or `.manicskin` for a public.aoshuang.game.* game type. */
export function exportFileName(info) {
  const ext = String(info && info.gameTypeIdentifier || "").startsWith("public.aoshuang.game.") ? "manicskin" : "deltaskin";
  const base = String(info && info.identifier || "skin").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^\.+/, "") || "skin";
  return `${base}.${ext}`;
}

/** Manic rejects an import whose identifier it already has, so an edited copy needs its own. */
export function identifierWarning(info, originalIdentifier) {
  if (originalIdentifier && info && info.identifier === originalIdentifier) {
    return "Same identifier as the skin you opened. Manic will not import a second skin with it; change it to install this beside the original.";
  }
  return null;
}

/** An iPhone or iPod browser: the editor opens read-only there. iPads (which report as Macintosh) and desktops are not. */
export const isPhone = ua => /iPhone|iPod/.test(String(ua || ""));

/** Artwork the editor can swap in: how Delta and Manic draw it. */
export function artworkFileProblem(name) {
  const ext = String(name).split(".").pop().toLowerCase();
  if (["png", "pdf", "jpg", "jpeg"].includes(ext)) return null;
  if (ext === "svg") return "Delta and Manic cannot draw SVG artwork. Use a PDF or PNG.";
  return "Artwork must be a PDF or PNG.";
}
