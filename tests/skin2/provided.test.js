/* What a resolved skin provides (SkinKit ProvidedTests): the same inline documents, the same sets. Also the
   capability, panel and semantic-input rules the report rests on. */

import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  initialPanelFlags, loadDocument, makeEnvironment, NOTHING_PROVIDED, provided, providedKeeping, resolutionNode, resolve, SEMANTIC_INPUTS,
  usedFeatures, parseJSON, validateText,
} from "../../docs/js/skin2/index.js";

const skin = (children, extra = "") => `{ "formatVersion": "2.0", "requires": ["shapes.parametric"], "identifier": "test", "name": "Test",
  "gameTypes": ["com.rileytestut.delta.game.dc"], "reference": { "shortSide": 390, "minScale": 1, "maxScale": 1.35 }${extra ? ", " + extra : ""},
  "root": { "type": "group", "children": [ ${children} ] } }`;

const CAPS = ["picture.vmu.p1", "input.arcade.coin1"];
const env = ({ capabilities = CAPS, flags = [] } = {}) =>
  makeEnvironment({ width: 390, height: 844 }, { capabilities: new Set(capabilities), flags: new Set(flags) });
const resolved = (children, options = {}, edits = {}) => resolve(loadDocument(skin(children)), env(options), edits);
const report = (children, options = {}, edits = {}) => provided(resolved(children, options, edits));

const lcd = (id = "lcd", frame = "[10,10,96,64]", extra = "") =>
  `{"type":"screen","id":"${id}","source":"vmu.p1","layout":{"frame":${frame}}${extra}}`;
const coin = (id = "coin", frame = "[10,200,60,60]", input = "arcade.coin1", extra = "") =>
  `{"type":"control","id":"${id}","kind":"button","input":"${input}","layout":{"frame":${frame}}${extra}}`;
const TAB = `{"type":"control","id":"tab","kind":"action","input":"togglePanel","layout":{"frame":[0,0,48,48]}}`;
function panel({ presentation = "shelf", open = false, extraChildren = "", when = "" } = {}) {
  return `{"type":"group","id":"vmuPanel","layout":{"frame":[100,100,160,120]},
    "panel":{"name":"vmu","label":"Visual Memory","needs":["picture.vmu.p1"],"presentation":"${presentation}","handle":"#tab","open":${open}}
    ${when ? `,"when":[${when}]` : ""},
    "children":[{"type":"shape","id":"body","shape":{"kind":"rect"}},
      {"type":"screen","id":"panelLcd","source":"vmu.p1","layout":{"frame":[56,8,96,64]}}, ${TAB}${extraChildren ? "," + extraChildren : ""}]}`;
}

