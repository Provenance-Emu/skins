// Node-side checks for the RetroArch converter's pure logic.
//   node --test tests/js/*.test.js
// tests/test_retroarch_converter.py runs this under pytest when node is installed.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as RA from "../../docs/js/skin/retroarch-convert.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, "..", "fixtures", "retroarch");
const inputMap = JSON.parse(readFileSync(join(HERE, "..", "..", "docs", "js", "skin", "retroarch-input-map.json"), "utf8"));

const fixture = name => RA.parseInfo(readFileSync(join(FIXTURES, name), "utf8"));
const convert = (info, opts) => RA.convert(info, Object.assign({ inputMap }, opts));

/** Parse a .cfg into {key: value} the way RetroArch's config_file does (quotes stripped). */
function parseCfg(cfg) {
  const out = {};
  for (const raw of cfg.split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const m = line.match(/^(\w+)\s*=\s*(.*)$/);
    assert.ok(m, `cfg line is key = value: ${line}`);
    out[m[1]] = m[2].replace(/^"(.*)"$/, "$1");
  }
  return out;
}

/** Every desc referenced by overlayK_descs exists and parses as input,x,y,shape,rx,ry in range. */
function checkCfgShape(cfg) {
  const c = parseCfg(cfg);
  const n = Number(c.overlays);
  assert.ok(n >= 1, "overlays >= 1");
  for (let k = 0; k < n; k++) {
    assert.ok(c[`overlay${k}_overlay`].endsWith(".png"), "overlay image is a png");
    assert.equal(c[`overlay${k}_full_screen`], "true");
    assert.equal(c[`overlay${k}_normalized`], "true");
    assert.ok(Number(c[`overlay${k}_aspect_ratio`]) > 0);
    const descs = Number(c[`overlay${k}_descs`]);
    for (let d = 0; d < descs; d++) {
      const v = c[`overlay${k}_desc${d}`];
      assert.ok(v, `overlay${k}_desc${d} present`);
      const parts = v.split(",");
      assert.equal(parts.length, 6, `six fields: ${v}`);
      assert.ok(["rect", "radial"].includes(parts[3]), `shape: ${v}`);
      for (const f of [parts[1], parts[2], parts[4], parts[5]]) {
        const x = Number(f);
        assert.ok(Number.isFinite(x) && x >= -0.5 && x <= 1.5, `coordinate in range: ${v}`);
      }
      if (parts[0].startsWith("analog_")) assert.equal(parts[3], "radial", "analog descs are radial");
    }
    assert.equal(c[`overlay${k}_desc${descs}`], undefined, "no descs past the count");
  }
  return c;
}

test("slugify never yields a name that is the current or parent folder", () => {
  for (const dots of [".", "..", "...", " .. ", "_.._", "", null]) assert.equal(RA.slugify(dots), "skin");
  assert.equal(RA.slugify("..hidden"), "..hidden");
  assert.equal(RA.slugify("Backbone One — GBA"), "Backbone_One_GBA");
});

test("stripComments drops comments and trailing commas outside strings only", () => {
  const src = '{\n  // a comment\n  "name": "a // b, /* not */ }", // trailing\n  /* block\n comment */ "url": "http://x,}",\n  "a": [1, 2, // c\n ],\n}\n';
  assert.deepEqual(JSON.parse(RA.stripComments(src)), { name: "a // b, /* not */ }", url: "http://x,}", a: [1, 2] });
  assert.deepEqual(RA.parseInfo('{"url":"https://example.com/x,}", // comment\n "a":[1,],}'), { url: "https://example.com/x,}", a: [1] });
});

test("resolveAsset is lenient like the apps", () => {
  const entries = ["info.json", "Art/IPhone_Portrait.PDF", "landscape.png"];
  assert.equal(RA.resolveAsset(entries, "info.json"), "info.json");
  assert.equal(RA.resolveAsset(entries, "iphone_portrait.pdf"), "Art/IPhone_Portrait.PDF");
  assert.equal(RA.resolveAsset(entries, "landscape.pdf"), "landscape.png");
  assert.equal(RA.resolveAsset(entries, "missing.pdf"), null);
});

test("systemOf uses gameTypes, then the identifier's suffix", () => {
  assert.equal(RA.systemOf({ gameTypeIdentifier: "com.rileytestut.delta.game.ds" }, inputMap), "nds");
  assert.equal(RA.systemOf({ gameTypeIdentifier: "public.aoshuang.game.megadrive" }, inputMap), "genesis");
  assert.equal(RA.systemOf({ gameTypeIdentifier: "com.whatever.psx" }, inputMap), "psx");
});

test("bindFor follows per-system core defaults", () => {
  assert.equal(RA.bindFor("z", "n64", inputMap), "l2");
  assert.equal(RA.bindFor("c", "genesis", inputMap), "a");
  assert.equal(RA.bindFor("a", "genesis", inputMap), "y");
  assert.equal(RA.bindFor("cross", "psx", inputMap), "b");
  assert.equal(RA.bindFor("menu", "gba", inputMap), "menu_toggle");
  assert.equal(RA.bindFor("l2", "unknown", inputMap), "l2");
  assert.equal(RA.bindFor("touchScreenX", "nds", inputMap), null);
  assert.equal(RA.bindFor("nonsense", "nes", inputMap), undefined);
});

