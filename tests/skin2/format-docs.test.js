import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";
import { renderToSurface, resolve, traitSetsFor, validateText } from "../../docs/js/skin2/index.js";
import { bundledFonts, surface } from "./helpers.js";

const examples = new URL("../../docs/format/examples/", import.meta.url);
for (const name of readdirSync(examples).filter((name) => name.endsWith(".json"))) {
  test(`the documentation example ${name} validates and renders both phone orientations`, () => {
    const report = validateText(readFileSync(new URL(name, examples), "utf8"));
    assert.deepEqual(report.errors, []);
    const traits = traitSetsFor(report.document.bake?.traits).filter(({ family }) => family === "iphone.edgeToEdge");
    assert.deepEqual(traits.map(({ orientation }) => orientation), ["portrait", "landscape"]);
    for (const { environment } of traits) {
      const result = renderToSurface(resolve(report.document, environment), 1, {
        surface, fonts: bundledFonts(), screenPlaceholders: true,
      });
      const pixels = result.getContext("2d").getImageData(0, 0, result.width, result.height).data;
      assert.ok(pixels.some((value, index) => index % 4 === 3 && value > 0), "preview has visible artwork");
    }
  });
}

test("the dreamcast-vmu example is the vendored fixture, validates clean and draws its panel only with the capability", () => {
  const text = readFileSync(new URL("dreamcast-vmu.json", examples), "utf8");
  assert.equal(text, readFileSync(new URL("../../fixtures/format2/dreamcast-vmu/skin.json", import.meta.url), "utf8"));
  const report = validateText(text);
  assert.deepEqual(report.issues, []);
  const trait = traitSetsFor(report.document.bake?.traits).find(({ name }) => name === "iphone-edgeToEdge-landscape");
  const draw = (capabilities, flags) => {
    const environment = { ...trait.environment, capabilities: new Set(capabilities), flags: new Set(flags) };
    const resolution = resolve(report.document, environment);
    const result = renderToSurface(resolution, 1, { surface, fonts: bundledFonts(), screenPlaceholders: true });
    return { resolution, data: Buffer.from(result.getContext("2d").getImageData(0, 0, result.width, result.height).data) };
  };
  const without = draw([], []), closed = draw(["picture.vmu.p1"], []), open = draw(["picture.vmu.p1"], ["panel.vmu.open"]);
  assert.deepEqual(without.resolution.provided, { pictures: [], inputs: [], panels: {} });
  assert.deepEqual(closed.resolution.provided, { pictures: ["vmu.p1"], inputs: [], panels: { vmu: false } });
  assert.deepEqual(open.resolution.provided.panels, { vmu: true });
  assert.ok(!without.data.equals(closed.data) && !closed.data.equals(open.data));
});

for (const name of ["gamecube-screen.json", "gamecube.json"]) {
  test(`${name} keeps its game viewport inside the safe area on every baked phone trait`, () => {
    const { document } = validateText(readFileSync(new URL(name, examples), "utf8"));
    for (const trait of traitSetsFor(document.bake.traits)) {
      const { frame } = resolve(document, trait.environment).root.children[0];
      const { left, right, top, bottom } = trait.safeArea;
      assert.ok(frame.x >= left && frame.y >= top, trait.name);
      assert.ok(frame.x + frame.width <= trait.size.width - right, trait.name);
      assert.ok(frame.y + frame.height <= trait.size.height - bottom, trait.name);
      assert.ok(Math.abs(frame.width - frame.height * 4 / 3) <= 1, trait.name);
    }
  });
}
