import { readEntry, readSkin } from "../skin/zip.js";
import { urlSource } from "../skin/source.js";
import { collectAssetPaths, loadDocument, renderToSurface, resolve, traitSetsFor } from "./index.js";

const dependencies = new Map();

function loadScript(global, src, integrity) {
  if (globalThis[global]) return Promise.resolve(globalThis[global]);
  if (!dependencies.has(global)) {
    const ready = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.integrity = integrity;
      script.crossOrigin = "anonymous";
      script.referrerPolicy = "no-referrer";
      script.onload = () => globalThis[global] ? resolve(globalThis[global]) : reject(new Error(global + " unavailable"));
      script.onerror = () => reject(new Error("Could not load " + global));
      document.head.append(script);
    });
    dependencies.set(global, ready.catch((error) => {
      dependencies.delete(global);
      throw error;
    }));
  }
  return dependencies.get(global);
}

const loadZip = () => loadScript("JSZip", "https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js",
  "sha512-XMVd28F1oH/O71fzwBnV7HucLxVwtxf26XV8P4wPk26EDxuGZ91N8bsOttmnomcCD3CS5ZMRL50H0GgOHvegtg==");
const loadFontParser = () => loadScript("opentype", "https://cdn.jsdelivr.net/npm/opentype.js@2.0.0/dist/opentype.min.js",
  "sha384-rZipYyCodoDMAXvm3BS6DXnn3CAyORo9RZ+7OSlLIj1y1YP4KeMFwgKVkO+9W3nB");

let previewFonts;

/** The bundled preview faces and the font parser, loaded once per page. */
export function loadPreviewFonts() {
  previewFonts ??= (async () => {
    const parser = await loadFontParser();
    const face = async (name) => {
      const response = await fetch(new URL(`fonts/Outfit-${name}.ttf`, import.meta.url));
      if (!response.ok) throw new Error("Could not load preview font");
      return parser.parse(await response.arrayBuffer());
    };
    const [regular, bold] = await Promise.all([face("Regular"), face("Bold")]);
    return { parser, regular, bold };
  })().catch((error) => {
    previewFonts = undefined;
    throw error;
  });
  return previewFonts;
}

function surface(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

async function loadPreview(data) {
  const archive = await readSkin(data, { JSZip: await loadZip() });
  const source = await readEntry(archive, "skin.json", "string");
  if (!source || !archive.info.format2) throw new Error("Choose a format 2 skin.");
  const { theme, variant } = archive.info.format2;
  return renderFormat2Previews(source, { theme, variant, readAsset: (name) => readEntry(archive, "assets/" + name) });
}

export async function renderFormat2Previews(source, { theme, variant, readAsset = async () => null } = {}) {
  const doc = loadDocument(source, { theme, variant });
  const paths = collectAssetPaths(doc);
  const images = new Map();
  const decoded = [];
  try {
    for (const name of paths.images) {
      const bytes = await readAsset(name);
      if (bytes) {
        const image = await createImageBitmap(new Blob([bytes]));
        decoded.push(image);
        images.set(name, image);
      }
    }
    const { parser, regular, bold } = await loadPreviewFonts();
    const families = new Map();
    for (const name of paths.fonts) {
      const bytes = await readAsset("fonts/" + name);
      if (bytes) families.set(name, parser.parse(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)));
    }
    const previews = new Map();
    for (const trait of traitSetsFor(doc.bake?.traits)) {
      if (trait.family !== "iphone.edgeToEdge") continue;
      previews.set(trait.orientation, renderToSurface(resolve(doc, trait.environment), 1, {
        surface, images, fonts: { regular, bold, families }, screenPlaceholders: true,
      }));
    }
    return previews;
  } finally {
    decoded.forEach((image) => image.close());
  }
}

/** Attaches a lazy preview to the open catalog detail. */
export function attachFormat2Preview(panel, downloadURL) {
  const status = panel.querySelector("[role=status]");
  const chooser = panel.querySelector("input");
  const fallback = panel.querySelector("label");
  const orientation = panel.querySelector("select");
  const output = panel.querySelector("[data-preview-output]");
  let previews;
  let started = false;
  let request = 0;

  function show() {
    const canvas = previews?.get(orientation.value);
    if (!canvas) return;
    canvas.setAttribute("aria-label", `${orientation.value} controller layout`);
    canvas.setAttribute("role", "img");
    canvas.style.cssText = "display:block;max-width:100%;height:auto;max-height:60vh;margin:0.5rem auto";
    output.replaceChildren(canvas);
  }

  async function open(read) {
    const ticket = ++request;
    status.textContent = "Loading preview…";
    try {
      const data = await read();
      if (!data) throw new Error("Download the skin, then choose the file to preview it.");
      const result = await loadPreview(data);
      if (ticket !== request || !panel.isConnected) return;
      previews = result;
      orientation.hidden = false;
      fallback.hidden = true;
      status.textContent = "";
      show();
    } catch (error) {
      if (ticket !== request || !panel.isConnected) return;
      fallback.hidden = false;
      status.textContent = error.message || "Could not render this skin.";
    }
  }

  orientation.addEventListener("change", show);
  chooser.addEventListener("change", () => {
    const file = chooser.files?.[0];
    if (file) void open(() => file);
  });
  panel.addEventListener("toggle", () => {
    if (!panel.open || started) return;
    started = true;
    void open(async () => {
      const result = await urlSource(downloadURL);
      return result.ok ? result.data : null;
    });
  });
  // The module can finish loading after the visitor expands the panel.
  if (panel.open) panel.dispatchEvent(new Event("toggle"));
}
