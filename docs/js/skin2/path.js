/* EmuSkins — skin format 2.0, a recorded path (docs/js/skin2/).

   A path as a list of commands that can be replayed onto any Canvas 2D context any number of times (fill, stroke,
   clip, offscreen layers), measured, and transformed. Stands in for CGPath in SkinKit's Skin2Shapes.swift. */
/** The circle approximation constant CGPath's ellipse uses (four cubics). */
export const KAPPA = 0.5522847498307936;
export class Path {
    commands = [];
    get isEmpty() { return this.commands.length === 0; }
    moveTo(x, y) { this.commands.push({ c: "M", x, y }); return this; }
    lineTo(x, y) { this.commands.push({ c: "L", x, y }); return this; }
    curveTo(x1, y1, x2, y2, x, y) {
        this.commands.push({ c: "C", x1, y1, x2, y2, x, y });
        return this;
    }
    quadTo(x1, y1, x, y) { this.commands.push({ c: "Q", x1, y1, x, y }); return this; }
    arcTo(x1, y1, x2, y2, r) { this.commands.push({ c: "T", x1, y1, x2, y2, r }); return this; }
    arc(cx, cy, r, a0, a1, ccw) {
        this.commands.push({ c: "A", cx, cy, r, a0, a1, ccw });
        return this;
    }
    close() { this.commands.push({ c: "Z" }); return this; }
    addLines(points) {
        points.forEach(([x, y], i) => (i === 0 ? this.moveTo(x, y) : this.lineTo(x, y)));
        return this;
    }
    addRect(x, y, w, h) {
        return this.moveTo(x, y).lineTo(x + w, y).lineTo(x + w, y + h).lineTo(x, y + h).close();
    }
    /** Four cubics, starting at the right-middle and running toward +y (clockwise on screen). */
    addEllipse(x, y, w, h) {
        const cx = x + w / 2, cy = y + h / 2, rx = w / 2, ry = h / 2, kx = rx * KAPPA, ky = ry * KAPPA;
        return this.moveTo(cx + rx, cy)
            .curveTo(cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry)
            .curveTo(cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy)
            .curveTo(cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry)
            .curveTo(cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy)
            .close();
    }
    addPath(other) {
        this.commands.push(...other.commands);
        return this;
    }
    /** Replays the commands onto a context (after beginPath) or a Path2D. */
    replay(sink) {
        for (const k of this.commands) {
            switch (k.c) {
                case "M":
                    sink.moveTo(k.x, k.y);
                    break;
                case "L":
                    sink.lineTo(k.x, k.y);
                    break;
                case "C":
                    sink.bezierCurveTo(k.x1, k.y1, k.x2, k.y2, k.x, k.y);
                    break;
                case "Q":
                    sink.quadraticCurveTo(k.x1, k.y1, k.x, k.y);
                    break;
                case "T":
                    sink.arcTo(k.x1, k.y1, k.x2, k.y2, k.r);
                    break;
                case "A":
                    sink.arc(k.cx, k.cy, k.r, k.a0, k.a1, k.ccw);
                    break;
                case "Z":
                    sink.closePath();
                    break;
            }
        }
    }
    /** A copy with every point mapped through x' = sx·x + tx, y' = sy·y + ty (axis-aligned stretch only). Arc
        commands are not supported (the SVG parser turns arcs into cubics). */
    stretched(sx, sy, tx, ty) {
        const out = new Path();
        const X = (x) => sx * x + tx, Y = (y) => sy * y + ty;
        for (const k of this.commands) {
            switch (k.c) {
                case "M":
                    out.moveTo(X(k.x), Y(k.y));
                    break;
                case "L":
                    out.lineTo(X(k.x), Y(k.y));
                    break;
                case "C":
                    out.curveTo(X(k.x1), Y(k.y1), X(k.x2), Y(k.y2), X(k.x), Y(k.y));
                    break;
                case "Q":
                    out.quadTo(X(k.x1), Y(k.y1), X(k.x), Y(k.y));
                    break;
                case "Z":
                    out.close();
                    break;
                default: throw new Error("stretched() does not support arc commands");
            }
        }
        return out;
    }
    /** A box around every point the path mentions (control points included, like CGPath.boundingBoxOfPath), or
        undefined for an empty path. Arcs contribute their full circle. */
    bounds() {
        let b;
        const add = (x, y) => {
            b = b ? { minX: Math.min(b.minX, x), minY: Math.min(b.minY, y), maxX: Math.max(b.maxX, x), maxY: Math.max(b.maxY, y) } : { minX: x, minY: y, maxX: x, maxY: y };
        };
        for (const k of this.commands) {
            switch (k.c) {
                case "M":
                case "L":
                    add(k.x, k.y);
                    break;
                case "C":
                    add(k.x1, k.y1);
                    add(k.x2, k.y2);
                    add(k.x, k.y);
                    break;
                case "Q":
                    add(k.x1, k.y1);
                    add(k.x, k.y);
                    break;
                case "T":
                    add(k.x1, k.y1);
                    add(k.x2, k.y2);
                    break;
                case "A":
                    add(k.cx - k.r, k.cy - k.r);
                    add(k.cx + k.r, k.cy + k.r);
                    break;
                case "Z": break;
            }
        }
        return b;
    }
}
