/* EmuSkins — skin format 2.0, a recorded path (docs/js/skin2/).

   A path as a list of commands that can be replayed onto any Canvas 2D context any number of times (fill, stroke,
   clip, offscreen layers), measured, and transformed. Stands in for CGPath in SkinKit's Skin2Shapes.swift. */

export type PathCommand =
  | { c: "M"; x: number; y: number }
  | { c: "L"; x: number; y: number }
  | { c: "C"; x1: number; y1: number; x2: number; y2: number; x: number; y: number }
  | { c: "Q"; x1: number; y1: number; x: number; y: number }
  /** Canvas arcTo / CGPath addArc(tangent1End:tangent2End:radius:) */
  | { c: "T"; x1: number; y1: number; x2: number; y2: number; r: number }
  /** Canvas arc(): angles in radians, increasing angle is clockwise on screen (y down) */
  | { c: "A"; cx: number; cy: number; r: number; a0: number; a1: number; ccw: boolean }
  | { c: "Z" };

/** The subset of CanvasRenderingContext2D / Path2D a Path replays onto. */
export interface PathSink {
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  bezierCurveTo(c1x: number, c1y: number, c2x: number, c2y: number, x: number, y: number): void;
  quadraticCurveTo(cx: number, cy: number, x: number, y: number): void;
  arcTo(x1: number, y1: number, x2: number, y2: number, r: number): void;
  arc(x: number, y: number, r: number, a0: number, a1: number, ccw?: boolean): void;
  closePath(): void;
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** The circle approximation constant CGPath's ellipse uses (four cubics). */
export const KAPPA = 0.5522847498307936;

export class Path {
  readonly commands: PathCommand[] = [];

  get isEmpty(): boolean { return this.commands.length === 0; }

  moveTo(x: number, y: number): this { this.commands.push({ c: "M", x, y }); return this; }
  lineTo(x: number, y: number): this { this.commands.push({ c: "L", x, y }); return this; }
  curveTo(x1: number, y1: number, x2: number, y2: number, x: number, y: number): this {
    this.commands.push({ c: "C", x1, y1, x2, y2, x, y });
    return this;
  }
  quadTo(x1: number, y1: number, x: number, y: number): this { this.commands.push({ c: "Q", x1, y1, x, y }); return this; }
  arcTo(x1: number, y1: number, x2: number, y2: number, r: number): this { this.commands.push({ c: "T", x1, y1, x2, y2, r }); return this; }
  arc(cx: number, cy: number, r: number, a0: number, a1: number, ccw: boolean): this {
    this.commands.push({ c: "A", cx, cy, r, a0, a1, ccw });
    return this;
  }
  close(): this { this.commands.push({ c: "Z" }); return this; }

  addLines(points: Array<[number, number]>): this {
    points.forEach(([x, y], i) => (i === 0 ? this.moveTo(x, y) : this.lineTo(x, y)));
    return this;
  }

  addRect(x: number, y: number, w: number, h: number): this {
    return this.moveTo(x, y).lineTo(x + w, y).lineTo(x + w, y + h).lineTo(x, y + h).close();
  }

  /** Four cubics, starting at the right-middle and running toward +y (clockwise on screen). */
  addEllipse(x: number, y: number, w: number, h: number): this {
    const cx = x + w / 2, cy = y + h / 2, rx = w / 2, ry = h / 2, kx = rx * KAPPA, ky = ry * KAPPA;
    return this.moveTo(cx + rx, cy)
      .curveTo(cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry)
      .curveTo(cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy)
      .curveTo(cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry)
      .curveTo(cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy)
      .close();
  }

  addPath(other: Path): this {
    this.commands.push(...other.commands);
    return this;
  }

  /** Replays the commands onto a context (after beginPath) or a Path2D. */
  replay(sink: PathSink): void {
    for (const k of this.commands) {
      switch (k.c) {
        case "M": sink.moveTo(k.x, k.y); break;
        case "L": sink.lineTo(k.x, k.y); break;
        case "C": sink.bezierCurveTo(k.x1, k.y1, k.x2, k.y2, k.x, k.y); break;
        case "Q": sink.quadraticCurveTo(k.x1, k.y1, k.x, k.y); break;
        case "T": sink.arcTo(k.x1, k.y1, k.x2, k.y2, k.r); break;
        case "A": sink.arc(k.cx, k.cy, k.r, k.a0, k.a1, k.ccw); break;
        case "Z": sink.closePath(); break;
      }
    }
  }

  /** A copy with every point mapped through x' = sx·x + tx, y' = sy·y + ty (axis-aligned stretch only). Arc
      commands are not supported (the SVG parser turns arcs into cubics). */
  stretched(sx: number, sy: number, tx: number, ty: number): Path {
    const out = new Path();
    const X = (x: number) => sx * x + tx, Y = (y: number) => sy * y + ty;
    for (const k of this.commands) {
      switch (k.c) {
        case "M": out.moveTo(X(k.x), Y(k.y)); break;
        case "L": out.lineTo(X(k.x), Y(k.y)); break;
        case "C": out.curveTo(X(k.x1), Y(k.y1), X(k.x2), Y(k.y2), X(k.x), Y(k.y)); break;
        case "Q": out.quadTo(X(k.x1), Y(k.y1), X(k.x), Y(k.y)); break;
        case "Z": out.close(); break;
        default: throw new Error("stretched() does not support arc commands");
      }
    }
    return out;
  }

  /** A box around every point the path mentions (control points included, like CGPath.boundingBoxOfPath), or
      undefined for an empty path. Arcs contribute their full circle. */
  bounds(): Bounds | undefined {
    let b: Bounds | undefined;
    const add = (x: number, y: number) => {
      b = b ? { minX: Math.min(b.minX, x), minY: Math.min(b.minY, y), maxX: Math.max(b.maxX, x), maxY: Math.max(b.maxY, y) } : { minX: x, minY: y, maxX: x, maxY: y };
    };
    for (const k of this.commands) {
      switch (k.c) {
        case "M": case "L": add(k.x, k.y); break;
        case "C": add(k.x1, k.y1); add(k.x2, k.y2); add(k.x, k.y); break;
        case "Q": add(k.x1, k.y1); add(k.x, k.y); break;
        case "T": add(k.x1, k.y1); add(k.x2, k.y2); break;
        case "A": add(k.cx - k.r, k.cy - k.r); add(k.cx + k.r, k.cy + k.r); break;
        case "Z": break;
      }
    }
    return b;
  }
}