describe("what a resolved skin provides", () => {
  test("a screen and a control outside any panel are provided", () => {
    assert.deepEqual(report(`${lcd()},${coin()}`), { pictures: ["vmu.p1"], inputs: ["arcade.coin1"], panels: {} });
  });
  test("a fixed panel provides its picture", () => {
    assert.deepEqual(report(panel({ presentation: "fixed" })), { pictures: ["vmu.p1"], inputs: [], panels: { vmu: true } });
  });
  test("an open shelf provides its picture", () => {
    assert.deepEqual(report(panel(), { flags: ["panel.vmu.open"] }), { pictures: ["vmu.p1"], inputs: [], panels: { vmu: true } });
  });
  test("a closed shelf the player can open still provides", () => {
    assert.deepEqual(report(panel({ extraChildren: coin("coin", "[60,60,60,60]") })), { pictures: ["vmu.p1"], inputs: ["arcade.coin1"], panels: { vmu: false } });
  });
  test("a closed shelf whose handle is off screen provides nothing", () => {
    assert.deepEqual(report(panel(), {}, { tab: { offset: { x: -400, y: 0 } } }), { pictures: [], inputs: [], panels: { vmu: false } });
    assert.deepEqual(report(panel(), {}, { tab: { hidden: true } }).pictures, []);
  });
  test("what a closed shelf would show when open is what counts", () => {
    const small = `{"type":"group","id":"shelf","layout":{"frame":[100,100,160,120]},"panel":{"name":"vmu","presentation":"shelf","handle":"#tab"},
      "children":[{"type":"screen","id":"lcd2","source":"vmu.p1","layout":{"frame":[56,8,96,64]},
        "when":[{"flag":"panel.vmu.open","layout":{"frame":[56,8,40,27]}}]}, ${TAB}]}`;
    assert.deepEqual(report(small).pictures, []);
  });
  test("a handle flush with a fractional safe edge is still reachable", () => {
    const doc = loadDocument(skin(panel()));
    const environment = makeEnvironment({ width: 390, height: 844 },
      { capabilities: new Set(CAPS), safeArea: { top: 0, left: 0, bottom: 0, right: 241.7 } });
    const r = resolve(doc, environment, { tab: { offset: { x: 0.3, y: 0 } } });
    assert.equal(r.panels[0].handleReachable, true);
    assert.deepEqual(provided(r).pictures, ["vmu.p1"]);
    assert.equal(resolve(doc, environment, { tab: { offset: { x: 1.5, y: 0 } } }).panels[0].handleReachable, false);
  });
  test("a picture smaller than 48 by 32 points is not provided", () => {
    assert.deepEqual(report(lcd("lcd", "[10,10,40,27]")).pictures, []);
    assert.deepEqual(report(lcd("lcd", "[10,10,48,32]")).pictures, ["vmu.p1"]);
  });
  test("a picture that leaves the canvas is not provided", () => {
    assert.deepEqual(report(lcd("lcd", "[350,10,96,64]")).pictures, []);
    assert.deepEqual(report(lcd(), {}, { lcd: { offset: { x: -60, y: 0 } } }).pictures, []);
  });
  test("a nearly transparent picture is not provided", () => {
    assert.deepEqual(report(lcd("lcd", "[10,10,96,64]", `,"opacity":0.04`)).pictures, []);
    assert.deepEqual(report(lcd("lcd", "[10,10,96,64]", `,"opacity":0.06`)).pictures, ["vmu.p1"]);
    assert.deepEqual(report(`{"type":"group","id":"g","opacity":0.2,"children":[${lcd("lcd", "[10,10,96,64]", `,"opacity":0.2`)}]}`).pictures, []);
  });
  test("a control smaller than 44 by 44 points is not provided", () => {
    assert.deepEqual(report(coin("coin", "[10,200,40,40]")).inputs, []);
    assert.deepEqual(report(coin("coin", "[10,200,40,40]", "arcade.coin1", `,"hit":{"extend":2}`)).inputs, ["arcade.coin1"]);
    assert.deepEqual(report(coin("coin", "[-30,200,60,60]")).inputs, []);
  });
  test("a node marked duplicate does not claim", () => {
    assert.deepEqual(report(lcd("lcd", "[10,10,96,64]", `,"duplicate":true`)).pictures, []);
    assert.deepEqual(report(`${lcd("lcd", "[10,10,96,64]", `,"duplicate":true`)},${lcd("second", "[10,100,96,64]")}`).pictures, ["vmu.p1"]);
    assert.deepEqual(report(coin("coin", "[10,200,60,60]", "arcade.coin1", `,"duplicate":true`)).inputs, []);
  });
  test("duplicate belongs on a screen or a control", () => {
    const r = validateText(skin(`{"type":"group","id":"g","duplicate":true}`));
    assert.ok(r.errors.some((i) => i.pointer === "/root/children/0/duplicate"));
  });
  test("panels report their open state", () => {
    assert.deepEqual(report(panel()).panels, { vmu: false });
    assert.deepEqual(report(panel(), { flags: ["panel.vmu.open"] }).panels, { vmu: true });
  });
  test("without the capability nothing is provided", () => {
    assert.deepEqual(report(`${panel()},${coin("coin", "[10,400,60,60]")}`, { capabilities: [] }), NOTHING_PROVIDED);
    assert.deepEqual(report(lcd(), { capabilities: [] }).pictures, []);
  });
  test("classic button names are never in inputs", () => {
    assert.deepEqual(report(coin("a", "[10,200,60,60]", "a")).inputs, []);
  });
  test("keeping narrows pictures to the ones delivered", () => {
    const p = { pictures: ["vmu.p1", "vmu.p2"], inputs: ["arcade.coin1"], panels: { vmu: true } };
    assert.deepEqual(providedKeeping(p, ["vmu.p2", "vmu.p3"]), { pictures: ["vmu.p2"], inputs: ["arcade.coin1"], panels: { vmu: true } });
    assert.deepEqual(providedKeeping(p, []).pictures, []);
  });
});

