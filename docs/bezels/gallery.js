import { renderBezel } from "../js/skin-renderer.js";
import { loadPreviewFonts } from "../js/skin2/catalog-preview.js";

const choice = document.getElementById("bezel-choice");
const shape = document.getElementById("bezel-shape");
const source = document.getElementById("bezel-source");
const output = document.querySelector(".bezel-preview");
const status = document.querySelector("figcaption");
const artworks = new Map();
const shapes = { "16:9": 1920, "4:3": 1440, "21:9": 2520 };
let request = 0;
let bezels;

async function json(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("Could not load bezel artwork.");
  return response.json();
}

async function draw() {
  const ticket = ++request;
  const bezel = bezels.get(choice.value);
  const ratio = shape.value;
  output.setAttribute("aria-busy", "true");
  source.hidden = true;
  status.textContent = `Rendering ${bezel.name}…`;
  try {
    if (!artworks.has(bezel.id)) {
      artworks.set(bezel.id, json(bezel.artwork).catch(error => {
        artworks.delete(bezel.id);
        throw error;
      }));
    }
    const [artwork, fonts] = await Promise.all([
      artworks.get(bezel.id), loadPreviewFonts().catch(() => undefined),
    ]);
    if (ticket !== request) return;
    const width = shapes[ratio];
    const { canvas } = renderBezel(artwork, {
      width, height: 1080, scale: Math.min(1, 1200 / width), screenPlaceholders: true, fonts,
    });
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", `${bezel.name} bezel preview at ${ratio}`);
    output.replaceChildren(canvas);
    source.href = bezel.artwork;
    source.hidden = false;
    status.textContent = `${bezel.name} · ${ratio}`;
    const params = new URLSearchParams({ bezel: bezel.id, shape: ratio });
    history.replaceState(null, "", `?${params}`);
  } catch (error) {
    console.error("Bezel render failed", error);
    if (ticket === request) {
      output.replaceChildren();
      status.textContent = "Could not render this bezel. Try another display.";
    }
  } finally {
    if (ticket === request) output.setAttribute("aria-busy", "false");
  }
}

try {
  const catalog = await json("catalog.json");
  bezels = new Map(catalog.bezels.map(bezel => [bezel.id, bezel]));
  for (const bezel of bezels.values()) choice.add(new Option(bezel.name, bezel.id));
  const params = new URLSearchParams(location.search);
  if (bezels.has(params.get("bezel"))) choice.value = params.get("bezel");
  if (Object.hasOwn(shapes, params.get("shape"))) shape.value = params.get("shape");
  choice.disabled = false;
  choice.addEventListener("change", draw);
  shape.addEventListener("change", draw);
  await draw();
} catch {
  output.setAttribute("aria-busy", "false");
  status.textContent = "The bezel catalog could not be loaded.";
}
