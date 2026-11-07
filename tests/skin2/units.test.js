/* Unit tests for the drawer's building blocks: SVG path data, text shaping, shape outlines, the Gaussian kernel,
   and a few renders small enough to check by hand. */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  collectAssetPaths, controlState, loadDocument, makeEnvironment, parseSVGPath, resolve, renderToSurface, shapePath, shapeLine,
  stateNames, textPath, gaussianKernel, controlStateFromJSON, Path, KAPPA,
} from "../../docs/js/skin2/index.js";
import { bundledFonts, pixelsOf, surface } from "./helpers.js";

const cmds = (d) => parseSVGPath(d).commands.map((c) => `${c.c}${Object.entries(c).filter(([k]) => k !== "c").map(([, v]) => +v.toFixed(3)).join(",")}`);

describe("SVG path data", () => {
  test("absolute and relative commands, implicit repeats, compact numbers", () => {
    assert.deepEqual(cmds("M0 0 L10 0 l0 10 h-10 v-10 z"), ["M0,0", "L10,0", "L10,10", "L0,10", "L0,0", "Z"]);
    assert.deepEqual(cmds("M0,0 10,0 10,10"), ["M0,0", "L10,0", "L10,10"]);
    assert.deepEqual(cmds("M1.5.5-1-2"), ["M1.5,0.5", "L-1,-2"]);
    assert.deepEqual(cmds("M0 0 C1 1 2 2 3 3 S5 5 6 6"), ["M0,0", "C1,1,2,2,3,3", "C4,4,5,5,6,6"]);
    assert.deepEqual(cmds("M0 0 Q1 1 2 0 T4 0"), ["M0,0", "Q1,1,2,0", "Q3,-1,4,0"]);
  });

  test("an arc becomes cubics of at most 90 degrees, ending on the endpoint", () => {
    const p = parseSVGPath("M0 0 A10 10 0 0 1 20 0");
    assert.equal(p.commands.length, 3); // M + two quarter arcs
    const last = p.commands[2];
    assert.ok(Math.abs(last.x - 20) < 1e-9 && Math.abs(last.y) < 1e-9);
  });

  test("malformed data ends the path at the last complete command", () => {
    assert.deepEqual(cmds("M0 0 L10 0 L5"), ["M0,0", "L10,0"]);
    assert.deepEqual(cmds("L5 5"), ["M0,0", "L5,5"]);
  });
});

describe("shapes", () => {
  const frame = { x: 10, y: 20, width: 100, height: 60 };
  const shape = (s) => shapePath({ kind: "rect", ...s }, frame, 1);

  test("a plain rect is four lines, a rounded one clamps its radii to half the short side", () => {
    assert.equal(shape({}).commands.length, 5);
    const r = shape({ cornerRadius: { op: "pt", value: 500 } });
    assert.ok(r.commands.filter((c) => c.c === "T").every((c) => c.r === 30));
  });

  test("an ellipse is four cubics from the right-middle", () => {
    const e = shapePath({ kind: "ellipse" }, frame, 1);
    assert.deepEqual(e.commands[0], { c: "M", x: 110, y: 50 });
    assert.equal(e.commands.filter((c) => c.c === "C").length, 4);
    assert.ok(Math.abs(e.commands[1].y1 - (50 + 30 * KAPPA)) < 1e-9);
  });

  test("a squircle starts 1.528665 radii from the corner", () => {
    const p = shapePath({ kind: "squircle", cornerRadius: { op: "pt", value: 10 } }, frame, 1);
    assert.ok(Math.abs(p.commands[0].x - (10 + 15.28665)) < 1e-9);
  });

  test("a polygon with rotation -90 points up, a star alternates radii", () => {
    const tri = shapePath({ kind: "polygon", sides: 3, rotation: -90 }, { x: 0, y: 0, width: 100, height: 100 }, 1);
    assert.deepEqual([tri.commands[0].x, tri.commands[0].y].map(Math.round), [50, 0]);
    const star = shapePath({ kind: "star", points: 5, innerRatio: 0.5 }, { x: 0, y: 0, width: 100, height: 100 }, 1);
    assert.equal(star.commands.filter((c) => c.c === "L" || c.c === "M").length, 10);
  });

  test("a path shape stretches its box non-uniformly onto the frame", () => {
    const p = shapePath({ kind: "path", d: "M0 0 L10 5", box: [0, 0, 10, 5] }, frame, 1);
    assert.deepEqual(p.commands, [{ c: "M", x: 10, y: 20 }, { c: "L", x: 110, y: 80 }]);
  });

  test("bounds include control points, and an empty path has none", () => {
    assert.equal(new Path().bounds(), undefined);
    assert.deepEqual(new Path().moveTo(0, 0).curveTo(5, -5, 10, 15, 10, 10).bounds(), { minX: 0, minY: -5, maxX: 10, maxY: 15 });
  });
});