describe("capabilities, panels and semantic inputs", () => {
  test("a has condition follows the capabilities; a list needs every name", () => {
    const one = `{"type":"group","id":"g","visible":{"has":"picture.vmu.p1"}}`;
    assert.equal(resolutionNode(resolved(one, { capabilities: [] }), "g"), undefined);
    assert.ok(resolutionNode(resolved(one), "g"));
    const both = `{"type":"group","id":"g","visible":{"has":["picture.vmu.p1","picture.vmu.p2"]}}`;
    assert.equal(resolutionNode(resolved(both), "g"), undefined);
    assert.ok(resolutionNode(resolved(both, { capabilities: ["picture.vmu.p1", "picture.vmu.p2"] }), "g"));
  });
  test("a closed shelf keeps only its handle; a fixed panel hides it", () => {
    const ids = (r) => { const out = []; const walk = (n) => { if (n.node.id) out.push(n.node.id); n.children.forEach(walk); }; walk(r.root); return out; };
    assert.deepEqual(ids(resolved(panel())), ["vmuPanel", "tab"]);
    assert.deepEqual(ids(resolved(panel(), { flags: ["panel.vmu.open"] })), ["vmuPanel", "body", "panelLcd", "tab"]);
    assert.deepEqual(ids(resolved(panel({ presentation: "fixed" }))), ["vmuPanel", "body", "panelLcd"]);
    assert.deepEqual(ids(resolved(panel(), { capabilities: [] })), []);
    const byWhen = loadDocument(skin(panel({ when: `{"minWidth":700,"panel":{"presentation":"fixed"}}` })));
    const wide = resolve(byWhen, makeEnvironment({ width: 1024, height: 768 }, { capabilities: new Set(CAPS) }));
    assert.equal(wide.panels[0].presentation, "fixed");
    assert.deepEqual([...initialPanelFlags(loadDocument(skin(panel({ open: true }))))], ["panel.vmu.open"]);
  });
  test("an accessory screen is not the screen area and takes its source's aspect", () => {
    const r = resolved(`{"type":"screen","id":"lcd","source":"vmu.p1","layout":{"size":{"width":96}}},
      {"type":"screen","id":"main","aspect":1.3333,"layout":{"size":{"width":"100%"},"anchor":{"y":"top"}}},
      {"type":"group","id":"follower","layout":{"anchor":{"to":"screen"}}}`);
    assert.deepEqual(resolutionNode(r, "follower").frame, resolutionNode(r, "main").frame);
    assert.equal(resolutionNode(r, "lcd").frame.height, 64);
  });
  test("a semantic control needs its capability", () => {
    assert.equal(resolutionNode(resolved(coin(), { capabilities: [] }), "coin"), undefined);
    assert.ok(resolutionNode(resolved(coin()), "coin"));
    assert.equal(SEMANTIC_INPUTS.length, 17);
  });
  test("the validator's new rules", () => {
    const errors = (children, extra = `"optional":["capabilities","screens.accessory","panels","inputs.semantic"]`) =>
      validateText(skin(children, extra)).errors.map((i) => `${i.pointer}: ${i.message}`);
    const has = (list, pointer, text) => list.some((e) => e.startsWith(`${pointer}: `) && e.includes(text));
    assert.ok(has(errors(`{"type":"group","id":"g","visible":{"has":"picture.gameboy"}}`), "/root/children/0/visible/has", "picture.gameboy"));
    assert.ok(has(errors(lcd("lcd", "[10,10,96,64]", `,"role":"top"`)), "/root/children/0/role", "role"));
    assert.ok(has(errors(`{"type":"screen","id":"s","source":"gameboy.lcd"}`), "/root/children/0/source", "gameboy.lcd"));
    assert.ok(has(errors(coin("c", "[10,200,60,60]", "arcade.jukebox")), "/root/children/0", "arcade.jukebox"));
    assert.ok(has(errors(coin("c", "[10,200,60,60]", "console.tvType")), "/root/children/0", "switch"));
    assert.ok(has(errors(`{"type":"group","id":"p","panel":{"name":"p","presentation":"shelf"}}`), "/root/children/0/panel/handle", "handle"));
    assert.ok(has(errors(`{"type":"group","id":"l","visible":{"flag":"panel.x.open"}}`), "/root/children/0/visible/flag", "panel.x.open"));
    assert.ok(has(errors(lcd(), ""), "/requires", "uses screens.accessory"));
    assert.ok(has(errors(lcd(), `"optional":["nope","screens.accessory"]`), "/optional/0", "nope"));
    assert.deepEqual(errors(`${panel()},${coin("coin", "[10,400,60,60]")}`), []);
    assert.throws(() => loadDocument(skin(`{"type":"group","panel":{"name":"a b"}}`)));
    assert.throws(() => loadDocument(skin(`{"type":"group","visible":{"has":7}}`)));
  });
  test("std.vmu is parts.std@2.1 and holds an accessory screen", () => {
    const text = skin(`{"use":"std.vmu","id":"v","with":{"source":"vmu.p2"}}`);
    const doc = loadDocument(text);
    const used = usedFeatures(parseJSON(text), [doc]);
    assert.ok(used.has("parts.std@2.1") && used.has("screens.accessory") && !used.has("parts.std@2.0"));
    const r = resolve(doc, env({ capabilities: ["picture.vmu.p2"] }));
    assert.equal(resolutionNode(r, "v.lcd").node.source, "vmu.p2");
    assert.deepEqual(provided(r).pictures, ["vmu.p2"]);
  });
});
