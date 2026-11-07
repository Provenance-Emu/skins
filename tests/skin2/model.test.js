/* Unit tests for the model, preprocessor, validator and resolver (docs/js/skin2/): the rules of sections 2-7
   that the fixtures don't pin down on their own, and the std.* hook. */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  makeEnvironment, loadDocument, parseLength, resolve, resolveLength, rect, Skin2Error, STD_PARTS, validateText, halfPoint,
  normalizeGameType, inputsForGameType, supports, layoutRecord,
} from "../../docs/js/skin2/index.js";

const skin = (over = {}) => ({
  formatVersion: "2.0",
  requires: [],
  identifier: "test.skin",
  name: "Test",
  gameTypes: ["com.provenance.gba"],
  reference: { shortSide: 390, minScale: 1, maxScale: 1.35 },
  root: { type: "group", id: "canvas", children: [] },
  ...over,
});
const load = (obj, options) => loadDocument(JSON.stringify(obj), options);
const ZERO = { top: 0, left: 0, bottom: 0, right: 0 };

describe("lengths", () => {
  test("points scale by the unit, percentages by the along size", () => {
    assert.equal(resolveLength(parseLength(8), 100, 1.5, ZERO), 12);
    assert.equal(resolveLength(parseLength("50%"), 200, 1.5, ZERO), 100);
    assert.equal(resolveLength(parseLength({ pt: 8 }), 0, 2, ZERO), 16);
    assert.equal(resolveLength(parseLength({ frac: 0.25 }), 80, 2, ZERO), 20);
  });

  test("max, min and sum nest, and safe reads the inset unscaled", () => {
    const edge = parseLength({ sum: [{ max: [{ safe: "left" }, 8] }, 8] });
    const safe = { top: 0, left: 59, bottom: 0, right: 0 };
    assert.equal(resolveLength(edge, 0, 1.35, safe), 59 + 8 * 1.35);
    assert.equal(resolveLength(edge, 0, 1, ZERO), 16);
  });

  test("bad forms are rejected with a reason", () => {
    assert.throws(() => parseLength("12px"), /not a length/);
    assert.throws(() => parseLength({ pt: 1, frac: 2 }), /exactly one key/);
    assert.throws(() => parseLength({ max: [1] }), /at least two/);
    assert.throws(() => parseLength({ nope: 1 }), /unknown length operator/);
    const deep = { max: [{ max: [{ max: [{ max: [{ max: [1, 2] }, 3] }, 4] }, 5] }, 6] };
    assert.throws(() => parseLength(deep), /at most 4/);
  });
});

describe("rounding", () => {
  test("half points, ties toward +infinity, no negative zero", () => {
    assert.equal(halfPoint(1.24), 1);
    assert.equal(halfPoint(1.25), 1.5);
    assert.equal(halfPoint(-0.2), 0);
    assert.ok(Object.is(halfPoint(-0.2), 0));
    assert.deepEqual(rect.array(rect.roundedToHalfPoint({ x: 0.3, y: 0.2, width: 10.1, height: 5.6 })), [0.5, 0, 10, 6]);
  });
});

describe("loading", () => {
  test("a bare skin loads", () => {
    const doc = load(skin());
    assert.equal(doc.name, "Test");
    assert.equal(doc.root.type, "group");
  });

  test("format 1.x and 3.x are refused, 2.x is read", () => {
    assert.throws(() => load(skin({ formatVersion: "1.0" })), /format 2\.x/);
    assert.throws(() => load(skin({ formatVersion: "3.0" })), /format 2\.x/);
    assert.equal(load(skin({ formatVersion: "2.7" })).formatVersion, "2.7");
  });

  test("errors name a JSON Pointer", () => {
    const bad = skin({ root: { type: "group", children: [{ type: "shape", shape: { kind: "hexagon" } }] } });
    assert.throws(() => load(bad), (e) => e instanceof Skin2Error && e.pointer === "/root/children/0/shape/kind");
    const wrong = skin({ root: { type: "group", children: [{ type: "text", text: 4 }] } });
    assert.throws(() => load(wrong), (e) => e.pointer === "/root/children/0/text");
  });

  test("unknown keys are ignored", () => {
    assert.equal(load(skin({ somethingNew: { a: 1 } })).identifier, "test.skin");
  });

  test("files over 512 KB are refused", () => {
    assert.throws(() => loadDocument(" ".repeat(512 * 1024 + 1)), /limit/);
  });
});