describe("text", () => {
  const { regular } = bundledFonts();

  test("the fi ligature replaces two glyphs, and pair kerning narrows AV", () => {
    assert.equal(shapeLine(regular, "fi").glyphs.length, 1);
    assert.equal(shapeLine(regular, "ff").glyphs.length, 1);
    assert.equal(shapeLine(regular, "fa").glyphs.length, 2);
    const av = shapeLine(regular, "AV");
    assert.ok(av.width < av.glyphs.reduce((s, g) => s + g.advanceWidth, 0));
  });

  test("alignment moves the line within the frame, fit shrinks it to at most 60 percent", () => {
    const frame = { x: 0, y: 0, width: 100, height: 40 };
    const bounds = (align, fit, size = 20, text = "Hello") => textPath(text, regular, size, align, fit, frame).bounds();
    assert.ok(bounds("leading", false).minX < 5);
    assert.ok(bounds("trailing", false).maxX > 95);
    const mid = bounds("center", false);
    assert.ok(Math.abs((mid.minX + mid.maxX) / 2 - 50) < 5);
    const fitted = bounds("leading", true, 20, "A very long line indeed here");
    const plain = bounds("leading", false, 20, "A very long line indeed here");
    assert.ok(fitted.maxX < plain.maxX);
    const floor = bounds("leading", true, 20, "x".repeat(200));
    const sixty = bounds("leading", false, 12, "x".repeat(200));
    assert.ok(Math.abs(floor.maxX - sixty.maxX) < 0.5);
  });
});

describe("raster", () => {
  test("a Gaussian kernel is normalised with radius ceil(3 sigma), one tap under a tenth of a pixel", () => {
    const k = gaussianKernel(2);
    assert.equal(k.length, 13);
    assert.ok(Math.abs([...k].reduce((a, b) => a + b, 0) - 1) < 1e-6);
    assert.deepEqual([...gaussianKernel(0.05)], [1]);
  });
});

