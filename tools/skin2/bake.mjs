import { createCanvas, loadImage, PDFDocument } from "@napi-rs/canvas";
import { PDFDocument as EditablePDF } from "pdf-lib";
import { zipSync } from "fflate";
import opentype from "opentype.js";
import { mkdir, readdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { bakeClassic, collectAssetPaths, drawResolution, renderToSurface } from "../../docs/js/skin2/index.js";

import { nativeSize } from "./native-size.mjs";

const parseFont = (bytes) => opentype.parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
const defaultFont = (face) => readFile(new URL(`../../docs/js/skin2/fonts/Outfit-${face}.ttf`, import.meta.url)).then(parseFont);

export async function bake(source, assets) {
  const [regular, bold] = await Promise.all([defaultFont("Regular"), defaultFont("Bold")]);
  const options = new WeakMap();
  async function renderOptions(doc) {
    if (options.has(doc)) return options.get(doc);
    const paths = collectAssetPaths(doc);
    const images = new Map();
    for (const path of paths.images) {
      const bytes = assets.get("assets/" + path);
      if (bytes) images.set(path, await loadImage(bytes));
    }
    const families = new Map();
    for (const path of paths.fonts) {
      const bytes = assets.get("assets/fonts/" + path);
      if (bytes) families.set(path, parseFont(bytes));
    }
    const result = { images, fonts: { regular, bold, families }, surface: createCanvas };
    options.set(doc, result);
    return result;
  }
  return bakeClassic(source, assets, {
    nativeSize,
    async pdf(doc, resolution, frame) {
      const pdf = new PDFDocument({ rasterDPI: 216 });
      const width = Math.ceil(frame.width), height = Math.ceil(frame.height);
      const context = pdf.beginPage(width, height);
      Object.defineProperty(context, "canvas", { value: frame });
      context.translate(-frame.x, -frame.y);
      drawResolution(resolution, context, { ...await renderOptions(doc), effectScale: 3 });
      pdf.endPage();
      const bytes = pdf.close();
      if (width === frame.width && height === frame.height) return bytes;
      const editable = await EditablePDF.load(bytes, { updateMetadata: false });
      editable.getPage(0).setMediaBox(0, height - frame.height, frame.width, frame.height);
      return editable.save();
    },
    async preview(doc, resolution) {
      const surface = renderToSurface(resolution, 2, await renderOptions(doc));
      return surface.toBuffer("image/png");
    },
  });
}

export async function bakeFile(sourcePath) {
  const root = dirname(sourcePath);
  const assets = new Map();
  async function readAssets(relative) {
    let entries;
    try {
      entries = await readdir(join(root, relative), { withFileTypes: true });
    } catch (error) {
      if (relative === "assets" && error.code === "ENOENT") return;
      throw error;
    }
    for (const entry of entries) {
      const name = relative + "/" + entry.name;
      if (entry.isDirectory()) await readAssets(name);
      else if (entry.isFile()) assets.set(name, await readFile(join(root, name)));
    }
  }
  await readAssets("assets");
  return bake(await readFile(sourcePath), assets);
}

async function main() {
  const [source, output, ...extra] = process.argv.slice(2);
  if (!source || !output || extra.length) throw new Error("usage: node bake.mjs <skin.json> <output-directory>");
  const bundles = await bakeFile(source);
  await mkdir(output, { recursive: true });
  for (const [index, bundle] of bundles.entries()) {
    const files = Object.create(null);
    for (const name of [...bundle.files.keys()].sort()) files[name] = bundle.files.get(name);
    const archive = zipSync(files, { mtime: new Date(2000, 0, 1) });
    const path = join(output, `skin-${index + 1}.deltaskin`);
    await writeFile(path, archive, { flag: "wx" });
    console.log(path);
    for (const warning of bundle.warnings) console.warn(warning);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => { console.error(error); process.exitCode = 1; });
}