describe("tokens, themes and parts", () => {
  const tokens = {
    tokens: { red: "#FF0000", gap: 8, edge: { length: { sum: [{ safe: "left" }, 4] } }, label: { string: "A" } },
    themes: { blue: { red: "#0000FF" } },
  };
  const rectNode = (fill) => ({ type: "shape", id: "s", shape: { kind: "rect" }, fills: [{ type: "solid", color: fill }] });

  test("$tokens expand, and a theme overrides them", () => {
    const base = skin({ ...tokens, root: { type: "group", children: [rectNode("$red")] } });
    assert.equal(load(base).root.children[0].fills[0].color.red, 1);
    assert.equal(load(base, { theme: "blue" }).root.children[0].fills[0].color.blue, 1);
  });

  test("an unknown token or theme fails", () => {
    assert.throws(() => load(skin({ root: { type: "group", children: [rectNode("$nope")] } })), /unknown token \$nope/);
    assert.throws(() => load(skin(tokens), { theme: "green" }), /no theme named/);
  });

  test("a theme can't change a token's type", () => {
    const bad = skin({ tokens: { red: "#FF0000" }, themes: { t: { red: 4 } } });
    assert.throws(() => load(bad, { theme: "t" }), /but the token is a color/);
  });

  const parts = {
    parts: {
      btn: {
        params: { input: { type: "string" }, size: { type: "length", default: { pt: 40 } } },
        node: {
          type: "control", kind: "button", input: "@input",
          children: [{ type: "shape", id: "body", shape: { kind: "ellipse" }, layout: { size: { width: "@size", height: "@size" } } }],
        },
      },
    },
  };

  test("a part instance substitutes parameters, scopes inner ids and merges caller keys", () => {
    const doc = load(skin({ ...parts, root: { type: "group", children: [{ use: "btn", id: "a", with: { input: "a" }, layout: { offset: { x: 5 } } }] } }));
    const a = doc.root.children[0];
    assert.equal(a.id, "a");
    assert.equal(a.input, "a");
    assert.equal(a.children[0].id, "a.body");
    assert.equal(a.layout.offset.x.value, 5);
    assert.equal(a.children[0].layout.size.width.value, 40);
  });

  test("parameters are typed, and a length argument is explicit", () => {
    const use = (w) => skin({ ...parts, root: { type: "group", children: [{ use: "btn", id: "a", with: w }] } });
    assert.throws(() => load(use({ input: 3 })), /btn\.input is a string/);
    assert.throws(() => load(use({ input: "a", size: 40 })), /length argument is explicit/);
    assert.throws(() => load(use({ input: "a", extra: 1 })), /no parameter "extra"/);
    assert.throws(() => load(use({})), /needs "input"/);
  });

  test("an instance of a part with inner ids needs an id", () => {
    assert.throws(() => load(skin({ ...parts, root: { type: "group", children: [{ use: "btn", with: { input: "a" } }] } })), /give this instance an id/);
  });

  test("parts can't use themselves", () => {
    const loop = { parts: { a: { node: { type: "group", children: [{ use: "a" }] } } }, root: { type: "group", children: [{ use: "a" }] } };
    assert.throws(() => load(skin(loop)), /uses itself/);
  });

  test("expansion stops at the node limit", () => {
    const wide = Array.from({ length: 2001 }, () => ({ type: "group" }));
    assert.throws(() => load(skin({ root: { type: "group", children: wide } })), /more than 2000 nodes/);
  });

  test("std.* parts are a hook: empty until SkinKit#123 lands", () => {
    assert.deepEqual(STD_PARTS, {});
    const std = skin({ root: { type: "group", children: [{ use: "std.faceButton", id: "a", with: {} }] } });
    assert.throws(() => load(std), /standard parts library \(std\.faceButton\) is not available/);
    const library = { "std.faceButton": { node: { type: "group" } } };
    assert.equal(load(std, { library }).root.children[0].id, "a");
  });
});