test("Backbone GBA: SVG landscape layout, hitboxes include edges, zl/zr land on l2/r2", () => {
  const r = convert(fixture("backbone-gba.info.json"));
  const c = checkCfgShape(r.cfg);
  assert.equal(r.system, "gba");
  assert.equal(c.overlays, "1");
  assert.equal(c.overlay0_name, "landscape");
  assert.equal(r.images.length, 1);
  assert.equal(r.images[0].asset, "controller.svg");
  assert.deepEqual([r.images[0].width, r.images[0].height], [852, 393]);
  // Translucent layout: the artwork stays as drawn (its screen area is already clear).
  assert.equal(r.images[0].clearRects.length, 0);
  assert.equal(c.overlay0_viewport, undefined, "screens are informational; no viewport key");
  const binds = Object.entries(c).filter(([k]) => /^overlay0_desc\d+$/.test(k)).map(([, v]) => v.split(",")[0]);
  for (const b of ["a", "b", "l", "r", "l2", "r2", "select", "start", "menu_toggle", "up|left", "down|right", "up", "left"]) {
    assert.ok(binds.includes(b), `has ${b}`);
  }
  assert.equal(binds.filter(b => b === "overlay_next").length, 0, "single layout: no rotate desc");
  // The "a" button: frame 766,231 42x34 with item edges 8 → hitbox 758,223 58x50 of 852x393.
  const a = Object.values(c).find(v => typeof v === "string" && v.startsWith("a,"));
  assert.equal(a, `a,${(787 / 852).toFixed(6)},${(248 / 393).toFixed(6)},rect,${(29 / 852).toFixed(6)},${(25 / 393).toFixed(6)}`);
  assert.equal(r.unconvertible.length, 0);
});

test("N64 with comments: thumbstick, C pad, combos, frontend buttons, alt layouts, unconvertible touch", () => {
  const info = fixture("n64-comments.info.json");
  assert.equal(info.name, "N64 Comments // Test", "// inside a string survives");
  const r = convert(info);
  const c = checkCfgShape(r.cfg);
  assert.equal(r.system, "n64");
  assert.equal(r.name, "N64_Comments_Test");
  // landscape, portrait, then the alt portrait
  assert.equal(c.overlays, "3");
  assert.deepEqual([c.overlay0_name, c.overlay1_name, c.overlay2_name], ["landscape", "portrait", "portrait-alt"]);

  const descsOf = k => Object.entries(c).filter(([key]) => new RegExp(`^overlay${k}_desc\\d+$`).test(key)).map(([key, v]) => [key, v]);
  const portrait = descsOf(1);
  const binds = portrait.map(([, v]) => v.split(",")[0]);
  // thumbstick → analog_left, radial, movable cap image
  const [thumbKey, thumbVal] = portrait.find(([, v]) => v.startsWith("analog_left,"));
  assert.ok(thumbVal.includes(",radial,"));
  assert.ok(c[`${thumbKey}_overlay`].endsWith("-thumb0.png"));
  assert.equal(c[`${thumbKey}_movable`], "true");
  const thumb = r.images.find(i => i.kind === "thumbstick");
  assert.deepEqual([thumb.width, thumb.height, thumb.innerWidth, thumb.innerHeight], [100, 100, 60, 60], "hitbox 80+10+10, cap 60");
  // C buttons as a pad → nine rects with right-stick binds
  for (const b of ["r_y_minus", "r_y_plus", "r_x_minus", "r_x_plus", "r_y_minus|r_x_minus", "r_y_plus|r_x_plus"]) assert.ok(binds.includes(b), b);
  // plain d-pad → nine rects; the item's own zero edges override the layout's 10
  assert.equal(binds.filter(b => ["up", "down", "left", "right", "up|left", "up|right", "down|left", "down|right"].includes(b)).length, 8);
  assert.ok(binds.includes("a|b"), "combo");
  assert.ok(binds.includes("l2"), "N64 Z on L2");
  for (const b of ["menu_toggle", "toggle_fast_forward", "save_state", "load_state"]) assert.ok(binds.includes(b), b);
  // toggleAltRepresentations → overlay_next into the alt layout, and back from it
  const [toggleKey] = portrait.find(([, v]) => v.startsWith("overlay_next,") && !v.includes("0.500000,0.000000"));
  assert.equal(c[`${toggleKey}_next_target`], "portrait-alt");
  const altToggle = descsOf(2).find(([, v]) => v.startsWith("overlay_next,") && !v.includes("0.500000,0.000000"));
  assert.equal(c[`${altToggle[0]}_next_target`], "portrait");
  // hidden rotate descs: portrait → landscape, landscape → portrait, alt portrait → landscape
  const rotate = k => descsOf(k).find(([, v]) => v.startsWith("overlay_next,0.500000,0.000000"));
  assert.equal(c[`${rotate(0)[0]}_next_target`], "portrait");
  assert.equal(c[`${rotate(1)[0]}_next_target`], "landscape");
  assert.equal(c[`${rotate(2)[0]}_next_target`], "landscape");
  assert.equal(c[`${rotate(1)[0]}_reach_x`], "0.0");
  // DS touch inputs are reported, not dropped silently
  const touch = r.unconvertible.filter(u => u.input.startsWith("touchScreen"));
  assert.equal(touch.length, 2);
  assert.ok(touch[0].reason.includes("pointer"));
  // portrait 320x340 is a controller strip (wider than a 19.5:9 screen): bottom-anchored,
  // height share = (340/320) / (19.5/9) = 0.490385.
  assert.equal(c.overlay1_rect, "0.000000,0.509615,1.000000,0.490385");
  // landscape screen, not translucent: the image is cleared there
  assert.equal(r.images.find(i => i.overlayName === "landscape").clearRects.length, 1);
  assert.ok(r.readme.includes("touchScreenX"), "README lists what did not convert");
  assert.ok(r.readme.includes("Mupen64Plus-Next"), "README names the core layout assumed");
});

