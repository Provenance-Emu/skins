/* EmuSkins — skin format 2.0, feature names and input tables (docs/js/skin2/).

   Port of SkinKit's Skin2Features.swift. Feature names (section 1) are the unit of detection: a skin lists what
   it uses in `requires`; a reader that lacks one renders the baked classic skin instead. */

import type { Document, Layout, Node, Paint, Patch } from "./model.js";
import { preorder } from "./model.js";
import type { JSONValue } from "./json.js";
import { isObject } from "./json.js";

export const ALL_FEATURES: string[] = [
  "layout.anchors", "layout.stack", "layout.grid", "layout.repeat",
  "shapes.parametric", "shapes.path",
  "paint.gradients", "paint.image",
  "effects.shadow", "effects.blur", "effects.blend", "effects.ci",
  "materials", "text",
  "parts", "tokens", "themes", "variants", "states",
  "controls.dpad", "controls.thumbstick", "controls.touchSurface",
  "parts.std@2.0",
];

/** The features this TypeScript renderer draws. `effects.ci` is not here: Core Image entries are skipped, so a
    skin that lists it falls back to its bake. */
export const SUPPORTED_FEATURES: ReadonlySet<string> = new Set([
  "layout.anchors", "layout.stack", "layout.grid", "layout.repeat",
  "shapes.parametric", "shapes.path",
  "paint.gradients", "paint.image",
  "effects.shadow", "effects.blur", "effects.blend",
  "materials", "text",
  "parts", "parts.std@2.0", "tokens", "themes", "variants", "states",
  "controls.dpad", "controls.thumbstick", "controls.touchSurface",
]);

/** True when this renderer draws every feature in `requires`. */
export function supports(requires: string[]): boolean {
  return requires.every((r) => SUPPORTED_FEATURES.has(r));
}

/** The features `source` uses. `documents` are its decoded forms (the base and each theme and variant), whose
    content may differ; the source supplies tokens, themes, parts and variants, which decoding removes. */
export function usedFeatures(source: JSONValue, documents: Document[]): Set<string> {
  const used = new Set<string>();
  if (isObject(source)) {
    for (const key of ["tokens", "themes", "variants"] as const) {
      const v = source[key];
      if (isObject(v) && Object.keys(v).length > 0) used.add(key);
    }
  }
  scanUses(source, used);
  for (const doc of documents) preorder(doc.root, (n) => scanNode(n, used));
  return used;
}

function scanUses(v: JSONValue, used: Set<string>): void {
  if (isObject(v)) {
    if (typeof v.use === "string") {
      used.add("parts");
      if (v.use.startsWith("std.")) used.add("parts.std@2.0");
    }
    for (const value of Object.values(v)) scanUses(value, used);
  } else if (Array.isArray(v)) {
    for (const value of v) scanUses(value, used);
  }
}

function scanLayout(l: Layout | undefined, used: Set<string>): void {
  if (l?.anchor !== undefined || l?.offset !== undefined) used.add("layout.anchors");
}

function scanPaints(paints: Paint[], used: Set<string>): void {
  for (const p of paints) {
    if (p.type === "linear" || p.type === "radial" || p.type === "angular") used.add("paint.gradients");
    else if (p.type === "image") used.add("paint.image");
  }
}

function scanPatch(p: Patch, used: Set<string>): void {
  scanLayout(p.layout, used);
  scanPaints(p.fills ?? [], used);
}

function scanNode(n: Node, used: Set<string>): void {
  scanLayout(n.layout, used);
  for (const w of n.when) scanPatch(w.patch, used);
  if (n.stack) used.add("layout.stack");
  if (n.grid) used.add("layout.grid");
  if (n.repeat) used.add("layout.repeat");
  if (n.shape) used.add(n.shape.kind === "path" ? "shapes.path" : "shapes.parametric");
  scanPaints(n.fills, used);
  for (const e of n.effects) {
    used.add(({ shadow: "effects.shadow", blur: "effects.blur", blend: "effects.blend", ci: "effects.ci" } as const)[e.type]);
  }
  if (n.material) used.add("materials");
  if (n.type === "text") used.add("text");
  if (Object.keys(n.states).length > 0) {
    used.add("states");
    for (const s of Object.values(n.states)) for (const p of s.patch) scanPatch(p, used);
  }
  if (n.kind === "dpad") used.add("controls.dpad");
  else if (n.kind === "thumbstick") used.add("controls.thumbstick");
  else if (n.kind === "touchSurface") used.add("controls.touchSurface");
}

