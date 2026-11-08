/* EmuSkins — skin format 2.0, shape outlines (docs/js/skin2/).

   Port of SkinKit's Skin2Shapes.swift (section 3, "Shape kinds"): shape outlines in canvas points. Conventions
   both renderers share: angles are degrees, 0 along +x, positive clockwise on screen (y is down). Polygons and
   stars start with a vertex along +x (0°) before `rotation`, so a triangle with rotation -90 points up. Lengths
   (cornerRadius) resolve with % against the frame's short side. Squircles use the shared cubic approximation. */
import { rect as R } from "./geometry.js";
import { resolveLength } from "./model.js";
import { Path } from "./path.js";
import { svgPath } from "./svgpath.js";
/** The outline of `shape` in `r`. `unit` scales point lengths. */
export function shapePath(shape, r, unit) {
    const short = Math.min(r.width, r.height);
    const len = (l, fallback) => l ? resolveLength(l, short, unit, { top: 0, left: 0, bottom: 0, right: 0 }) : fallback * unit;
    switch (shape.kind) {
        case "rect": {
            if (shape.corners && shape.corners.length === 4)
                return roundedRect(r, shape.corners.map((c) => len(c, 0)));
            const rad = len(shape.cornerRadius, 0);
            return roundedRect(r, [rad, rad, rad, rad]);
        }
        case "squircle":
            return squircle(r, len(shape.cornerRadius, 0));
        case "ellipse":
            return new Path().addEllipse(r.x, r.y, r.width, r.height);
        case "capsule": {
            const rad = Math.min(r.width, r.height) / 2;
            return roundedRect(r, [rad, rad, rad, rad]);
        }
        case "polygon":
            return polygon(shape.sides ?? 6, shape.rotation ?? 0, len(shape.cornerRadius, 0), r);
        case "star":
            return star(shape.points ?? 5, shape.innerRatio ?? 0.5, shape.rotation ?? 0, r);
        case "arc":
            return arc(shape.startAngle ?? 0, shape.endAngle ?? 360, shape.inner ?? 0, r);
        case "line": {
            const a = shape.from ?? { x: 0, y: 0.5 }, b = shape.to ?? { x: 1, y: 0.5 };
            const pa = point(a, r), pb = point(b, r);
            return new Path().moveTo(pa.x, pa.y).lineTo(pb.x, pb.y);
        }
        case "cross":
            return cross(shape.armRatio ?? 0.34, len(shape.cornerRadius, 6), r);
        case "kidney":
            return kidney(shape.bulge ?? 0.5, r);
        case "trapezoid":
            return trapezoid(shape.taper ?? 0.14, r);
        case "path":
            return svgPath(shape.d ?? "", shape.box ?? [0, 0, 1, 1], r);
    }
}
/** True for outlines that are lines, not areas: they are stroked only, and inner/outer stroke alignment falls
    back to centre. */
export function isOpenShape(shape) {
    return shape.kind === "line";
}
function point(p, r) {
    return { x: r.x + p.x * r.width, y: r.y + p.y * r.height };
}
/** A rectangle with per-corner radii [topLeft, topRight, bottomRight, bottomLeft], each clamped to half the
    short side. Corners are circular arcs (arcTo in Canvas 2D). */
function roundedRect(r, radii) {
    const limit = Math.min(r.width, r.height) / 2;
    const rad = radii.map((v) => Math.max(0, Math.min(v, limit)));
    if (rad.every((v) => v === 0))
        return new Path().addRect(r.x, r.y, r.width, r.height);
    const [x0, y0, x1, y1] = [r.x, r.y, R.maxX(r), R.maxY(r)];
    return new Path()
        .moveTo(x0 + rad[0], y0)
        .arcTo(x1, y0, x1, y1, rad[1])
        .arcTo(x1, y1, x0, y1, rad[2])
        .arcTo(x0, y1, x0, y0, rad[3])
        .arcTo(x0, y0, x1, y0, rad[0])
        .close();
}
/** Continuous ("squircle") corners, the shared approximation both renderers use: each corner starts
    e = min(1.528665 × radius, short side / 2) from the corner along each edge and is one cubic whose control
    points sit 0.1 × e from the corner on each edge. */
