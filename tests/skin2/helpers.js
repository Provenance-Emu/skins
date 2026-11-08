/* Shared helpers for the skin 2.0 tests: where the fixtures are, how a reference image is named and rendered
   (the same set SkinKit's ReferenceImageTests renders), the layout files FixtureTests records, headless canvas
   and font loading, and the pixelmatch comparison of section 9.3. */

import { createCanvas, loadImage } from "@napi-rs/canvas";
import opentype from "opentype.js";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  controlStateFromJSON, layoutRecord, loadDocument, renderToSurface, resolve as resolveLayout, traitSetsFor, validateText,
} from "../../docs/js/skin2/index.js";

const here = dirname(fileURLToPath(import.meta.url));
export const FIXTURES = resolve(here, "../../fixtures/format2");
export const SKIN2_JS = resolve(here, "../../docs/js/skin2");

export const fixtureNames = readdirSync(FIXTURES, { withFileTypes: true })
  .filter((d) => d.isDirectory() && existsSync(join(FIXTURES, d.name, "skin.json")))
  .map((d) => d.name)
  .sort();

export const skinText = (name) => readFileSync(join(FIXTURES, name, "skin.json"), "utf8");
export const expectedDir = (name) => join(FIXTURES, name, "expected");

/** Parses a bundled/shipped font file for the renderer. */
export function parseFont(bytes) {
  return opentype.parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
}

let defaultFonts;
export function bundledFonts() {
  defaultFonts ??= {
    regular: parseFont(readFileSync(join(SKIN2_JS, "fonts/Outfit-Regular.ttf"))),
    bold: parseFont(readFileSync(join(SKIN2_JS, "fonts/Outfit-Bold.ttf"))),
  };
  return defaultFonts;
}

export const surface = (w, h) => createCanvas(w, h);

/** A fixture's themes, variants, trait sets and state sets, in the order SkinKit records them. */
export function fixtureDoc(name, options = {}) {
  return loadDocument(skinText(name), options);
}

/** File name → layout record for every layout.json this fixture records (SkinKit FixtureTests.records). */
export function layoutRecords(name) {
  const base = fixtureDoc(name);
  const out = {};
  for (const trait of traitSetsFor(base.bake?.traits)) {
    const baseRecord = layoutRecord(resolveLayout(base, trait.environment), trait.name);
    out[`${trait.name}.layout.json`] = baseRecord;
    for (const variant of Object.keys(base.variants).sort()) {
      const doc = fixtureDoc(name, { variant });
      out[`${trait.name}.variant-${variant}.layout.json`] = layoutRecord(resolveLayout(doc, trait.environment), trait.name);
    }
    for (const theme of base.themeNames) {
      const doc = fixtureDoc(name, { theme });
      const record = layoutRecord(resolveLayout(doc, trait.environment), trait.name);
      // Colour-only themes have no layout file: their layout is the base layout.
      if (JSON.stringify(record.nodes) !== JSON.stringify(baseRecord.nodes)) out[`${trait.name}.theme-${theme}.layout.json`] = record;
    }
  }
  return out;
}

export function stateSets(name) {
  const p = join(FIXTURES, name, "states.json");
  if (!existsSync(p)) return [];
  const root = JSON.parse(readFileSync(p, "utf8"));
  return Object.keys(root).sort().map((set) => {
    const states = {};
    for (const [id, raw] of Object.entries(root[set])) states[id] = controlStateFromJSON(raw);
    return [set, states];
  });
}

/** Every reference image of a fixture (SkinKit ReferenceImage.all): <trait>@2x.png, <trait>.variant-<name>@2x.png,
    <trait>.theme-<name>@2x.png for every theme, and <trait>.state-<name>@2x.png for each state set. */
