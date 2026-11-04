/* EmuSkins — Delta/Manic skin → RetroArch overlay converter (pure logic).

   An ES module with no DOM or network code: it turns a parsed info.json and
   the mapping table (retroarch-input-map.json) into the text of a RetroArch
   overlay .cfg plus a list of images the caller must render. The browser page
   (docs/js/retroarch-page.js) renders them with pdf.js and a canvas;
   tests/js/retroarch_convert.test.js runs the same code under Node.

   RetroArch overlay format, as read by tasks/task_overlay.c:
     overlays = N
     overlayK_name = "landscape" | "portrait"     auto-rotate matches on these words
     overlayK_overlay = image.png                 one image per overlay, next to the .cfg
     overlayK_full_screen = true                  stretch over the whole screen, not the video
     overlayK_normalized = true                   desc coordinates are 0..1 of the overlay rect
     overlayK_aspect_ratio = w/h                  the screen ratio the layout assumes (Auto-Scale)
     overlayK_rect = "x,y,w,h"                    where on the screen the image goes (0..1)
     overlayK_descs = M
     overlayK_descJ = "input,x,y,shape,rx,ry"     center x,y and half extents rx,ry, all 0..1
     overlayK_descJ_overlay = image.png           per-button image (thumbstick caps)
     overlayK_descJ_movable = true                the image follows the finger
     overlayK_descJ_next_target = "name"          for overlay_next
     overlayK_descJ_reach_x/_reach_y = 0          removes the hitbox (hidden rotate descs)
   Inputs join with '|' ("a|b", "up|left"). Any name in RetroArch's
   input_config_bind_map works; the map file holds the ones skins use.
*/

// ── info.json ────────────────────────────────────────────────────────────

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

// ── Systems and inputs ───────────────────────────────────────────────────

/** Our system key for a skin: the map's gameTypes table, else the last
    component of gameTypeIdentifier through gameTypeSuffixes. */
export function systemOf(info, map) {
  const id = String((info && info.gameTypeIdentifier) || "").toLowerCase();
  const types = map.gameTypes || {};
  for (const k of Object.keys(types)) if (k.toLowerCase() === id) return types[k];
  const last = id.split(".").pop();
  return (map.gameTypeSuffixes || {})[last] || last || "unknown";
}

const has = (o, k) => o != null && Object.prototype.hasOwnProperty.call(o, k);

/** RetroArch bind for a skin token: a string, null (known, nothing to bind
    to) or undefined (unknown token). */
export function bindFor(token, system, map) {
  const sys = (map.systems || {})[system] || {};
  if (has(sys.map, token)) return sys.map[token];
  if (has(sys.aliases, token)) return bindFor(sys.aliases[token], system, map);
  if (has(map.common, token)) return map.common[token];
  const def = (map.systems || {}).default || {};
  if (has(def.map, token)) return def.map[token];
  return undefined;
}

function reasonFor(token, system, map) {
  if (has(map.unconvertibleReasons, token)) return map.unconvertibleReasons[token];
  if (bindFor(token, system, map) === undefined) return `No RetroArch bind known for "${token}" on ${system}.`;
  return `"${token}" has no RetroArch equivalent.`;
}

const LEFT_ANALOG = { up: "l_y_minus", down: "l_y_plus", left: "l_x_minus", right: "l_x_plus" };
const RIGHT_ANALOG = { up: "r_y_minus", down: "r_y_plus", left: "r_x_minus", right: "r_x_plus" };
const sameDirections = (binds, table) => ["up", "down", "left", "right"].every(d => binds[d] === table[d]);

// ── Geometry ─────────────────────────────────────────────────────────────

function edges(rep, item) {
  // Delta: the representation's extendedEdges are the default for every
  // item; an item's own extendedEdges override per side.
  const base = rep.extendedEdges || {};
  const own = item.extendedEdges || {};
  const pick = k => (own[k] != null ? own[k] : base[k] != null ? base[k] : 0);
  return { top: pick("top"), bottom: pick("bottom"), left: pick("left"), right: pick("right") };
}

/** The touch area of an item in mapping points: frame plus extended edges. */
export function hitbox(rep, item) {
  const f = item.frame, e = edges(rep, item);
  return {
    x: f.x - e.left, y: f.y - e.top,
    width: Math.max(0, f.width + e.left + e.right),
    height: Math.max(0, f.height + e.top + e.bottom),
  };
}

const n6 = v => (Math.round(v * 1e6) / 1e6).toFixed(6);

