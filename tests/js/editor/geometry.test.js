// geometry.js and snap.js: frame math, nudges, view conversion, snapping.

import { test } from "node:test";
import assert from "node:assert/strict";

import { moveFrame, resizeFrame, nudgeDelta, outsetFrame, effectiveEdges, edgesOf, fitScale, makeView, frameToPx, inputStripSize, normFrame, MIN_SIZE } from "../../../docs/js/editor/geometry.js";
import { snapTargets, snapMove, snapResize } from "../../../docs/js/editor/snap.js";

const F = { x: 100, y: 200, width: 80, height: 40 };

test("move shifts the origin and keeps the size", () => {
  assert.deepEqual(moveFrame(F, 5, -7), { x: 105, y: 193, width: 80, height: 40 });
});

test("normFrame fills missing numbers with 0", () => {
  assert.deepEqual(normFrame({ x: 3 }), { x: 3, y: 0, width: 0, height: 0 });
  assert.deepEqual(normFrame(undefined), { x: 0, y: 0, width: 0, height: 0 });
});

test("resize from each corner keeps the opposite corner fixed", () => {
  assert.deepEqual(resizeFrame(F, "se", 10, 20), { x: 100, y: 200, width: 90, height: 60 });
  assert.deepEqual(resizeFrame(F, "nw", -10, -20), { x: 90, y: 180, width: 90, height: 60 });
  assert.deepEqual(resizeFrame(F, "ne", 10, -20), { x: 100, y: 180, width: 90, height: 60 });
  assert.deepEqual(resizeFrame(F, "sw", -10, 20), { x: 90, y: 200, width: 90, height: 60 });
});

test("resize cannot go below the minimum size or flip over", () => {
  const r = resizeFrame(F, "se", -500, -500);
  assert.deepEqual(r, { x: 100, y: 200, width: MIN_SIZE, height: MIN_SIZE });
  const l = resizeFrame(F, "nw", 500, 500);
  assert.equal(l.width, MIN_SIZE);
  assert.equal(l.x + l.width, 180, "the south-east corner stayed");
  assert.equal(l.y + l.height, 240);
});

test("aspect lock keeps the ratio and follows the larger change", () => {
  const r = resizeFrame(F, "se", 40, 0, { lockAspect: true });
  assert.deepEqual(r, { x: 100, y: 200, width: 120, height: 60 });
  const byHeight = resizeFrame(F, "se", 0, 40, { lockAspect: true });
  assert.deepEqual(byHeight, { x: 100, y: 200, width: 160, height: 80 });
  const nw = resizeFrame(F, "nw", -40, 0, { lockAspect: true });
  assert.deepEqual(nw, { x: 60, y: 180, width: 120, height: 60 }, "grows toward the north-west, south-east corner fixed");
});

test("aspect lock respects the minimum", () => {
  const r = resizeFrame(F, "se", -1000, 0, { lockAspect: true });
  assert.ok(r.width >= MIN_SIZE && r.height >= MIN_SIZE);
  assert.equal(r.width / r.height, 2);
});

test("arrow keys nudge by one point, shift by ten", () => {
  assert.deepEqual(nudgeDelta("ArrowLeft"), { dx: -1, dy: 0 });
  assert.deepEqual(nudgeDelta("ArrowDown", true), { dx: 0, dy: 10 });
  assert.equal(nudgeDelta("a"), null);
});

test("extended edges outset the frame; a missing side is 0; the item's own edges win over the layout's", () => {
  assert.deepEqual(outsetFrame(F, { top: 4, left: 2 }), { x: 98, y: 196, width: 82, height: 44 });
  assert.deepEqual(outsetFrame(F, null), F);
  assert.deepEqual(effectiveEdges({ extendedEdges: { top: 1 } }, { extendedEdges: { top: 9 } }), { top: 1 });
  assert.deepEqual(effectiveEdges({}, { extendedEdges: { top: 9 } }), { top: 9 });
  assert.equal(effectiveEdges({}, {}), null);
});

test("edgesOf gives the edges and the center", () => {
  assert.deepEqual(edgesOf(F), { left: 100, right: 180, top: 200, bottom: 240, cx: 140, cy: 220 });
});

