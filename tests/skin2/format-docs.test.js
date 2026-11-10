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
