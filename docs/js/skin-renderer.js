import { drawArtwork, loadImage } from "./skin/art.js";
import { listLayouts } from "./skin/info.js";
import { findAsset } from "./skin/validate.js";
import { readEntry, readSkin } from "./skin/zip.js";
import { collectAssetPaths, loadDocument, loadDocumentJSON, makeEnvironment, renderToSurface, resolve, resolutionScreens } from "./skin2/index.js";

export { listLayouts, readSkin };

function createSurface(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

/** Render a Format 2 document on a caller-selected display, with optional decoded assets and fonts. */
export function renderSkinDocument(source, {
  environment = { size: { width: 393, height: 852 }, displayType: "edgeToEdge" },
  theme, variant, edits, scale = 1, surface = createSurface,
  images, fonts, screenPlaceholders = false,
} = {}) {
  const doc = typeof source === "string"
    ? loadDocument(source, { theme, variant })
    : loadDocumentJSON(source, { theme, variant });
  const resolution = resolve(doc, makeEnvironment(environment.size, environment), edits);
  return {
    canvas: renderToSurface(resolution, scale, { surface, images, fonts, screenPlaceholders }),
    resolution,
    screens: resolutionScreens(resolution).map(screen => screen.frame),
  };
}

/** A bezel is a Format 2 TV document with one tube. Its frame is in canvas layout units. */
export function renderBezel(source, { width = 1920, height = 1080, ...options } = {}) {
  const result = renderSkinDocument(source, {
    ...options, environment: { size: { width, height }, device: "tv", displayType: "standard", orientation: "landscape" },
  });
  if (result.screens.length !== 1 || result.screens[0].width <= 0 || result.screens[0].height <= 0) {
    throw new Error("A bezel must have one visible screen with a positive size.");
  }
  return { ...result, tube: result.screens[0] };
}

/** Draw a resting Delta or Manic layout from a decoded archive. */
export async function renderClassicSkin(archive, { path, alternate = false, maxDimension = 800 } = {}) {
  const layouts = listLayouts(alternate ? archive.info.altRepresentations : archive.info.representations);
  const selected = path ? layouts.find(row => row.path.join("/") === path.join("/")) : layouts[0];
  if (!selected) throw new Error("No matching skin layout.");
  const { layout } = selected;
  let mapping = archive.info.mappingSize;
  let parent = alternate ? archive.info.altRepresentations : archive.info.representations;
  for (const key of selected.path) {
    parent = parent[key];
    mapping = parent.mappingSize ?? mapping;
  }
  mapping = layout.mappingSize ?? mapping;
  if (![mapping?.width, mapping?.height, maxDimension].every(n => Number.isFinite(n) && n > 0)) {
    throw new Error("The layout needs a positive mapping size.");
  }
  const scale = Math.min(1, Math.min(4096, maxDimension) / Math.max(mapping.width, mapping.height));
  const canvas = createSurface(Math.max(1, Math.round(mapping.width * scale)), Math.max(1, Math.round(mapping.height * scale)));
  const ctx = canvas.getContext("2d");
  ctx.scale(canvas.width / mapping.width, canvas.height / mapping.height);
  async function paint(names, frame) {
    for (const name of names) {
      if (typeof name !== "string" || !name) continue;
      const asset = findAsset(archive.entries, name);
      if (!asset) continue;
      const bytes = await readEntry(archive, asset);
      if (!bytes) continue;
      const isPDF = [37, 80, 68, 70, 45].every((byte, i) => bytes[i] === byte);
      const file = isPDF ? "art.pdf" : asset.replace(/\.pdf$/i, ".png");
      try {
        await drawArtwork(ctx, bytes, file, frame.x, frame.y, frame.width, frame.height);
        return true;
      } catch (error) {
        // Other representations of the same art may still decode.
        console.warn("Could not draw skin art", asset, error);
      }
    }
    return false;
  }
  const assets = layout.assets ?? {};
  if (!await paint([assets.resizable, assets.large, assets.medium, assets.small], { x: 0, y: 0, ...mapping })) {
    throw new Error("The layout has no usable background.");
  }
  const items = Array.isArray(layout.items) ? layout.items : [];
  for (const item of items) {
    const frame = item?.frame;
    if (!frame || ![frame.x, frame.y, frame.width, frame.height].every(Number.isFinite)) continue;
    await paint([item.states?.normal?.image, item.asset?.normal], frame);
  }
  for (const item of items) {
    const stick = item?.thumbstick;
    const frame = item?.frame;
    if (!stick || !frame || ![frame.x, frame.y, frame.width, frame.height, stick.width, stick.height].every(Number.isFinite)) continue;
    await paint([stick.name], {
      x: frame.x + (frame.width - stick.width) / 2,
      y: frame.y + (frame.height - stick.height) / 2,
      width: stick.width, height: stick.height,
    });
  }
  return { canvas, path: selected.path, layout };
}

/** Open and draw an archive, using its embedded Format 2 document when present.
 * Pass JSZip explicitly or load it in the browser before calling this function.
 */
export async function renderSkin(data, options = {}) {
  const archive = await readSkin(data, options);
  if (!archive.info.format2) return renderClassicSkin(archive, options);
  const source = await readEntry(archive, "skin.json", "string");
  if (!source) throw new Error("The archive declares Format 2 but has no skin.json.");
  const theme = options.theme ?? archive.info.format2.theme;
  const variant = options.variant ?? archive.info.format2.variant;
  const doc = loadDocument(source, { theme, variant });
  const images = new Map(options.images);
  for (const name of collectAssetPaths(doc).images) {
    if (images.has(name)) continue;
    const bytes = await readEntry(archive, `assets/${name}`);
    if (bytes) images.set(name, await loadImage(bytes, name));
  }
  return renderSkinDocument(source, { ...options, theme, variant, images });
}

export { collectAssetPaths };