describe("render", () => {
  const phone = makeEnvironment({ width: 100, height: 100 }, {});
  const skin = (children, extra = {}) => ({
    formatVersion: "2.0", requires: [], identifier: "t", name: "t", gameTypes: ["com.provenance.gba"],
    reference: { shortSide: 100, minScale: 1, maxScale: 1 }, root: { type: "group", children }, ...extra,
  });
  const draw = (obj, options = {}, scale = 1) => {
    const res = resolve(loadDocument(JSON.stringify(obj)), phone);
    const canvas = renderToSurface(res, scale, { surface, fonts: bundledFonts(), ...options });
    return pixelsOf(canvas);
  };
  const px = (img, x, y) => [...img.data.slice((y * img.width + x) * 4, (y * img.width + x) * 4 + 4)];
  const solid = (color, extra = {}) => ({ type: "shape", shape: { kind: "rect" }, fills: [{ type: "solid", color }], ...extra });

  test("a solid fill, and group opacity composited once", () => {
    const img = draw(skin([{ type: "group", opacity: 0.5, children: [solid("#FF0000"), solid("#FF0000", { layout: { inset: 0 } })] }]));
    const [r, g, b, a] = px(img, 50, 50);
    assert.deepEqual([r, g, b], [255, 0, 0]);
    assert.ok(Math.abs(a - 128) <= 1, `alpha ${a}`);
  });

  test("multiply blends with what is under it", () => {
    const img = draw(skin([solid("#FF8000"), solid("#808080", { effects: [{ type: "blend", mode: "multiply" }] })]));
    const [r, g, b] = px(img, 50, 50);
    assert.ok(Math.abs(r - 128) <= 1 && Math.abs(g - 64) <= 1 && b === 0, `${r},${g},${b}`);
  });

  test("a drop shadow is blurred with sigma = radius / 2 and offset", () => {
    const node = { type: "shape", shape: { kind: "rect" }, layout: { size: { width: 20, height: 20 } }, fills: [{ type: "solid", color: "#FFFFFF" }],
      effects: [{ type: "shadow", color: "#000000", radius: 8, offset: [10, 0] }] };
    const img = draw(skin([node]));
    assert.equal(px(img, 50, 50)[3], 255); // the square itself, opaque
    const edge = px(img, 70, 50)[3]; // the shadow's edge: half coverage at the offset square's edge
    assert.ok(edge > 100 && edge < 160, `edge alpha ${edge}`);
    assert.equal(px(img, 95, 50)[3], 0); // beyond three sigma
  });

  test("an inner shadow stays inside the shape", () => {
    const node = { type: "shape", shape: { kind: "rect" }, layout: { size: { width: 40, height: 40 } }, fills: [{ type: "solid", color: "#FFFFFF" }],
      effects: [{ type: "shadow", color: "#000000", radius: 6, offset: [0, 0], inner: true }] };
    const img = draw(skin([node]));
    assert.equal(px(img, 5, 5)[3], 0);
    const nearEdge = px(img, 31, 50), centre = px(img, 50, 50);
    assert.ok(nearEdge[0] < centre[0]);
  });

  test("an outer stroke is outside the path, an inner one inside", () => {
    const stroke = (align) => skin([{ type: "shape", shape: { kind: "rect" }, layout: { size: { width: 40, height: 40 } },
      strokes: [{ color: "#FF0000", width: 4, align }] }]);
    const outer = draw(stroke("outer")), inner = draw(stroke("inner"));
    assert.equal(px(outer, 29, 50)[3], 255);
    assert.equal(px(outer, 32, 50)[3], 0);
    assert.equal(px(inner, 29, 50)[3], 0);
    assert.equal(px(inner, 32, 50)[3], 255);
  });

  test("repeat draws copies at their transforms", () => {
    const node = { type: "shape", shape: { kind: "rect" }, layout: { size: { width: 10, height: 10 }, anchor: { x: "leading", y: "top" } },
      fills: [{ type: "solid", color: "#00FF00" }], repeat: { count: 3, offset: { x: 20, y: 0 } } };
    const img = draw(skin([node]));
    assert.equal(px(img, 5, 5)[3], 255);
    assert.equal(px(img, 25, 5)[3], 255);
    assert.equal(px(img, 45, 5)[3], 255);
    assert.equal(px(img, 15, 5)[3], 0);
  });

  test("control states: pressed patches a descendant, scales about the centre, and moves the knob", () => {
    const ctl = {
      type: "control", kind: "thumbstick", id: "stick", input: "leftThumbstick", layout: { size: { width: 60, height: 60 } },
      states: { pressed: { patch: [{ target: "#base", fills: [{ type: "solid", color: "#0000FF" }] }] } },
      children: [
        { type: "shape", id: "base", shape: { kind: "ellipse" }, fills: [{ type: "solid", color: "#FF0000" }] },
        { type: "shape", role: "knob", shape: { kind: "rect" }, layout: { size: { width: 10, height: 10 } }, fills: [{ type: "solid", color: "#FFFFFF" }] },
      ],
    };
    const rest = draw(skin([ctl]));
    assert.deepEqual(px(rest, 35, 50).slice(0, 3), [255, 0, 0]);
    assert.deepEqual(px(rest, 50, 50).slice(0, 3), [255, 255, 255]);
    const held = draw(skin([ctl]), { states: { stick: controlState({ pressed: true, stick: { x: 1, y: 0 } }) } });
    assert.deepEqual(px(held, 35, 50).slice(0, 3), [0, 0, 255]);
    assert.deepEqual(px(held, 50 + 21, 50).slice(0, 3), [255, 255, 255]); // travel is 35 % of 60
    assert.deepEqual(px(held, 50, 50).slice(0, 3), [0, 0, 255]);
  });

  test("states.json entries and their names", () => {
    const s = controlStateFromJSON({ pressed: true, directions: ["down", "left"], stick: [3, 4] });
    assert.deepEqual(stateNames(s), ["pressed", "pressed.down", "pressed.left"]);
    assert.ok(Math.abs(Math.hypot(s.stick.x, s.stick.y) - 1) < 1e-9);
    assert.throws(() => controlStateFromJSON({ directions: ["sideways"] }), /unknown direction/);
  });

  test("text is drawn from the font, and not at all without one", () => {
    const text = { type: "text", text: "HI", font: { size: 40, weight: "bold" }, color: "#FFFFFF" };
    const withFont = draw(skin([text]));
    assert.ok(withFont.data.some((v, i) => i % 4 === 3 && v > 0));
    const without = draw(skin([text]), { fonts: undefined });
    assert.ok(without.data.every((v) => v === 0));
  });

  test("asset paths cover nodes, paints, patches, states and font families", () => {
    const doc = loadDocument(JSON.stringify(skin([
      { type: "image", src: "a.png" },
      { type: "shape", shape: { kind: "rect" }, fills: [{ type: "image", src: "b.png" }], when: [{ orientation: "portrait", fills: [{ type: "image", src: "c.png" }] }] },
      { type: "text", text: "x", font: { size: 10, family: "My.ttf" } },
    ])));
    assert.deepEqual(collectAssetPaths(doc), { images: ["a.png", "b.png", "c.png"], fonts: ["My.ttf"] });
  });
});