/** "x,y,shape,rx,ry" for a rect in mapping points: center and half extents, normalized. */
function descGeometry(rect, mapping, shape) {
  const cx = (rect.x + rect.width / 2) / mapping.width;
  const cy = (rect.y + rect.height / 2) / mapping.height;
  return `${n6(cx)},${n6(cy)},${shape},${n6(rect.width / 2 / mapping.width)},${n6(rect.height / 2 / mapping.height)}`;
}

function screenFrames(rep) {
  const out = [];
  for (const s of rep.screens || []) if (s && s.outputFrame) out.push(s.outputFrame);
  if (!out.length && rep.gameScreenFrame) out.push(rep.gameScreenFrame);
  return out;
}

// ── Representations ──────────────────────────────────────────────────────

export const DISPLAY_PREFERENCE = ["edgeToEdge", "standard", "splitView", "stageManager", "externalDisplay"];

/** Every (device, displayType, orientation) with artwork in a representations tree. */
export function listRepresentations(info, key = "representations") {
  const out = [];
  const reps = (info && info[key]) || {};
  for (const device of Object.keys(reps)) {
    for (const displayType of Object.keys(reps[device] || {})) {
      for (const orientation of Object.keys(reps[device][displayType] || {})) {
        const rep = reps[device][displayType][orientation];
        if (rep && rep.assets && rep.mappingSize) out.push({ device, displayType, orientation, rep });
      }
    }
  }
  return out;
}

/** The landscape and portrait layouts to convert for a device and display
    type, each falling back through the device's other display types. */
export function pickRepresentations(info, opts, key = "representations") {
  const all = listRepresentations(info, key);
  const notes = [];
  let device = opts.device;
  if (!all.some(r => r.device === device)) {
    const other = all[0] && all[0].device;
    if (!other) return { device: null, portrait: null, landscape: null, notes };
    if (key === "representations") notes.push(`No ${device} layouts; using ${other}.`);
    device = other;
  }
  const order = [opts.displayType].concat(DISPLAY_PREFERENCE).filter((v, i, a) => v && a.indexOf(v) === i);
  const pick = orientation => {
    for (const dt of order) {
      const hit = all.find(r => r.device === device && r.displayType === dt && r.orientation === orientation);
      if (hit) {
        if (dt !== opts.displayType && key === "representations") notes.push(`${orientation}: no ${opts.displayType} layout, using ${dt}.`);
        return hit;
      }
    }
    return null;
  };
  return { device, landscape: pick("landscape"), portrait: pick("portrait"), notes };
}

/** The artwork file for a layout: a resizable PDF/SVG first, else the largest raster. */
export function assetName(rep) {
  const a = rep.assets || {};
  return a.resizable || a.large || a.medium || a.small || null;
}

/** Find artwork in the archive the way the apps do: exact path, then the
    same file name anywhere ignoring case, then the same stem as .pdf/.png/.svg. */
export function resolveAsset(entries, name) {
  if (!name) return null;
  if (entries.includes(name)) return name;
  const base = name.split("/").pop().toLowerCase();
  const stem = base.replace(/\.[^.]+$/, "");
  let hit = entries.find(e => e.split("/").pop().toLowerCase() === base);
  if (hit) return hit;
  for (const ext of [".pdf", ".png", ".svg"]) {
    hit = entries.find(e => e.split("/").pop().toLowerCase() === stem + ext);
    if (hit) return hit;
  }
  return null;
}

// ── Conversion ───────────────────────────────────────────────────────────

/** Screen ratios (width/height in portrait) the layouts are drawn for. */
export const SCREEN_ASPECTS = { iphone_edgeToEdge: 9 / 19.5, iphone_standard: 9 / 16, ipad: 3 / 4, tv: 9 / 16 };

export function screenAspectFor(device, displayType) {
  if (device === "ipad") return SCREEN_ASPECTS.ipad;
  if (device === "tv" || device === "appletv") return SCREEN_ASPECTS.tv;
  return displayType === "standard" ? SCREEN_ASPECTS.iphone_standard : SCREEN_ASPECTS.iphone_edgeToEdge;
}

export const slugify = s => String(s || "skin").normalize("NFKD").replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 60) || "skin";