export function referenceImages(name) {
  const base = fixtureDoc(name);
  const sets = stateSets(name);
  const out = [];
  for (const trait of traitSetsFor(base.bake?.traits)) {
    out.push({ file: `${trait.name}@2x.png`, trait });
    for (const variant of Object.keys(base.variants).sort()) out.push({ file: `${trait.name}.variant-${variant}@2x.png`, trait, variant });
    for (const theme of base.themeNames) out.push({ file: `${trait.name}.theme-${theme}@2x.png`, trait, theme });
    for (const [setName, states] of sets) out.push({ file: `${trait.name}.state-${setName}@2x.png`, trait, states });
  }
  return out;
}

/** Decoded assets a fixture's skin references: images under assets/ and fonts under assets/fonts/. */
export async function fixtureAssets(name, doc) {
  const { collectAssetPaths } = await import("../../docs/js/skin2/index.js");
  const { images: imagePaths, fonts: fontPaths } = collectAssetPaths(doc);
  const images = new Map();
  for (const src of imagePaths) {
    const p = join(FIXTURES, name, "assets", src);
    if (existsSync(p)) images.set(src, await loadImage(readFileSync(p)));
  }
  const families = new Map();
  for (const family of fontPaths) {
    const p = join(FIXTURES, name, "assets", "fonts", family);
    if (existsSync(p)) families.set(family, parseFont(readFileSync(p)));
  }
  return { images, fonts: { ...bundledFonts(), families } };
}

/** Renders one reference image of a fixture to a canvas. */
export async function renderReference(name, ref) {
  const doc = fixtureDoc(name, { theme: ref.theme, variant: ref.variant });
  const resolution = resolveLayout(doc, ref.trait.environment);
  const { images, fonts } = await fixtureAssets(name, doc);
  return renderToSurface(resolution, 2, { states: ref.states ?? {}, screenPlaceholders: true, images, fonts, surface });
}

export const readPNG = (buf) => PNG.sync.read(buf);

/** A recorded PNG's size and straight RGBA, decoded natively (pngjs is too slow for the iPad images). */
export async function decodePNG(bytes) {
  const image = await loadImage(bytes);
  const canvas = createCanvas(image.width, image.height);
  const ctx = canvas.getContext("2d");
  ctx.drawImage(image, 0, 0);
  const img = ctx.getImageData(0, 0, image.width, image.height);
  return { width: img.width, height: img.height, data: img.data };
}

/** The canvas's pixels as straight (non-premultiplied) RGBA, like a decoded PNG. */
export function pixelsOf(canvas) {
  const img = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  return { width: img.width, height: img.height, data: img.data };
}

/** Section 9.3: pixelmatch with threshold 0.1 (anti-aliased pixels count); returns the differing fraction and,
    when asked, a diff image. `actual` is a canvas, `expectedBytes` the recorded PNG. */
export async function comparePNG(actual, expectedBytes, { includeAA = true, wantDiff = false } = {}) {
  const a = pixelsOf(actual), e = await decodePNG(expectedBytes);
  if (a.width !== e.width || a.height !== e.height) return { fraction: 1, differing: -1, total: e.width * e.height, diff: null };
  const diff = new PNG({ width: a.width, height: a.height });
  const differing = pixelmatch(a.data, e.data, diff.data, a.width, a.height, { threshold: 0.1, includeAA });
  return { fraction: differing / (a.width * a.height), differing, total: a.width * a.height, diff: wantDiff ? PNG.sync.write(diff) : null };
}

/** Where failing comparisons leave the actual and diff images (never the repo). */
export function failureDir(name) {
  const dir = join(process.env.SKIN2_FAILURES ?? join(tmpdir(), "skin2-render-failures"), name);
  mkdirSync(dir, { recursive: true });
  return dir;
}

export function writeFailure(name, file, actual, diff) {
  const dir = failureDir(name);
  const stem = file.replace(/@2x\.png$/, "");
  writeFileSync(join(dir, `${stem}.actual.png`), actual.toBuffer("image/png"));
  if (diff) writeFileSync(join(dir, `${stem}.diff.png`), diff);
  return dir;
}

/** Tolerance by fixture (section 9.3): at most 0.25 % of pixels, 1.0 % for effects (blur kernels differ). */
export const tolerance = (name) => (name === "effects" ? 0.01 : 0.0025);

export { validateText };
