// The line resolver against the shared cases (fixtures/lines/resolve-cases.json).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
require("../../../docs/js/lines.js");
const L = globalThis.emuskinsLines;
const doc = JSON.parse(readFileSync(new URL("../../../fixtures/lines/resolve-cases.json", import.meta.url), "utf8"));
const { line, members } = doc;

for (const c of doc.cases) {
  test(`${c.fn}: ${c.name}`, () => {
    const a = c.args;
    if (c.fn === "isAvailable") {
      assert.equal(L.isAvailable(line, members, a.selection, a.axisId, a.valueId), c.expect);
      return;
    }
    let out;
    if (c.fn === "resolve") {
      out = L.resolve(line, members, a.selection, a.changedAxis ?? null);
    } else {
      const selection = L.initialSelection(line, members, a.traits, a.stored ?? null);
      out = L.resolve(line, members, selection);
      assert.deepEqual(selection, out.selection, "initialSelection returns a resolved selection");
    }
    assert.equal(out.member.id, c.expect.member);
    assert.deepEqual(out.selection, c.expect.selection);
  });
}

test("values: a string or a list", () => {
  assert.deepEqual(L.values("a"), ["a"]);
  assert.deepEqual(L.values(["a", "b"]), ["a", "b"]);
  assert.deepEqual(L.values(undefined), []);
});

test("memberById and selectionFor", () => {
  const d1 = L.memberById(members, "d1");
  assert.equal(d1.id, "d1");
  assert.equal(L.memberById(members, "nope"), undefined);
  assert.deepEqual(L.selectionFor(d1), { device: "island", game: "tate", hand: "right", colour: "red" });
});

test("resolve does not change its arguments", () => {
  const selection = { device: "ipad", colour: "blue" };
  const before = JSON.stringify([line, members, selection]);
  L.resolve(line, members, selection, "colour");
  assert.equal(JSON.stringify([line, members, selection]), before);
});

test("resolve with no members returns no member", () => {
  assert.equal(L.resolve(line, [], {}).member, null);
});

test("mapping axis takes the host's first supported mapping", () => {
  const mline = {
    axes: [{ id: "map", role: "mapping", values: [
      { id: "new", mapping: "manic-2.0.2" }, { id: "old", mapping: "manic-2.0.1" }] }],
    default: { map: "new" },
  };
  const ms = [{ id: "n", options: { map: "new" } }, { id: "o", options: { map: "old" } }];
  assert.deepEqual(L.initialSelection(mline, ms, { mappings: ["manic-2.0.1", "manic-2.0.2"] }), { map: "old" });
  assert.deepEqual(L.initialSelection(mline, ms, { mappings: ["other"] }), { map: "new" });
});