test("view converts between mapping points and pixels", () => {
  const v = makeView({ width: 414, height: 896 }, 0.5);
  assert.equal(v.pxWidth, 207);
  assert.equal(v.toPx(100), 50);
  assert.equal(v.toModel(50), 100);
  assert.deepEqual(frameToPx(F, v), { left: 50, top: 100, width: 40, height: 20 });
});

test("fitScale fits the mapping in the space, up to a maximum", () => {
  assert.equal(fitScale({ width: 400, height: 800 }, 800, 400), 0.5);
  assert.equal(fitScale({ width: 100, height: 100 }, 1000, 1000), 1.5);
  assert.equal(fitScale({ width: 0, height: 0 }, 100, 100), 1);
});

test("the input strip spans the farthest inputFrame, 256x240 by default", () => {
  assert.deepEqual(inputStripSize([]), { width: 256, height: 240 });
  assert.deepEqual(inputStripSize([{ inputFrame: { x: 0, y: 0, width: 256, height: 192 } }, { inputFrame: { x: 0, y: 192, width: 256, height: 192 } }]), { width: 256, height: 384 });
});

// ── snapping ─────────────────────────────────────────────────────────────

const LAYOUT = {
  mappingSize: { width: 400, height: 800 },
  items: [{ frame: { x: 10, y: 600, width: 50, height: 50 } }, { frame: { x: 300, y: 600, width: 50, height: 50 } }],
  screens: [{ outputFrame: { x: 0, y: 0, width: 400, height: 300 } }],
};

test("targets: the frame's edges and center, other items' and screens' edges; the dragged one is left out", () => {
  const t = snapTargets(LAYOUT, { kind: "item", index: 0 });
  assert.deepEqual(t.xs, [0, 200, 300, 350, 400]);
  assert.deepEqual(t.ys, [0, 300, 400, 600, 650, 800]);
  assert.ok(snapTargets(LAYOUT).xs.includes(60), "all items when nothing is skipped");
});

test("moving snaps an edge to a target within the threshold", () => {
  const t = snapTargets(LAYOUT, { kind: "item", index: 0 });
  const r = snapMove({ x: 296, y: 603, width: 50, height: 50 }, t, 6);
  assert.deepEqual(r.frame, { x: 300, y: 600, width: 50, height: 50 });
  assert.deepEqual(r.guides, { x: [300], y: [600] });
});

test("moving snaps the center to the frame center", () => {
  const t = snapTargets(LAYOUT, { kind: "item", index: 0 });
  const r = snapMove({ x: 177, y: 450, width: 50, height: 50 }, t, 6);
  assert.equal(r.frame.x, 175, "center 202 moves to 200");
  assert.deepEqual(r.guides.x, [200]);
});

test("outside the threshold nothing moves and there are no guides", () => {
  const t = snapTargets(LAYOUT, { kind: "item", index: 0 });
  const r = snapMove({ x: 120, y: 450, width: 50, height: 50 }, t, 3);
  assert.deepEqual(r.frame, { x: 120, y: 450, width: 50, height: 50 });
  assert.deepEqual(r.guides, { x: [], y: [] });
});

test("the nearest target wins", () => {
  // right edge 99 is 1 from 100; left 97 is 3 away and the center 98 is 2 away
  const r = snapMove({ x: 97, y: 0, width: 2, height: 10 }, { xs: [100, 95], ys: [] }, 6);
  assert.equal(r.frame.x, 98);
  assert.deepEqual(r.guides.x, [100]);
});

test("resizing snaps only the edges the handle moves", () => {
  const t = snapTargets(LAYOUT, { kind: "item", index: 0 });
  const r = snapResize({ x: 100, y: 500, width: 197, height: 98 }, "se", t, 6);
  assert.deepEqual(r.frame, { x: 100, y: 500, width: 200, height: 100 });
  assert.deepEqual(r.guides, { x: [300], y: [600] });
  const nw = snapResize({ x: 97, y: 703, width: 100, height: 97 }, "nw", { xs: [100], ys: [700] }, 6);
  assert.deepEqual(nw.frame, { x: 100, y: 700, width: 97, height: 100 }, "right and bottom stayed");
});

test("snapping a resize never shrinks below the minimum", () => {
  const r = snapResize({ x: 100, y: 100, width: 6, height: 6 }, "se", { xs: [100], ys: [100] }, 8);
  assert.ok(r.frame.width >= MIN_SIZE && r.frame.height >= MIN_SIZE);
});