/**
 * Convert a parsed info.json.
 *   opts.inputMap     the parsed retroarch-input-map.json (required)
 *   opts.device       "iphone" | "ipad"            (default iphone)
 *   opts.displayType  "edgeToEdge" | "standard" | … (default edgeToEdge)
 *   opts.screenAspect portrait width/height of the screen the layout is for (default from device)
 *   opts.name         folder/file base name (default: the skin's name, slugified)
 *   opts.entries      file names in the skin archive; a layout whose artwork is not
 *                     among them is skipped (listed in `skipped`) instead of emitted
 * Returns { cfg, readme, images, descs, unconvertible, skipped, notes, name, system, device, layouts }.
 *   images: [{ file, kind: "overlay"|"thumbstick", asset, width, height, clearRects, innerWidth?, innerHeight? }]
 */
export function convert(info, opts) {
  opts = Object.assign({ device: "iphone", displayType: "edgeToEdge" }, opts || {});
  const map = opts.inputMap;
  if (!map || !map.common) throw new Error("convert() needs opts.inputMap (retroarch-input-map.json)");
  const system = systemOf(info, map);
  let name = slugify(opts.name || info.name || info.identifier);

  const base = pickRepresentations(info, opts);
  const notes = base.notes.slice();
  const device = base.device;
  if (device === "ipad" && !/ipad$/i.test(name)) name += "-ipad"; // one preset per device class
  if ((device === "tv" || device === "appletv") && !/tv$/i.test(name)) name += "-tv";
  const unconvertible = [], skipped = [], descs = [], images = [], layouts = [];
  const empty = { cfg: "", readme: "", images, descs, unconvertible, skipped, notes, name, system, device, layouts };
  if (!device) { notes.push("The skin has no layouts with artwork."); return empty; }
  if (device === "tv" || device === "appletv") {
    notes.push("TV layouts are artwork only: RetroArch on Apple TV takes input from a controller, so the buttons in this overlay are decoration.");
  }
  const inArchive = asset => !opts.entries || !!resolveAsset(opts.entries, asset);

  const alt = pickRepresentations(info, Object.assign({}, opts, { device }), "altRepresentations");
  const hasAlt = !!(alt.landscape || alt.portrait);
  if (info.gameOverrides) notes.push("Per-game overrides (gameOverrides) are not converted; the base layout is used.");

  // Overlay plan: landscape then portrait, then the alternate pair.
  const plan = [];
  for (const [set, picked] of [["", base], ["-alt", alt]]) {
    for (const orientation of ["landscape", "portrait"]) {
      const chosen = picked[orientation];
      if (!chosen) continue;
      const art = assetName(chosen.rep);
      if (!inArchive(art)) {
        skipped.push({ overlayName: orientation + set, displayType: chosen.displayType, asset: art,
          reason: `The archive has no "${art}", so this layout cannot be drawn.` });
        continue;
      }
      plan.push({ orientation, chosen, set, overlayName: orientation + set });
    }
  }
  if (!plan.length) { notes.push("No landscape or portrait layout with artwork for this device."); return empty; }
  const named = n => plan.find(p => p.overlayName === n);
  const rotateTarget = p => {
    const other = p.orientation === "landscape" ? "portrait" : "landscape";
    return (named(other + p.set) || named(other) || {}).overlayName || null;
  };
  const altTarget = p => (named(p.orientation + (p.set ? "" : "-alt")) || {}).overlayName || null;

  const sysInfo = (map.systems || {})[system];
  const lines = [];
  lines.push(`# ${info.name || name} — RetroArch overlay`);
  lines.push(`# Converted from a ${/manic/i.test(String(info.identifier)) ? ".manicskin" : ".deltaskin"} by EmuSkins (https://emuskins.com/retroarch.html).`);
  if (info.identifier) lines.push(`# Skin identifier: ${info.identifier}`);
  lines.push(`# System: ${system}${sysInfo && sysInfo.assumes ? ` — buttons follow ${sysInfo.assumes}` : ""}.`);
  lines.push(`# Layouts: ${device}, ${plan.map(p => `${p.overlayName} (${p.chosen.displayType})`).join(", ")}.`);
  lines.push("# Auto-Rotate Overlay (on by default on iOS) switches landscape/portrait with the device.");
  lines.push("");
  lines.push(`overlays = ${plan.length}`);
  lines.push("");

  plan.forEach((p, k) => {
    const { orientation, chosen, set, overlayName } = p;
    const rep = chosen.rep;
    const mapping = rep.mappingSize;
    const screenAspect = opts.screenAspect || screenAspectFor(device, chosen.displayType);
    // Delta scales the image to the screen width and keeps its aspect, so a
    // portrait layout shorter than the screen (a 320x240 controller strip)
    // sits at the bottom with the game above it.
    const skinAspect = mapping.width / mapping.height;
    const screenRatio = orientation === "portrait" ? screenAspect : 1 / screenAspect;
    let rect = null;
    if (orientation === "portrait" && skinAspect > screenRatio * 1.02) {
      const h = screenRatio / skinAspect;
      rect = { x: 0, y: 1 - h, w: 1, h };
    }

    const imgFile = `${name}-${overlayName}.png`;
    const asset = assetName(rep);
    const frames = screenFrames(rep);
    const translucent = rep.translucent === true;
    images.push({
      file: imgFile, kind: "overlay", asset, orientation, overlayName,
      width: mapping.width, height: mapping.height,
      // The apps draw the game over the skin unless it is translucent; the
      // RetroArch overlay sits on top of the video, so that area must be clear.
      clearRects: translucent ? [] : frames.slice(),
    });

    const pre = `overlay${k}`;
    lines.push(`${pre}_name = "${overlayName}"`);
    lines.push(`${pre}_overlay = "${imgFile}"`);
    lines.push(`${pre}_full_screen = true`);
    lines.push(`${pre}_normalized = true`);
    lines.push(`${pre}_aspect_ratio = ${n6(screenRatio)}`);
    if (rect) lines.push(`${pre}_rect = "${n6(rect.x)},${n6(rect.y)},${n6(rect.w)},${n6(rect.h)}"`);

    const out = [];
    let d = 0;
    const items = rep.items || [];
    const where = (idx) => `${overlayName} item ${idx + 1}`;
    const push = (line) => out.push(`${pre}_desc${d}${line}`);

    items.forEach((item, idx) => {
      if (!item || !item.frame) return;
      const box = hitbox(rep, item);
      const inputs = item.inputs;

      if (Array.isArray(inputs)) {
        const ok = [], bad = [];
        for (const t of inputs) {
          const b = bindFor(t, system, map);
          if (b === "overlay_next") {
            // toggleAltRepresentations: jump to this layout's alternate (or back).
            const target = altTarget(p);
            if (target) ok.push(b); else bad.push(t);
            continue;
          }
          if (b) ok.push(b); else bad.push(t);
        }
        for (const t of bad) unconvertible.push({ where: where(idx), input: t, reason: reasonFor(t, system, map) });
        if (!ok.length) return;
        const bind = ok.filter((v, i, a) => a.indexOf(v) === i).join("|");
        const shape = bind === "analog_left" || bind === "analog_right" ? "radial" : "rect";
        push(` = "${bind},${descGeometry(box, mapping, shape)}"`);
        if (bind === "overlay_next") push(`_next_target = "${altTarget(p)}"`);
        descs.push({ overlayName, inputs: inputs.slice(), bind, kind: bind === "overlay_next" ? "toggle" : "button" });
        d++;
        return;
      }

      if (inputs && typeof inputs === "object") {
        const dirs = {}, bad = [];
        for (const dir of ["up", "down", "left", "right"]) {
          const t = inputs[dir];
          if (t == null) continue;
          const b = bindFor(t, system, map);
          if (b) dirs[dir] = b; else bad.push(t);
        }
        for (const t of bad) unconvertible.push({ where: where(idx), input: t, reason: reasonFor(t, system, map) });
        if (!Object.keys(dirs).length) return;

        // A stick is an item with a thumbstick image or stick-named tokens.
        // Four C buttons resolve to right-stick binds too, but they are
        // buttons: each gets a cell with full deflection, not a radial stick.
        const tokens = Object.values(inputs).filter(t => typeof t === "string");
        const isThumb = !!item.thumbstick;
        const stickish = isThumb || tokens.some(t => /analog|thumb|stick/i.test(t));
        let bind = null;
        if (stickish) {
          bind = sameDirections(dirs, RIGHT_ANALOG) || tokens.some(t => /^right/i.test(t)) ? "analog_right" : "analog_left";
        }
        if (bind) {
          push(` = "${bind},${descGeometry(box, mapping, "radial")}"`);
          if (isThumb && item.thumbstick.name && !inArchive(item.thumbstick.name)) {
            notes.push(`Thumbstick image "${item.thumbstick.name}" is not in the archive; the stick has no cap image.`);
          } else if (isThumb && item.thumbstick.name) {
            const thumbFile = `${name}-${overlayName}-thumb${d}.png`;
            push(`_overlay = "${thumbFile}"`);
            push(`_movable = true`);
            images.push({
              file: thumbFile, kind: "thumbstick", asset: item.thumbstick.name, orientation, overlayName,
              width: box.width, height: box.height,
              innerWidth: item.thumbstick.width || box.width, innerHeight: item.thumbstick.height || box.height,
              clearRects: [],
            });
          }
          descs.push({ overlayName, inputs: Object.assign({}, inputs), bind, kind: "analog" });
          d++;
          return;
        }

        // A four-way pad: nine rects on a 3x3 grid of the hitbox, the way
        // Delta reads it and the stock RetroArch overlays draw it. Corners
        // press two directions; the centre is empty.
        const cw = box.width / 3, ch = box.height / 3;
        const cells = [
          [0, 0, ["up", "left"]], [1, 0, ["up"]], [2, 0, ["up", "right"]],
          [0, 1, ["left"]], [2, 1, ["right"]],
          [0, 2, ["down", "left"]], [1, 2, ["down"]], [2, 2, ["down", "right"]],
        ];
        for (const [cx, cy, ds] of cells) {
          const binds = ds.map(dd => dirs[dd]).filter(Boolean);
          if (binds.length !== ds.length) continue; // a missing direction drops its cells
          const cell = { x: box.x + cx * cw, y: box.y + cy * ch, width: cw, height: ch };
          push(` = "${binds.join("|")},${descGeometry(cell, mapping, "rect")}"`);
          d++;
        }
        descs.push({ overlayName, inputs: Object.assign({}, inputs), bind: Object.values(dirs).join("/"), kind: "dpad" });
        return;
      }
      unconvertible.push({ where: where(idx), input: "(no inputs)", reason: "Item has no inputs." });
    });

    // A hidden overlay_next tells auto-rotate where the other orientation
    // lives. reach 0 removes its hitbox so it can't be tapped.
    const rot = rotateTarget(p);
    if (rot) {
      push(` = "overlay_next,0.500000,0.000000,rect,0.001000,0.001000"`);
      push(`_next_target = "${rot}"`);
      push(`_reach_x = 0.0`);
      push(`_reach_y = 0.0`);
      d++;
    }

    lines.push(`${pre}_descs = ${d}`);
    lines.push(...out);
    lines.push("");
    layouts.push({
      orientation, overlayName, set: set ? "alt" : "base", displayType: chosen.displayType, mapping, asset, rect,
      translucent, screens: frames.length, items: items.length, descs: d,
    });
  });

  if (hasAlt) notes.push("The alternate layouts (altRepresentations) are extra overlays; the skin's toggle button switches to them.");
  const result = { cfg: lines.join("\n"), images, descs, unconvertible, skipped, notes, name, system, device, layouts };
  result.readme = readmeText(result, info, sysInfo);
  return result;
}