test("Genesis standard portrait strip: bottom-anchored rect, largest PNG, core button layout, iPad folder", () => {
  const info = fixture("genesis-standard-png.info.json");
  const r = convert(info, { displayType: "standard" });
  const c = checkCfgShape(r.cfg);
  assert.equal(c.overlays, "1");
  assert.equal(c.overlay0_name, "portrait");
  assert.equal(r.images[0].asset, "portrait_large.png");
  // 375x240 on a 16:9 phone: height share = (240/375) / (16/9) = 0.36
  assert.equal(c.overlay0_rect, "0.000000,0.640000,1.000000,0.360000");
  assert.equal(c.overlay0_aspect_ratio, "0.562500");
  const binds = Object.entries(c).filter(([k]) => /^overlay0_desc\d+$/.test(k)).map(([, v]) => v.split(",")[0]);
  for (const b of ["y", "b", "a", "select", "start"]) assert.ok(binds.includes(b), `Genesis ${b}`);
  assert.ok(!binds.includes("c"), "Genesis C is remapped");
  assert.equal(r.unconvertible.length, 0);

  const ipad = convert(info, { device: "ipad", displayType: "standard" });
  assert.equal(ipad.name, "Genesis_Standard_PNG-ipad");
  assert.equal(parseCfg(ipad.cfg).overlay0_name, "landscape");
  assert.equal(parseCfg(ipad.cfg).overlay0_aspect_ratio, (4 / 3).toFixed(6));
  assert.equal(ipad.notes.length, 0);

  // Asking for edgeToEdge falls back to standard and says so.
  const fb = convert(info, { displayType: "edgeToEdge" });
  assert.ok(fb.notes.some(n => n.includes("using standard")));
});

test("a layout whose artwork is missing from the archive is skipped, not emitted", () => {
  const info = fixture("n64-comments.info.json");
  // Landscape.pdf is missing; the thumbstick cap is present under a different case.
  const entries = ["info.json", "portrait.PDF", "PortraitAlt.pdf", "Thumb.pdf"];
  const r = convert(info, { entries });
  const c = checkCfgShape(r.cfg);
  assert.equal(c.overlays, "2");
  assert.deepEqual([c.overlay0_name, c.overlay1_name], ["portrait", "portrait-alt"]);
  assert.equal(r.skipped.length, 1);
  assert.equal(r.skipped[0].overlayName, "landscape");
  assert.ok(r.skipped[0].reason.includes("Landscape.pdf"));
  assert.ok(r.images.every(i => i.overlayName !== "landscape"));
  assert.ok(r.images.some(i => i.kind === "thumbstick"), "cap image resolved case-insensitively");
  assert.ok(r.readme.includes("Layouts left out"));
  // Without the thumbstick file the analog desc stays but has no cap image.
  const r2 = convert(info, { entries: ["info.json", "Portrait.pdf", "PortraitAlt.pdf"] });
  assert.ok(!r2.images.some(i => i.kind === "thumbstick"));
  assert.ok(!r2.cfg.includes("_movable"));
  assert.ok(r2.notes.some(n => n.includes("thumb.pdf")));
  // Without entries nothing is skipped (the caller has no archive to check against).
  assert.equal(convert(info).skipped.length, 0);
});

test("tv layouts convert as artwork with a note and a -tv folder", () => {
  const info = fixture("genesis-standard-png.info.json");
  info.representations.tv = { standard: { landscape: info.representations.ipad.standard.landscape } };
  const r = convert(info, { device: "tv", displayType: "standard" });
  assert.equal(r.name, "Genesis_Standard_PNG-tv");
  assert.equal(parseCfg(r.cfg).overlay0_aspect_ratio, (16 / 9).toFixed(6));
  assert.ok(r.notes.some(n => n.includes("controller")));
});

test("a skin with no artwork converts to nothing, with a note", () => {
  const r = convert({ name: "Empty", representations: { iphone: { standard: { portrait: { items: [] } } } } });
  assert.equal(r.cfg, "");
  assert.ok(r.notes.length);
});
