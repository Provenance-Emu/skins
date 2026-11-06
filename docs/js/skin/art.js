/* EmuSkins — artwork rasterizing for the shared skin stack (docs/js/skin/).

   Draws a skin's artwork onto a canvas: PNG/JPEG through <img>, PDF through
   pdf.js (pinned to 4.10.38, from cdnjs, loaded the first time a PDF turns up), SVG
   through <img> with a note that Delta and Manic will not draw it. The RetroArch
   converter uses it to emit PNGs; the editor uses it for the canvas background.

   Browser only (canvas, Image, URL.createObjectURL). Nothing here runs at import
   time, so Node can import the module for artKind() and SVG_NOTE.
*/

// Pinned to an exact version: a floating URL would let a CDN change reach every user of the site.
const PDFJS_BASE = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38";

export const SVG_NOTE = "Delta and Manic cannot draw SVG artwork. Use a PDF or PNG.";

/** "pdf" | "svg" | "raster" for an artwork file name. */
export function artKind(name) {
  const ext = String(name).split(".").pop().toLowerCase();
  return ext === "pdf" ? "pdf" : ext === "svg" ? "svg" : "raster";
}

function mimeFor(name) {
  const ext = String(name).split(".").pop().toLowerCase();
  return ext === "svg" ? "image/svg+xml" : ext === "jpg" || ext === "jpeg" ? "image/jpeg" : "image/png";
}

let pdfjs = null;
/** pdf.js, imported on first use. */
export function loadPdfJs() {
  if (!pdfjs) {
    pdfjs = import(/* pdf.js 4.10.38 */ `${PDFJS_BASE}/pdf.min.mjs`).then(lib => {
      lib.GlobalWorkerOptions.workerSrc = `${PDFJS_BASE}/pdf.worker.min.mjs`;
      return lib;
    });
  }
  return pdfjs;
}

/** Decode image bytes into an <img>. */
export async function loadImage(bytes, name) {
  const url = URL.createObjectURL(new Blob([bytes], { type: mimeFor(name) }));
  try {
    return await new Promise((ok, err) => {
      const i = new Image();
      i.onload = () => ok(i);
      i.onerror = () => err(new Error(`Could not decode ${name}`));
      i.src = url;
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** Natural size of an artwork file in its own units (PDF points, image pixels). */
export async function artworkSize(bytes, name) {
  if (artKind(name) === "pdf") {
    const lib = await loadPdfJs();
    const doc = await lib.getDocument({ data: bytes.slice(0), isEvalSupported: false }).promise;
    try {
      const vp = (await doc.getPage(1)).getViewport({ scale: 1 });
      return { width: vp.width, height: vp.height };
    } finally { doc.destroy(); }
  }
  const img = await loadImage(bytes, name);
  return { width: img.naturalWidth, height: img.naturalHeight };
}

/** Draw an artwork file (PDF, SVG or raster) stretched into w×h pixels of ctx at (x, y). */
export async function drawArtwork(ctx, bytes, name, x, y, w, h) {
  if (artKind(name) === "pdf") {
    const lib = await loadPdfJs();
    const doc = await lib.getDocument({ data: bytes.slice(0), isEvalSupported: false }).promise;
    try {
      const page = await doc.getPage(1);
      const vp = page.getViewport({ scale: 1 });
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(w / vp.width, h / vp.height);
      await page.render({ canvasContext: ctx, viewport: vp }).promise;
      ctx.restore();
    } finally { doc.destroy(); }
    return;
  }
  ctx.drawImage(await loadImage(bytes, name), x, y, w, h);
}

/** A new canvas of width×height pixels with the artwork stretched over it.
    Returns { canvas, note }; note is set for SVG artwork. */
export async function rasterize(bytes, name, width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width));
  canvas.height = Math.max(1, Math.round(height));
  await drawArtwork(canvas.getContext("2d"), bytes, name, 0, 0, canvas.width, canvas.height);
  return { canvas, note: artKind(name) === "svg" ? SVG_NOTE : null };
}

export const canvasToPng = canvas => new Promise(ok => canvas.toBlob(ok, "image/png"));