/** README.txt for the overlay folder: the menu taps and what did not convert. */
export function readmeText(result, info, sysInfo) {
  const L = [];
  L.push(`${info.name || result.name} — RetroArch overlay`);
  L.push("Converted by EmuSkins (https://emuskins.com/retroarch.html).");
  L.push("");
  L.push("Install on iOS");
  L.push(`  1. Move this whole folder (${result.name}) to Files > On My iPhone > RetroArch > RetroArch > overlays.`);
  L.push(`  2. In RetroArch: Settings > On-Screen Display > On-Screen Overlay > Overlay Preset > ${result.name}/${result.name}.cfg.`);
  L.push("  3. Auto-Rotate Overlay (on by default) switches landscape and portrait with the device.");
  L.push("     Set Overlay Opacity to 1.0 if the artwork looks faded.");
  L.push("");
  L.push("Other platforms: put the folder in RetroArch's overlays directory (Settings > Directory > Overlays).");
  L.push("");
  if (sysInfo && sysInfo.assumes) {
    L.push(`Buttons follow ${sysInfo.assumes}. On another core, remap in Quick Menu > Controls.`);
    L.push("");
  }
  if (result.skipped.length) {
    L.push("Layouts left out:");
    for (const s of result.skipped) L.push(`  - ${s.overlayName} (${s.displayType}): ${s.reason}`);
    L.push("");
  }
  if (result.unconvertible.length) {
    L.push("Not converted (RetroArch has nothing to bind these to):");
    const seen = new Set();
    for (const u of result.unconvertible) {
      const k = `${u.input}|${u.reason}`;
      if (seen.has(k)) continue;
      seen.add(k);
      L.push(`  - ${u.input}: ${u.reason}`);
    }
    L.push("");
  }
  for (const n of result.notes) L.push(`Note: ${n}`);
  return L.join("\n") + "\n";
}
