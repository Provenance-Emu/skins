// zip.js and info.js: reading the archive layouts the tools accept, the lenient info.json parse,
// the round trip that keeps unknown keys, and writing a new archive.

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { JSZip, ROOT, zipFiles, zipDir, fixtureBytes } from "./helpers.js";
import { readSkin, readEntry, writeSkin, rewriteSkin, findInfoPath, SkinReadError, MAX_ARCHIVE_BYTES } from "../../../docs/js/skin/zip.js";
import { parseInfo, stripComments, stringifyInfo, cloneInfo, getIn, patchInfo, listLayouts, knownInputs } from "../../../docs/js/skin/info.js";

const INFO = { identifier: "com.example.t", name: "T", gameTypeIdentifier: "com.rileytestut.delta.game.gba", representations: { iphone: { edgeToEdge: { portrait: { assets: { resizable: "a.png" }, mappingSize: { width: 1, height: 2 }, items: [] } } } } };
const text = o => JSON.stringify(o);
const read = (data, opts) => readSkin(data, { JSZip, ...opts });

test("info.json at the root: entries are the archive's files", async () => {
  const skin = await read(await zipFiles({ "info.json": text(INFO), "a.png": "x", "Art/": "", "Art/b.png": "x" }));
  assert.equal(skin.infoPath, "info.json");
  assert.equal(skin.prefix, "");
  assert.deepEqual(skin.entries, ["info.json", "a.png", "Art/b.png"]);
  assert.deepEqual(skin.info, INFO);
  assert.equal(skin.rawInfo, text(INFO));
});

test("info.json one folder down: entries are relative to it, assets still read", async () => {
  const skin = await read(await zipFiles({ "Skin.deltaskin/info.json": text(INFO), "Skin.deltaskin/a.png": "PNG", "__MACOSX/Skin.deltaskin/._a.png": "x", ".DS_Store": "x" }));
  assert.equal(skin.infoPath, "Skin.deltaskin/info.json");
  assert.equal(skin.prefix, "Skin.deltaskin/");
  assert.deepEqual(skin.entries, ["info.json", "a.png"]);
  assert.equal(await readEntry(skin, "a.png", "string"), "PNG");
  assert.equal(await readEntry(skin, "missing.png"), null);
});

test("the root info.json wins over folders, and a pack lists the other candidates", async () => {
  assert.equal(findInfoPath(["B/info.json", "info.json", "A/info.json"]).path, "info.json");
  const f = findInfoPath(["B/info.json", "A/info.json", "A/deeper/info.json"]);
  assert.equal(f.path, "A/info.json");
  assert.deepEqual(f.alternates, ["B/info.json"]);
  assert.equal(findInfoPath(["A/deeper/info.json", "a.png"]), null, "two folders down is not a skin");
  assert.equal(findInfoPath(["__MACOSX/info.json", ".DS_Store"]), null);
});

test("comments, trailing commas and a BOM do not stop an archive from reading", async () => {
  const raw = "﻿{\n // Delta ignores this\n \"identifier\": \"i\", \"url\": \"http://x//y\", /* and this */\n \"list\": [1, 2,],\n}\n";
  const skin = await read(await zipFiles({ "info.json": raw }));
  assert.deepEqual(skin.info, { identifier: "i", url: "http://x//y", list: [1, 2] });
});

test("errors carry a code the page can turn into a message", async () => {
  const code = async (data, opts) => { try { await read(data, opts); } catch (e) { assert.ok(e instanceof SkinReadError); return e.code; } return "no error"; };
  assert.equal(await code(Buffer.from("not a zip at all")), "not_zip");
  assert.equal(await code(await zipFiles({ "a.png": "x" })), "no_info_json");
  assert.equal(await code(await zipFiles({ "info.json": "{ nope" })), "bad_info_json");
  assert.equal(await code({ byteLength: MAX_ARCHIVE_BYTES + 1 }), "too_large");
  await assert.rejects(readSkin(await zipFiles({ "info.json": "{}" })), e => e.code === "no_zip_library");
});