function squircle(r, radius) {
    const e = Math.min(1.528665 * Math.max(0, radius), Math.min(r.width, r.height) / 2);
    if (e === 0)
        return new Path().addRect(r.x, r.y, r.width, r.height);
    const k = 0.1 * e;
    const [x0, y0, x1, y1] = [r.x, r.y, R.maxX(r), R.maxY(r)];
    return new Path()
        .moveTo(x0 + e, y0)
        .lineTo(x1 - e, y0)
        .curveTo(x1 - k, y0, x1, y0 + k, x1, y0 + e)
        .lineTo(x1, y1 - e)
        .curveTo(x1, y1 - k, x1 - k, y1, x1 - e, y1)
        .lineTo(x0 + e, y1)
        .curveTo(x0 + k, y1, x0, y1 - k, x0, y1 - e)
        .lineTo(x0, y0 + e)
        .curveTo(x0, y0 + k, x0 + k, y0, x0 + e, y0)
        .close();
}
const radians = (degrees) => (degrees * Math.PI) / 180;
/** A closed outline through `points`, with the corners at the indexes `rounded` accepts rounded by `radius`. */
function roundedPolygon(points, radius, rounded) {
    const p = new Path();
    const n = points.length;
    if (radius <= 0 || n < 3) {
        p.addLines(points);
        return p.close();
    }
    // Start halfway along the last edge so every corner is reached through arcTo.
    const last = points[n - 1], first = points[0];
    p.moveTo((last[0] + first[0]) / 2, (last[1] + first[1]) / 2);
    for (let i = 0; i < n; i++) {
        const corner = points[i], next = points[(i + 1) % n];
        if (rounded(i)) {
            const prev = points[(i + n - 1) % n];
            // Clamp so two arcs on one edge never overlap.
            const edge = Math.min(Math.hypot(corner[0] - prev[0], corner[1] - prev[1]), Math.hypot(next[0] - corner[0], next[1] - corner[1])) / 2;
            const a1 = Math.atan2(prev[1] - corner[1], prev[0] - corner[0]), a2 = Math.atan2(next[1] - corner[1], next[0] - corner[0]);
            let half = Math.abs(a1 - a2);
            if (half > Math.PI)
                half = 2 * Math.PI - half;
            half /= 2;
            const maxRadius = edge * Math.tan(half);
            p.arcTo(corner[0], corner[1], next[0], next[1], Math.min(radius, maxRadius));
        }
        else {
            p.lineTo(corner[0], corner[1]);
        }
    }
    return p.close();
}
/** A regular polygon inscribed in a circle of the frame's short side, centred. */
function polygon(sides, rotation, cornerRadius, r) {
    const n = Math.max(3, sides);
    const cx = R.midX(r), cy = R.midY(r), radius = Math.min(r.width, r.height) / 2;
    const points = [];
    for (let i = 0; i < n; i++) {
        const a = radians(rotation + (360 * i) / n);
        points.push([cx + radius * Math.cos(a), cy + radius * Math.sin(a)]);
    }
    return roundedPolygon(points, cornerRadius, () => true);
}
function star(count, innerRatio, rotation, r) {
    const n = Math.max(3, count);
    const cx = R.midX(r), cy = R.midY(r);
    const outer = Math.min(r.width, r.height) / 2, inner = outer * innerRatio;
    const vertices = [];
    for (let i = 0; i < 2 * n; i++) {
        const rad = i % 2 === 0 ? outer : inner;
        const a = radians(rotation + (180 * i) / n);
        vertices.push([cx + rad * Math.cos(a), cy + rad * Math.sin(a)]);
    }
    return new Path().addLines(vertices).close();
}
/** A pie slice (inner 0) or ring sector of the circle on the frame's short side, clockwise from `start` to `end`
    degrees. */
function arc(start, end, inner, r) {
    const cx = R.midX(r), cy = R.midY(r), outer = Math.min(r.width, r.height) / 2;
    let sweep = end - start;
    if (sweep > 360)
        sweep = 360;
    const a0 = radians(start), a1 = radians(start + sweep);
    const p = new Path();
    if (inner > 0) {
        const rad = outer * inner;
        p.arc(cx, cy, outer, a0, a1, sweep < 0);
        p.arc(cx, cy, rad, a1, a0, sweep >= 0);
    }
    else {
        if (Math.abs(sweep) < 360)
            p.moveTo(cx, cy);
        p.arc(cx, cy, outer, a0, a1, sweep < 0);
    }
    return p.close();
}
/** The d-pad body: a plus whose horizontal arm is armRatio × height tall and vertical arm armRatio × width wide,
    reaching the frame's edges. The eight outer corners are rounded; the four inner ones are sharp. */
function cross(armRatio, cornerRadius, r) {
    const aw = r.width * armRatio, ah = r.height * armRatio;
    const l = R.midX(r) - aw / 2, rr = R.midX(r) + aw / 2, t = R.midY(r) - ah / 2, b = R.midY(r) + ah / 2;
    const [x0, y0, x1, y1] = [r.x, r.y, R.maxX(r), R.maxY(r)];
    const pts = [
        [l, y0], [rr, y0], [rr, t], [x1, t], [x1, b], [rr, b], [rr, y1], [l, y1], [l, b], [x0, b], [x0, t], [l, t],
    ];
    const inner = new Set([2, 5, 8, 11]);
    return roundedPolygon(pts, cornerRadius, (i) => !inner.has(i));
}
/** The bean (Provenance's and iCube's kidney button), long axis horizontal. The top edge dips toward the middle
    by 0.3 × bulge of the height; the bottom edge is convex. */
function kidney(bulge, r) {
    const dip = 0.3 * bulge;
    const d = `M0 0.5 C0 0.05 0.3 0 0.5 ${dip} C0.7 0 1 0.05 1 0.5 C1 0.95 0.75 1 0.5 1 C0.25 1 0 0.95 0 0.5 Z`;
    return svgPath(d, [0, 0, 1, 1], r);
}
/** iCube's bar: the top edge is inset by taper × width on each side. */
function trapezoid(taper, r) {
    const inset = r.width * taper;
    return new Path()
        .addLines([[r.x + inset, r.y], [R.maxX(r) - inset, r.y], [R.maxX(r), R.maxY(r)], [r.x, R.maxY(r)]])
        .close();
}
