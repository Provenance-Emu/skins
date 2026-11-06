/* EmuSkins — frame math for the skin editor (docs/js/editor/).

   Pure functions over frames: { x, y, width, height } in a layout's mapping
   points. No DOM; the canvas code converts between mapping points and screen
   pixels with the view helpers here and does everything else with these.
*/

/** The smallest a button or screen can be dragged to, in mapping points. */
export const MIN_SIZE = 4;

export const HANDLES = ["nw", "ne", "sw", "se"];

const num = (v, fallback = 0) => (Number.isFinite(v) ? v : fallback);

/** A frame with all four numbers present, whatever the info.json had. */
export function normFrame(f) {
  return { x: num(f && f.x), y: num(f && f.y), width: num(f && f.width), height: num(f && f.height) };
}

export const roundFrame = f => ({ x: Math.round(f.x), y: Math.round(f.y), width: Math.round(f.width), height: Math.round(f.height) });

export const sameFrame = (a, b) => a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;

export const moveFrame = (f, dx, dy) => ({ x: f.x + dx, y: f.y + dy, width: f.width, height: f.height });

/** Edges and center of a frame. */
export function edgesOf(f) {
  return { left: f.x, right: f.x + f.width, top: f.y, bottom: f.y + f.height, cx: f.x + f.width / 2, cy: f.y + f.height / 2 };
}

/**
 * Drag a corner handle by (dx, dy) and return the new frame, rounded to whole points.
 *   handle      "nw" | "ne" | "sw" | "se" (the corner being dragged; the opposite one stays put)
 *   min         smallest width/height
 *   lockAspect  keep the frame's width:height ratio (the larger of the two relative changes wins)
 */
export function resizeFrame(f, handle, dx, dy, { min = MIN_SIZE, lockAspect = false } = {}) {
  const west = handle.includes("w"), north = handle.includes("n");
  let left = f.x, right = f.x + f.width, top = f.y, bottom = f.y + f.height;
  if (west) left += dx; else right += dx;
  if (north) top += dy; else bottom += dy;

  if (lockAspect && f.width > 0 && f.height > 0) {
    const sx = (right - left) / f.width, sy = (bottom - top) / f.height;
    let s = Math.abs(sx - 1) >= Math.abs(sy - 1) ? sx : sy;
    s = Math.max(s, min / f.width, min / f.height);
    const w = f.width * s, h = f.height * s;
    const anchorX = west ? f.x + f.width : f.x, anchorY = north ? f.y + f.height : f.y;
    left = west ? anchorX - w : anchorX;
    right = west ? anchorX : anchorX + w;
    top = north ? anchorY - h : anchorY;
    bottom = north ? anchorY : anchorY + h;
  } else {
    if (west) left = Math.min(left, right - min); else right = Math.max(right, left + min);
    if (north) top = Math.min(top, bottom - min); else bottom = Math.max(bottom, top + min);
  }
  return roundFrame({ x: left, y: top, width: right - left, height: bottom - top });
}

const ARROWS = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };

/** The (dx, dy) an arrow key nudges by: one mapping point, ten with shift. null for other keys. */
export function nudgeDelta(key, shift = false) {
  const d = ARROWS[key];
  return d ? { dx: d[0] * (shift ? 10 : 1), dy: d[1] * (shift ? 10 : 1) } : null;
}

/** The frame grown by an extendedEdges object ({top, bottom, left, right}, any may be missing). */
export function outsetFrame(f, ext) {
  const e = ext || {};
  const l = num(e.left), r = num(e.right), t = num(e.top), b = num(e.bottom);
  return { x: f.x - l, y: f.y - t, width: f.width + l + r, height: f.height + t + b };
}

/** An item's extended edges: its own, else the layout's, else none. */
export function effectiveEdges(item, layout) {
  return (item && item.extendedEdges) || (layout && layout.extendedEdges) || null;
}

// ── View: mapping points ⇄ screen pixels ─────────────────────────────────

/** Scale that fits a mapping size in the available pixels without upscaling past `max`. */
export function fitScale(mapping, availW, availH, max = 1.5) {
  const w = num(mapping && mapping.width), h = num(mapping && mapping.height);
  if (w <= 0 || h <= 0 || availW <= 0 || availH <= 0) return 1;
  return Math.min(max, availW / w, availH / h);
}

export function makeView(mapping, scale) {
  const width = num(mapping && mapping.width, 1), height = num(mapping && mapping.height, 1);
  return {
    scale, width, height,
    pxWidth: width * scale, pxHeight: height * scale,
    toPx: v => v * scale,
    toModel: px => px / scale,
  };
}

/** The pixel box of a frame in a view. */
export const frameToPx = (f, view) => ({ left: f.x * view.scale, top: f.y * view.scale, width: f.width * view.scale, height: f.height * view.scale });

/** The native-resolution strip the screen inputFrames live on: from the origin to the
    farthest inputFrame corner; 256×240 (NES) when there are none. */
export function inputStripSize(screens) {
  let width = 0, height = 0;
  for (const s of screens || []) {
    if (!s || !s.inputFrame) continue;
    const f = normFrame(s.inputFrame);
    width = Math.max(width, f.x + f.width);
    height = Math.max(height, f.y + f.height);
  }
  return width > 0 && height > 0 ? { width, height } : { width: 256, height: 240 };
}