test("every fixture skin reads, with its info.json and artwork", async () => {
  for (const path of ["fixtures/variants/sample-nes.deltaskin", "fixtures/variants/sample-alt-ds.deltaskin", "fixtures/variants/sample-gameoverrides-jaguar.manicskin"]) {
    const skin = await read(readFileSync(join(ROOT, path)));
    assert.equal(skin.prefix, "", path);
    assert.ok(skin.info.identifier && skin.info.representations, path);
    assert.ok(skin.entries.some(e => e.endsWith(".png")), path);
  }
  const merge = await read(await zipDir(join(ROOT, "fixtures", "merge", "alt-two-layouts", "members", "1-blue")));
  assert.equal(merge.info.name, "Merge Test — Blue");
});

test("bytes, typed arrays and ArrayBuffers all read (browsers also pass a File; JSZip in Node cannot)", async () => {
  const bytes = await zipFiles({ "info.json": text(INFO) });
  assert.equal((await read(new Uint8Array(bytes))).info.name, "T");
  assert.equal((await read(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength))).info.name, "T");
});

// ── Round trips ──────────────────────────────────────────────────────────

test("unknown keys survive parse, patch and stringify untouched", async () => {
  const bytes = await fixtureBytes({ path: "fixtures/variants/sample-gameoverrides-jaguar.manicskin" });
  const skin = await read(bytes);
  const withUnknown = { ...skin.info, keyboardOverlay: { rows: [["q", "w"]], futureKey: { deep: [1, { x: null }] } }, haptic: { style: "soft" } };
  const edited = patchInfo(withUnknown, [{ op: "set", path: ["name"], value: "Renamed" }]);
  assert.equal(edited.name, "Renamed");
  assert.deepEqual({ ...edited, name: withUnknown.name }, withUnknown, "only the patched key changed");
  assert.deepEqual(parseInfo(stringifyInfo(edited)), edited);
  assert.deepEqual(Object.keys(parseInfo(stringifyInfo(edited))), Object.keys(withUnknown), "key order kept");
  assert.ok(stringifyInfo(edited).endsWith("}\n") && stringifyInfo(edited).includes('\n  "name"'));
});

test("patchInfo leaves its argument alone, creates paths and edits arrays", () => {
  const info = Object.freeze({ a: { b: [1, 2, 3] }, keep: { x: 1 } });
  const out = patchInfo(info, [
    { op: "set", path: ["a", "c", "d"], value: { v: 1 } },
    { op: "remove", path: ["a", "b", 1] },
    { op: "merge", path: ["keep"], value: { y: 2 } },
    { op: "remove", path: ["nope", "deeper"] },
  ]);
  assert.deepEqual(out, { a: { b: [1, 3], c: { d: { v: 1 } } }, keep: { x: 1, y: 2 } });
  assert.deepEqual(info, { a: { b: [1, 2, 3] }, keep: { x: 1 } });
  const value = { n: 1 };
  const set = patchInfo({}, [{ op: "set", path: ["k"], value }]);
  value.n = 2;
  assert.equal(set.k.n, 1, "the patch copies its value");
  assert.throws(() => patchInfo({}, [{ op: "set", path: ["__proto__", "x"], value: 1 }]));
  assert.throws(() => patchInfo({}, [{ op: "set", path: [], value: 1 }]));
  assert.throws(() => patchInfo({}, [{ op: "bogus", path: ["a"] }]));
  assert.equal(({}).x, undefined);
});

test("getIn and cloneInfo", () => {
  const info = { a: { b: [{ c: 1 }] } };
  assert.equal(getIn(info, ["a", "b", 0, "c"]), 1);
  assert.equal(getIn(info, ["a", "x", "y"]), undefined);
  assert.equal(getIn(info, []), info);
  const copy = cloneInfo(info);
  copy.a.b[0].c = 2;
  assert.equal(info.a.b[0].c, 1);
});

test("listLayouts finds layouts at any depth by their keys", () => {
  const reps = { iphone: { edgeToEdge: { portrait: { assets: {} }, landscape: { items: [] } } }, ipad: { standard: { portrait: { mappingSize: {} } } }, odd: [] };
  assert.deepEqual(listLayouts(reps).map(l => l.path.join("/")), ["iphone/edgeToEdge/portrait", "iphone/edgeToEdge/landscape", "ipad/standard/portrait"]);
  assert.deepEqual(listLayouts(null), []);
});

