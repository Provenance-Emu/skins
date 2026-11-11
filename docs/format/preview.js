/* EmuSkins — format 2.0 documentation helpers shared by the live examples and the playground: rendering one
   trait of a source, printing JSON compactly, colouring it, and finding a JSON pointer in its text. */
import { loadPreviewFonts } from "../js/skin2/catalog-preview.js";
import { loadDocument, renderToSurface, resolutionControls, resolve, traitSetsFor } from "../js/skin2/index.js";

export const DEFAULT_FAMILY = "iphone.edgeToEdge";

export const FAMILY_LABELS = {
  "iphone.standard": "iPhone with Home button",
  "iphone.edgeToEdge": "iPhone",
  "ipad.standard": "iPad",
  "ipad.splitView": "iPad Split View",
  "tv.standard": "Apple TV",
};

function surface(width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

/** The trait set to preview: the wanted family and orientation, else the nearest the source bakes to. */
export function pickTrait(doc, family = DEFAULT_FAMILY, orientation = "portrait") {
  const traits = traitSetsFor(doc.bake?.traits);
  const inFamily = traits.filter((trait) => trait.family === family);
  const pool = inFamily.length ? inFamily : traits.filter((trait) => trait.family === traits[0]?.family);
  return pool.find((trait) => trait.orientation === orientation) ?? pool[0];
}

function drawGuides(canvas, scale, resolution, trait) {
  const ctx = canvas.getContext("2d");
  ctx.save();
  ctx.scale(scale, scale);
  ctx.lineWidth = 1;
  const { top, left, bottom, right } = trait.safeArea;
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = "rgba(255,255,255,0.45)";
  ctx.strokeRect(left + 0.5, top + 0.5, trait.size.width - left - right - 1, trait.size.height - top - bottom - 1);
  ctx.setLineDash([3, 3]);
  ctx.strokeStyle = "#00F2F2";
  for (const control of resolutionControls(resolution)) {
    const { x, y, width, height } = control.hitFrame ?? control.frame;
    ctx.strokeRect(x + 0.5, y + 0.5, width - 1, height - 1);
  }
  ctx.restore();
}

/** Renders one trait of `source`. Returns the canvas with the document and trait it shows. */
export async function renderPreview(source, { theme, variant, family, orientation, guides = false } = {}) {
  const doc = loadDocument(source, { theme, variant });
  const trait = pickTrait(doc, family, orientation);
  if (!trait) throw new Error("The skin lists no trait this preview can draw.");
  const { regular, bold } = await loadPreviewFonts();
  const { width, height } = trait.size;
  const scale = (globalThis.devicePixelRatio || 1) > 1 && width * height <= 1_100_000 ? 2 : 1;
  const resolution = resolve(doc, trait.environment);
  const canvas = renderToSurface(resolution, scale, {
    surface, images: new Map(), fonts: { regular, bold, families: new Map() }, screenPlaceholders: true,
  });
  if (guides) drawGuides(canvas, scale, resolution, trait);
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `${trait.orientation} skin layout`);
  canvas.dataset.orientation = trait.orientation;
  canvas.style.aspectRatio = `${width} / ${height}`;
  return { canvas, doc, trait, controls: resolutionControls(resolution).length };
}

/** JSON with two-space indentation that keeps a shallow array or object on one line when it fits. */
export function formatJSON(value, width = 92) {
  const depth = (v) => v === null || typeof v !== "object" ? 0 : 1 + Math.max(0, ...Object.values(v).map(depth));
  const inline = (v) => {
    if (v === null || typeof v !== "object") return JSON.stringify(v);
    if (Array.isArray(v)) return "[" + v.map(inline).join(", ") + "]";
    const entries = Object.entries(v).map(([key, child]) => `${JSON.stringify(key)}: ${inline(child)}`);
    return entries.length ? "{ " + entries.join(", ") + " }" : "{}";
  };
  const print = (v, indent, lead) => {
    if (v === null || typeof v !== "object") return JSON.stringify(v);
    const flat = inline(v);
    if (depth(v) <= 2 && lead + flat.length <= width) return flat;
    const inner = indent + "  ";
    if (Array.isArray(v) && depth(v) === 1) {
      const lines = [];
      for (const item of v.map((child) => JSON.stringify(child))) {
        const last = lines[lines.length - 1];
        if (last !== undefined && inner.length + last.length + 2 + item.length <= width) lines[lines.length - 1] = `${last}, ${item}`;
        else lines.push(item);
      }
      return "[\n" + lines.map((line) => inner + line).join(",\n") + "\n" + indent + "]";
    }
    const body = Array.isArray(v)
      ? v.map((child) => inner + print(child, inner, inner.length))
      : Object.entries(v).map(([key, child]) => {
        const name = JSON.stringify(key) + ": ";
        return inner + name + print(child, inner, inner.length + name.length);
      });
    return (Array.isArray(v) ? "[\n" : "{\n") + body.join(",\n") + "\n" + indent + (Array.isArray(v) ? "]" : "}");
  };
  return print(value, "", 0) + "\n";
}

/** `text` as HTML with a span around each key, string, number and literal. */
export function highlightJSON(text) {
  const escaped = text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  return escaped.replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,
    (match, string, colon) => {
      if (string) return colon ? `<span class="j-key">${string}</span>${colon}` : `<span class="j-str">${string}</span>`;
      return `<span class="${/\d/.test(match[match.length - 1]) ? "j-num" : "j-lit"}">${match}</span>`;
    });
}

/** The character range of the value a JSON pointer names in `text`, or of its nearest ancestor that parses. */
export function locatePointer(text, pointer) {
  const tokens = pointer.split("/").slice(1).map((token) => token.replace(/~1/g, "/").replace(/~0/g, "~"));
  let at = 0;
  const space = () => { while (/\s/.test(text[at] ?? "")) at++; };
  const string = () => {
    const from = at++;
    while (at < text.length && text[at] !== '"') at += text[at] === "\\" ? 2 : 1;
    at++;
    return text.slice(from, at);
  };
  // Skips one value and returns its range, descending first when `path` names a child.
  const value = (path) => {
    space();
    const from = at;
    let found;
    if (text[at] === "{" || text[at] === "[") {
      const isObject = text[at] === "{";
      const close = isObject ? "}" : "]";
      at++;
      for (let index = 0; ; index++) {
        space();
        if (at >= text.length) throw new Error("unterminated");
        if (text[at] === close) { at++; break; }
        let key = String(index);
        if (isObject) {
          key = JSON.parse(string());
          space();
          at++;
        }
        const wanted = path !== null && path.length > 0 && path[0] === key;
        const child = value(wanted ? path.slice(1) : null);
        if (wanted) found = child;
        space();
        if (text[at] === ",") at++;
      }
    } else if (text[at] === '"') {
      string();
    } else {
      while (at < text.length && !/[\s,\]}]/.test(text[at])) at++;
      if (at === from) throw new Error("unexpected");
    }
    return path === null ? undefined : found ?? { start: from, end: at };
  };
  try {
    return value(tokens);
  } catch {
    return undefined;
  }
}