// ── Inputs per game type (6.1) ───────────────────────────────────────────

/** Inputs every game type accepts: directions, start/select. */
export const COMMON_INPUTS: ReadonlySet<string> = new Set(["up", "down", "left", "right", "start", "select"]);

/** `action` control inputs (the Provenance OverlayAction list that Delta understands, plus Provenance's own). */
export const ACTION_INPUTS: ReadonlySet<string> = new Set([
  "menu", "quickSave", "quickLoad", "fastForward", "toggleFastForward", "toggleAltRepresentations",
  "toggleKeyboard", "screenshot", "rewind", "pause", "reset", "restart",
]);

/** `touchSurface` inputs. */
export const TOUCH_SURFACE_INPUTS: ReadonlySet<string> = new Set(["touchScreen", "pointer", "lightGun", "trackpad"]);

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

const SYSTEM_TABLE: Array<[string[], string[]]> = [
  [["nes", "fds", "famicom"], ["a", "b"]],
  [["snes", "sfc"], ["a", "b", "x", "y", "l", "r"]],
  [["gb", "gbc"], ["a", "b"]],
  [["gba"], ["a", "b", "l", "r"]],
  [["n64"], ["a", "b", "l", "r", "z", "cUp", "cDown", "cLeft", "cRight", "leftThumbstick", "analogStick"]],
  [["ds", "nds"], ["a", "b", "x", "y", "l", "r", "touchScreen"]],
  [["3ds"], ["a", "b", "x", "y", "l", "r", "zl", "zr", "home", "leftThumbstick", "rightThumbstick", "cStick", "touchScreen"]],
  [["genesis", "md", "megadrive", "segacd", "mcd", "megacd", "32x", "sega32x"], ["a", "b", "c", "x", "y", "z", "mode"]],
  [["ms", "mastersystem", "gg", "gamegear", "sg1000"], ["a", "b"]],
  [["saturn", "ss"], ["a", "b", "c", "x", "y", "z", "l", "r"]],
  [["psx", "ps1"], ["cross", "circle", "square", "triangle", "l1", "l2", "r1", "r2", "l3", "r3", "leftThumbstick", "rightThumbstick", "analog"]],
  [["psp"], ["cross", "circle", "square", "triangle", "l", "r", "leftThumbstick"]],
  [["dc", "dreamcast"], ["a", "b", "x", "y", "l", "r", "leftThumbstick"]],
  [["gamecube", "gc", "ngc", "gcn"], ["a", "b", "x", "y", "z", "l", "r", "leftThumbstick", "rightThumbstick", "cStick", "mic"]],
  [["wii"], ["a", "b", "one", "two", "plus", "minus", "home", "c", "z", "nunchukStick", "pointer", "x", "y", "l", "r", "zl", "zr", "leftThumbstick", "rightThumbstick"]],
  [["intellivision"], [...DIGITS, "clear", "enter", "topAction", "bottomLeftAction", "bottomRightAction"]],
  [["colecovision", "coleco"], [...DIGITS, "*", "#", "leftAction", "rightAction"]],
];

const SYSTEMS: Map<string, Set<string>> = new Map(SYSTEM_TABLE.flatMap(([names, inputs]) => names.map((n) => [n, new Set(inputs)] as const)));

/** com.rileytestut.delta.game.snes → snes. */
export function normalizeGameType(gameType: string): string {
  const parts = gameType.toLowerCase().split(".").filter((s) => s.length > 0);
  const last = parts.length > 0 ? parts[parts.length - 1] : gameType.toLowerCase();
  return last.replace(/[-_ ]/g, "");
}

/** The inputs a game type accepts besides COMMON_INPUTS and ACTION_INPUTS, or undefined when the table doesn't
    know it. */
export function inputsForGameType(gameType: string): ReadonlySet<string> | undefined {
  return SYSTEMS.get(normalizeGameType(gameType));
}
