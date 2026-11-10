import assert from "node:assert/strict";
import { test } from "node:test";
import { bakeClassic } from "../../docs/js/skin2/bake.js";
import { skinText } from "./helpers.js";

const artwork = {
  pdf: async () => new Uint8Array(),
  preview: async () => new Uint8Array(),
  nativeSize: () => undefined,
};
const info = (bundle) => JSON.parse(new TextDecoder().decode(bundle.files.get("info.json")));
const bake = (name) => bakeClassic(new TextEncoder().encode(skinText(name)), new Map(), artwork);
const portrait = (skin) => skin.representations.iphone.edgeToEdge.portrait;

test("classic GameCube bake preserves left and right thumbstick inputs", async () => {
  const [base] = await bake("gamecube-icube");
  const sticks = portrait(info(base)).items.filter(({ thumbstick }) => thumbstick);
  assert.deepEqual(sticks.map(({ inputs }) => inputs.up).sort(), ["leftThumbstickUp", "rightThumbstickUp"]);
});

test("layout-changing themes have complete layouts of their own", async () => {
  const [base, ...other] = await bake("variants");
  assert.deepEqual(info(base).themes.map(({ id }) => id), ["red"]);
  const large = other.find(({ variantLabel }) => variantLabel === "big");
  assert.ok(large);
  assert.equal(info(large).format2.theme, "big");
  const width = (bundle) => portrait(info(bundle)).items.find(({ inputs }) => Array.isArray(inputs) && inputs.includes("a")).frame.width;
  assert.ok(width(large) > width(base));
});

test("unknown native resolution leaves the classic source crop unset", async () => {
  const [base] = await bake("layout");
  const [screen] = portrait(info(base)).screens;
  assert.ok(screen);
  assert.equal(screen.inputFrame, undefined);
});