describe("variants", () => {
  const withVariant = (patch) => skin({
    variants: { v: { patch } },
    root: { type: "group", children: [{ type: "group", id: "g", layout: { size: { width: 10, height: 20 } } }] },
  });

  test("patches merge layout field by field, and null removes", () => {
    const doc = load(withVariant([{ target: "#g", layout: { size: { width: 99 }, aspect: 2 } }]), { variant: "v" });
    const l = doc.root.children[0].layout;
    assert.equal(l.size.width.value, 99);
    assert.equal(l.size.height.value, 20);
    assert.equal(l.aspect, 2);
    const cleared = load(withVariant([{ target: "#g", layout: { size: { height: null } } }]), { variant: "v" });
    assert.equal(cleared.root.children[0].layout.size.height, undefined);
  });

  test("a patch for a missing id fails, and so does an unknown variant", () => {
    assert.throws(() => load(withVariant([{ target: "#nope" }]), { variant: "v" }), /no node with id "nope"/);
    assert.throws(() => load(withVariant([]), { variant: "w" }), /no variant named "w"/);
  });
});

describe("resolver", () => {
  // 390 points on the short side: the unit is exactly 1.
  const phone = makeEnvironment({ width: 390, height: 844 }, { safeArea: { top: 59, left: 0, bottom: 34, right: 0 } });
  const frames = (obj, env = phone, options) => {
    const r = resolve(load(obj, options), env);
    return Object.fromEntries(layoutRecord(r).nodes.filter((n) => n.id).map((n) => [n.id, n.frame]));
  };
  const node = (id, layout, extra = {}) => ({ type: "group", id, layout, ...extra });

  test("anchors place against the safe area with offsets", () => {
    const f = frames(skin({ root: node("c", undefined, { children: [
      node("br", { size: { width: 100, height: 50 }, anchor: { x: "trailing", y: "bottom", to: "safeArea" }, offset: { x: -10, y: -6 } }),
    ] }) }));
    assert.deepEqual(f.br, [280, 844 - 34 - 50 - 6, 100, 50]);
  });

  test("the unit clamps between minScale and maxScale", () => {
    const f = frames(skin({ root: node("c", undefined, { children: [node("a", { size: { width: 10, height: 10 }, anchor: { x: "leading", y: "top" } })] }) }),
      makeEnvironment({ width: 1000, height: 2000 }));
    assert.deepEqual(f.a, [0, 0, 13.5, 13.5]);
  });

  test("a vertical stack packs children and aligns the cross axis", () => {
    const f = frames(skin({ root: node("c", undefined, { children: [
      node("s", { anchor: { x: "leading", y: "top" } }, { stack: { axis: "vertical", spacing: 4, align: "trailing" }, children: [
        node("a", { size: { width: 10, height: 20 } }), node("b", { size: { width: 30, height: 10 } }),
      ] }),
    ] }) }));
    assert.deepEqual(f.s, [0, 0, 30, 34]);
    assert.deepEqual(f.a, [20, 0, 10, 20]);
    assert.deepEqual(f.b, [0, 24, 30, 10]);
  });

  test("a hidden node takes no space in a stack", () => {
    const f = frames(skin({ root: node("c", undefined, { children: [
      node("s", { anchor: { x: "leading", y: "top" } }, { stack: { axis: "horizontal", spacing: 4 }, children: [
        node("a", { size: { width: 10, height: 10 } }), node("b", { size: { width: 10, height: 10 } }, { visible: false }),
        node("d", { size: { width: 10, height: 10 } }),
      ] }),
    ] }) }));
    assert.deepEqual(f.s, [0, 0, 24, 10]);
    assert.equal(f.b, undefined);
  });

  test("when patches apply in order, later wins, and conditions read the environment", () => {
    const obj = skin({ root: node("c", undefined, { children: [
      node("a", { size: { width: 10, height: 10 }, anchor: { x: "leading", y: "top" } }, { when: [
        { orientation: "portrait", layout: { size: { width: 20 } } },
        { device: "iphone", layout: { size: { width: 30 } } },
        { device: "ipad", layout: { size: { width: 40 } } },
        { minHeight: 5000, layout: { size: { width: 50 } } },
      ] }),
    ] }) });
    assert.equal(frames(obj).a[2], 30);
    // 600 points on the short side: the unit clamps to 1.35.
    assert.equal(frames(obj, makeEnvironment({ width: 800, height: 600 }, { device: "ipad" })).a[2], 40 * 1.35);
  });

  test("visible takes a flag condition from the environment", () => {
    const obj = skin({ root: node("c", undefined, { children: [node("m", { size: { width: 5, height: 5 } }, { visible: { flag: "microphone" } })] }) });
    assert.equal(frames(obj).m, undefined);
    assert.ok(frames(obj, makeEnvironment({ width: 390, height: 844 }, { flags: new Set(["microphone"]) })).m);
  });

  test("an anchor to a node not yet laid out warns and uses the parent", () => {
    const r = resolve(load(skin({ root: node("c", undefined, { children: [node("a", { anchor: { to: "#later" } }), node("later", {})] }) })), phone);
    assert.equal(r.warnings.length, 1);
    assert.match(r.warnings[0].message, /not laid out before this node/);
  });

  test("player edits move, scale and hide by id", () => {
    const doc = load(skin({ root: node("c", undefined, { children: [node("a", { size: { width: 100, height: 100 }, anchor: { x: "leading", y: "top" } })] }) }));
    const r = resolve(doc, phone, { a: { offset: { x: 10, y: 20 }, scale: 0.5 } });
    assert.deepEqual(r.root.children[0].exactFrame, { x: 35, y: 45, width: 50, height: 50 });
    assert.equal(resolve(doc, phone, { a: { hidden: true } }).root.children.length, 0);
  });

  test("repeat gives one transform per copy, the first the identity", () => {
    const doc = load(skin({ root: node("c", undefined, { children: [
      node("a", { size: { width: 10, height: 10 } }, { repeat: { count: 4, rotate: 90 } }),
    ] }) }));
    const copies = resolve(doc, phone).root.children[0].copies;
    assert.equal(copies.length, 4);
    assert.deepEqual(copies[0], { a: 1, b: 0, c: 0, d: 1, tx: 0, ty: 0 });
    assert.ok(Math.abs(copies[1].b - 1) < 1e-9);
  });
});