test("writeSkin makes an archive readSkin reads back, info.json first", async () => {
  const out = await writeSkin({ "a.png": "PNG", "Art/b.png": new Uint8Array([1, 2, 3]), "info.json": "ignored" }, INFO, { JSZip });
  const skin = await read(out);
  assert.deepEqual(skin.info, INFO);
  assert.equal(skin.names[0], "info.json");
  assert.equal(await readEntry(skin, "a.png", "string"), "PNG");
  assert.deepEqual([...await readEntry(skin, "Art/b.png")], [1, 2, 3]);
  assert.ok(skin.rawInfo.startsWith('{\n  "identifier"'), "pretty-printed");
  const buffer = await writeSkin({}, INFO, { JSZip, type: "arraybuffer" });
  assert.ok(buffer instanceof ArrayBuffer);
  assert.equal((await read(buffer)).info.name, "T");
});

test("rewriteSkin swaps info.json, copies the rest, and moves a folder skin to the root", async () => {
  const folder = await read(await zipFiles({ "S.deltaskin/info.json": text(INFO), "S.deltaskin/a.png": "PNG", "S.deltaskin/Art/b.png": "B", "other/stuff.txt": "no" }));
  const out = await read(await rewriteSkin(folder, { ...INFO, name: "New" }, { JSZip }));
  assert.equal(out.info.name, "New");
  assert.equal(out.prefix, "");
  assert.deepEqual(out.entries.sort(), ["Art/b.png", "a.png", "info.json"]);
  assert.equal(await readEntry(out, "Art/b.png", "string"), "B");
});

test("stripComments leaves strings alone", () => {
  assert.equal(stripComments('{"a": "x // y /* z */"} // end'), '{"a": "x // y /* z */"} ');
});

// ── inputs.json ──────────────────────────────────────────────────────────

const inputs = JSON.parse(readFileSync(join(ROOT, "docs", "js", "skin", "inputs.json"), "utf8"));
const raMap = JSON.parse(readFileSync(join(ROOT, "docs", "js", "skin", "retroarch-input-map.json"), "utf8"));

test("inputs.json offers Delta and Manic spellings plus Provenance's extras", () => {
  const names = group => knownInputs(inputs, "com.rileytestut.delta.game.snes").find(g => g.group === group).inputs;
  assert.deepEqual(names("buttons"), ["a", "b", "x", "y", "l", "r"]);
  assert.deepEqual(names("directions"), ["up", "down", "left", "right"]);
  for (const extra of ["toggleAltRepresentations", "quickSave", "menu"]) assert.ok(names("frontend").includes(extra), extra);
  assert.ok(knownInputs(inputs, "public.aoshuang.game.md")[0].inputs.includes("mode"), "Manic's Mega Drive id");
  assert.ok(knownInputs(inputs, "PUBLIC.AOSHUANG.GAME.PS1")[0].inputs.includes("cross"), "ids are case-insensitive");
  assert.ok(knownInputs(inputs, "com.rileytestut.delta.game.n64")[0].inputs.includes("c-up"), "aliases are offered");
  assert.deepEqual(knownInputs(inputs, "com.example.unknown")[0].inputs, inputs.default, "unknown types get the default set");
});

test("every game type's buttons are the ones retroarch-input-map.json tabulates for its system", () => {
  assert.ok(Object.keys(inputs.gameTypes).length >= 40);
  for (const [id, entry] of Object.entries(inputs.gameTypes)) {
    if (entry.system === null) { assert.equal(entry.buttons, null, id); continue; }
    const sys = raMap.systems[entry.system];
    assert.ok(sys, `${id} -> ${entry.system} exists in the map`);
    // Compared as sets: a JS object lists integer-like keys ("1", "2") first.
    assert.deepEqual([...entry.buttons].sort(), [...Object.keys(sys.map), ...Object.keys(sys.aliases || {})].sort(), id);
  }
  for (const t of [...inputs.directions, ...inputs.startSelect, ...inputs.sticks, ...inputs.frontend]) {
    assert.ok(Object.prototype.hasOwnProperty.call(raMap.common, t), `${t} is a token the converter knows`);
  }
});
