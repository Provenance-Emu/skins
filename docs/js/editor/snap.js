/* EmuSkins — snapping for the skin editor (docs/js/editor/).

   Moving or resizing a frame snaps its edges (and, when moving, its center) to
   the edges of the other items and screens, to the mapping frame's edges and to
   its center, when one is within `threshold` mapping points. Pure: the page
   converts its pixel threshold (SNAP_PX) to points and draws the guides.
*/

import { edgesOf, normFrame, roundFrame, MIN_SIZE } from "./geometry.js";

/** How close, in screen pixels, an edge has to get before it snaps. */
export const SNAP_PX = 6;

/**
 * The lines a frame can snap to: { xs, ys } sorted and unique.
 *   layout   the layout object (mappingSize, items, screens)
 *   skip     { kind: "item" | "screen", index } the thing being dragged, left out
 */
export function snapTargets(layout, skip = null) {
  const xs = new Set(), ys = new Set();
  const m = layout && layout.mappingSize;
  if (m && m.width > 0 && m.height > 0) {
    xs.add(0); xs.add(m.width); xs.add(m.width / 2);
    ys.add(0); ys.add(m.height); ys.add(m.height / 2);
  }
  const add = frame => {
    if (!frame) return;
    const e = edgesOf(normFrame(frame));
    xs.add(e.left); xs.add(e.right);
    ys.add(e.top); ys.add(e.bottom);
  };
  ((layout && layout.items) || []).forEach((it, i) => { if (!(skip && skip.kind === "item" && skip.index === i)) add(it && it.frame); });
  ((layout && layout.screens) || []).forEach((s, i) => { if (!(skip && skip.kind === "screen" && skip.index === i)) add(s && s.outputFrame); });
  const sort = set => [...set].sort((a, b) => a - b);
  return { xs: sort(xs), ys: sort(ys) };
}

/** The smallest shift (target - candidate) within threshold, or null. */
function bestShift(candidates, targets, threshold) {
  let best = null;
  for (const c of candidates) {
    for (const t of targets) {
      const d = t - c;
      if (Math.abs(d) <= threshold && (best === null || Math.abs(d) < Math.abs(best.d))) best = { d, at: t };
    }
  }
  return best;
}

/**
 * Snap a frame that is being moved. Returns { frame, guides: { x: [..], y: [..] } }:
 * the frame shifted by the snapping, and the target lines it landed on.
 */
export function snapMove(frame, targets, threshold) {
  const e = edgesOf(frame);
  const sx = bestShift([e.left, e.right, e.cx], targets.xs, threshold);
  const sy = bestShift([e.top, e.bottom, e.cy], targets.ys, threshold);
  return {
    frame: { x: frame.x + (sx ? sx.d : 0), y: frame.y + (sy ? sy.d : 0), width: frame.width, height: frame.height },
    guides: { x: sx ? [sx.at] : [], y: sy ? [sy.at] : [] },
  };
}

/**
 * Snap the edges a corner handle is moving. `frame` is the resized frame; only the
 * dragged corner's two edges move, and never below `min` in size.
 */
export function snapResize(frame, handle, targets, threshold, min = MIN_SIZE) {
  const west = handle.includes("w"), north = handle.includes("n");
  let left = frame.x, right = frame.x + frame.width, top = frame.y, bottom = frame.y + frame.height;
  const sx = bestShift([west ? left : right], targets.xs, threshold);
  const sy = bestShift([north ? top : bottom], targets.ys, threshold);
  if (sx) { if (west) left = Math.min(left + sx.d, right - min); else right = Math.max(right + sx.d, left + min); }
  if (sy) { if (north) top = Math.min(top + sy.d, bottom - min); else bottom = Math.max(bottom + sy.d, top + min); }
  return {
    frame: roundFrame({ x: left, y: top, width: right - left, height: bottom - top }),
    guides: { x: sx ? [sx.at] : [], y: sy ? [sy.at] : [] },
  };
}