describe("validator", () => {
  const controlSkin = (children, over = {}) => skin({
    requires: [],
    root: { type: "group", id: "canvas", children },
    ...over,
  });
  const ctl = (id, input, layout, extra = {}) => ({
    type: "control", kind: "button", id, input, layout: { size: { width: 60, height: 60 }, ...layout }, ...extra,
  });
  const messages = (text) => validateText(JSON.stringify(text)).issues.map((i) => `${i.severity} ${i.pointer} ${i.message}`);

  test("requires must list what the skin uses, and warns about what it doesn't", () => {
    const m = messages(controlSkin([{ type: "group", id: "g", layout: { anchor: { x: "leading" } } }]));
    assert.ok(m.some((x) => x.includes("uses layout.anchors but does not list it")), m.join("\n"));
    const extra = messages(controlSkin([], { requires: ["materials", "made.up"] }));
    assert.ok(extra.some((x) => x.startsWith("warning /requires/0") && x.includes("does not use")));
    assert.ok(extra.some((x) => x.includes('"made.up" is not a 2.0 feature name')));
  });

  test("overlapping hit frames are errors, touching ones are not", () => {
    const overlapping = messages(controlSkin([
      ctl("a", "a", { frame: [0, 0, 60, 60] }), ctl("b", "b", { frame: [50, 0, 60, 60] }),
    ], { requires: [] }));
    assert.ok(overlapping.some((x) => x.includes("hit frame of #a overlaps #b")));
    const touching = messages(controlSkin([
      ctl("a", "a", { frame: [0, 0, 60, 60] }), ctl("b", "b", { frame: [60, 0, 60, 60] }),
    ]));
    assert.ok(!touching.some((x) => x.includes("overlaps")), touching.join("\n"));
  });

  test("inputs are checked against the game type and the control kind", () => {
    const m = messages(controlSkin([ctl("a", "cross", { frame: [0, 0, 60, 60] }), ctl("m", "nope", { frame: [100, 0, 60, 60] }, { kind: "action" })]));
    assert.ok(m.some((x) => x.includes('"cross" is not an input of game type com.provenance.gba')));
    assert.ok(m.some((x) => x.includes('"nope" is not an app action')));
  });

  test("ids are unique, controls and screens need ids, anchors can't point forward", () => {
    const m = messages(controlSkin([
      { type: "group", id: "x", layout: { anchor: { to: "#y" } } }, { type: "group", id: "y" }, { type: "group", id: "x" },
      { type: "screen" }, { type: "control", kind: "button", input: "a" },
    ], { requires: ["layout.anchors"] }));
    assert.ok(m.some((x) => x.includes('anchors to #y, which is not a node earlier')));
    assert.ok(m.some((x) => x.includes('id "x" is already used at /root/children/0')));
    assert.ok(m.some((x) => x.includes("a screen needs an id")));
    assert.ok(m.some((x) => x.includes("a control needs an id")));
  });

  test("asset paths can't be URLs or climb out of assets/", () => {
    const m = messages(controlSkin([
      { type: "image", src: "https://example.com/a.png" }, { type: "image", src: "../a.png" }, { type: "image", src: "ok/a.png" },
    ]));
    assert.equal(m.filter((x) => x.startsWith("error") && x.includes("/src")).length, 2);
  });

  test("small controls warn, bake traits must include the required families", () => {
    const small = messages(controlSkin([ctl("a", "a", { size: { width: 30, height: 30 } })]));
    assert.ok(small.some((x) => x.startsWith("warning") && x.includes("30.0 pt on its short side")));
    const bake = messages(controlSkin([], { bake: { traits: ["iphone.standard"] } }));
    assert.ok(bake.some((x) => x.includes("bake.traits must include iphone.edgeToEdge")));
  });

  test("a document that fails to load reports one error with a pointer", () => {
    const r = validateText(JSON.stringify(skin({ gameTypes: [] })));
    assert.equal(r.isValid, false);
    assert.equal(r.errors.length, 1);
    assert.equal(r.errors[0].pointer, "/gameTypes");
    assert.equal(validateText("{").errors[0].pointer, "");
  });
});

describe("features and inputs", () => {
  test("a reader supports a skin when it has every required feature", () => {
    assert.ok(supports(["layout.stack", "text"]));
    assert.ok(!supports(["layout.stack", "effects.ci"]));
  });

  test("game type names normalise to the table's keys", () => {
    assert.equal(normalizeGameType("com.rileytestut.delta.game.SNES"), "snes");
    assert.ok(inputsForGameType("com.provenance.gamecube").has("cStick"));
    assert.equal(inputsForGameType("com.example.unknown"), undefined);
  });
});
