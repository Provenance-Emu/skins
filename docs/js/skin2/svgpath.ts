/* EmuSkins — skin format 2.0, SVG path data (docs/js/skin2/).

   Port of SkinKit's Skin2SVGPath.swift (`shapes.path`): M L H V C S Q T A Z, absolute and relative, implicit
   repeats, compact numbers (1.5.5, -1-2, 1e-3) and compact arc flags. The path is built in its own `box` and
   stretched, non-uniformly, onto the frame. Arcs become cubics (at most 90° each) so both renderers draw the
   same curve. Malformed data ends the path at the last complete command. */

import type { Path as PathT } from "./path.js";
import { Path } from "./path.js";

interface Pt { x: number; y: number }

/** The path stretched from `box` ([x, y, w, h]) onto `rect`. */
export function svgPath(d: string, box: number[], rect: { x: number; y: number; width: number; height: number }): PathT {
  const [bx, by, bw, bh] = box;
  const sx = bw > 0 ? rect.width / bw : 1;
  const sy = bh > 0 ? rect.height / bh : 1;
  // translate(rect.origin) · scale(sx, sy) · translate(-box.origin)
  return parseSVGPath(d).stretched(sx, sy, rect.x - bx * sx, rect.y - by * sy);
}

class Scanner {
  i = 0;
  readonly bytes: number[];
  constructor(d: string) { this.bytes = Array.from(new TextEncoder().encode(d)); }

  peek(): number | undefined { return this.i < this.bytes.length ? this.bytes[this.i] : undefined; }
  advance(): void { this.i += 1; }

  static isCommand(c: number): boolean { return "MmLlHhVvCcSsQqTtAaZz".includes(String.fromCharCode(c)); }
  static isSeparator(c: number): boolean { return c === 0x20 || c === 0x2c || c === 0x09 || c === 0x0a || c === 0x0d || c === 0x0c; }

  skipSeparators(): void {
    for (let c = this.peek(); c !== undefined && Scanner.isSeparator(c); c = this.peek()) this.i += 1;
  }

  /** One number: sign, digits, one decimal point, exponent. 1.5.5 reads as 1.5 then .5. */
  number(): number | undefined {
    this.skipSeparators();
    const start = this.i;
    let c = this.peek();
    if (c === 0x2b || c === 0x2d) this.i += 1;
    let digits = 0, dot = false;
    for (c = this.peek(); c !== undefined; c = this.peek()) {
      if (c >= 0x30 && c <= 0x39) { digits += 1; this.i += 1; } else if (c === 0x2e && !dot) { dot = true; this.i += 1; } else break;
    }
    if (digits === 0) { this.i = start; return undefined; }
    c = this.peek();
    if (c === 0x65 || c === 0x45) {
      const save = this.i;
      this.i += 1;
      const s = this.peek();
      if (s === 0x2b || s === 0x2d) this.i += 1;
      let expDigits = 0;
      for (let d = this.peek(); d !== undefined && d >= 0x30 && d <= 0x39; d = this.peek()) { expDigits += 1; this.i += 1; }
      if (expDigits === 0) this.i = save;
    }
    const v = Number(String.fromCharCode(...this.bytes.slice(start, this.i)));
    return Number.isFinite(v) ? v : undefined;
  }

  /** An arc flag: a single 0 or 1, which may run into the next number (a1 1 0 01 1 1). */
  flag(): boolean | undefined {
    this.skipSeparators();
    const c = this.peek();
    if (c !== 0x30 && c !== 0x31) return undefined;
    this.i += 1;
    return c === 0x31;
  }
}

/** The path in its own coordinates. */
export function parseSVGPath(d: string): PathT {
  const s = new Scanner(d);
  const p = new Path();
  let cur: Pt = { x: 0, y: 0 }, start: Pt = { x: 0, y: 0 };
  let lastControl: Pt | undefined;
  let lastCommand = 0;
  let command = 0;
  const code = (ch: string) => ch.charCodeAt(0);
  const ensureStarted = () => { if (p.isEmpty) p.moveTo(cur.x, cur.y); };
  const reflect = (q: Pt, about: Pt): Pt => ({ x: 2 * about.x - q.x, y: 2 * about.y - q.y });
  const isCubic = (c: number) => c === code("C") || c === code("S");
  const isQuad = (c: number) => c === code("Q") || c === code("T");

  for (;;) {
    s.skipSeparators();
    const c = s.peek();
    if (c === undefined) break;
    if (Scanner.isCommand(c)) {
      command = c;
      s.advance();
    } else if (command === 0 || command === code("Z") || command === code("z")) {
      break;
    }
    const rel = command >= code("a");
    const base: Pt = rel ? cur : { x: 0, y: 0 };
    const upper = rel ? command - 32 : command;
    const pt = (): Pt | undefined => {
      const x = s.number();
      if (x === undefined) return undefined;
      const y = s.number();
      if (y === undefined) return undefined;
      return { x: base.x + x, y: base.y + y };
    };
    let ok = true;
    switch (String.fromCharCode(upper)) {
      case "M": {
        const q = pt();
        if (!q) { ok = false; break; }
        p.moveTo(q.x, q.y); cur = q; start = q;
        // Further pairs after a moveto are linetos.
        command = rel ? code("l") : code("L");
        break;
      }
      case "L": {
        const q = pt();
        if (!q) { ok = false; break; }
        ensureStarted(); p.lineTo(q.x, q.y); cur = q;
        break;
      }
      case "H": {
        const x = s.number();
        if (x === undefined) { ok = false; break; }
        ensureStarted(); cur = { x: base.x + x, y: cur.y }; p.lineTo(cur.x, cur.y);
        break;
      }
      case "V": {
        const y = s.number();
        if (y === undefined) { ok = false; break; }
        ensureStarted(); cur = { x: cur.x, y: base.y + y }; p.lineTo(cur.x, cur.y);
        break;
      }
      case "C": {
        const c1 = pt(), c2 = c1 && pt(), q = c2 && pt();
        if (!c1 || !c2 || !q) { ok = false; break; }
        ensureStarted(); p.curveTo(c1.x, c1.y, c2.x, c2.y, q.x, q.y); lastControl = c2; cur = q;
        break;
      }
      case "S": {
        const c2 = pt(), q = c2 && pt();
        if (!c2 || !q) { ok = false; break; }
        const c1 = isCubic(lastCommand) ? reflect(lastControl ?? cur, cur) : cur;
        ensureStarted(); p.curveTo(c1.x, c1.y, c2.x, c2.y, q.x, q.y); lastControl = c2; cur = q;
        break;
      }
      case "Q": {
        const c1 = pt(), q = c1 && pt();
        if (!c1 || !q) { ok = false; break; }
        ensureStarted(); p.quadTo(c1.x, c1.y, q.x, q.y); lastControl = c1; cur = q;
        break;
      }
      case "T": {
        const q = pt();
        if (!q) { ok = false; break; }
        const c1 = isQuad(lastCommand) ? reflect(lastControl ?? cur, cur) : cur;
        ensureStarted(); p.quadTo(c1.x, c1.y, q.x, q.y); lastControl = c1; cur = q;
        break;
      }
      case "A": {
        const rx = s.number(), ry = rx !== undefined ? s.number() : undefined, rot = ry !== undefined ? s.number() : undefined;
        const large = rot !== undefined ? s.flag() : undefined, sweep = large !== undefined ? s.flag() : undefined;
        const q = sweep !== undefined ? pt() : undefined;
        if (rx === undefined || ry === undefined || rot === undefined || large === undefined || sweep === undefined || !q) { ok = false; break; }
        ensureStarted();
        addArc(p, cur, q, Math.abs(rx), Math.abs(ry), rot, large, sweep);
        cur = q;
        break;
      }
      case "Z":
        p.close(); cur = start;
        break;
      default:
        ok = false;
    }
    if (!ok) break;
    lastCommand = upper;
  }
  return p;
}

/** SVG's endpoint arc (implementation notes F.6) as cubic segments of at most 90°. */
function addArc(p: PathT, p0: Pt, p1: Pt, rx0: number, ry0: number, rotation: number, large: boolean, sweep: boolean): void {
  if (p0.x === p1.x && p0.y === p1.y) return;
  if (rx0 === 0 || ry0 === 0) { p.lineTo(p1.x, p1.y); return; }
  const phi = (rotation * Math.PI) / 180;
  const cosP = Math.cos(phi), sinP = Math.sin(phi);
  const dx = (p0.x - p1.x) / 2, dy = (p0.y - p1.y) / 2;
  const x1 = cosP * dx + sinP * dy, y1 = -sinP * dx + cosP * dy;
  let rx = rx0, ry = ry0;
  const lambda = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry);
  if (lambda > 1) { rx *= Math.sqrt(lambda); ry *= Math.sqrt(lambda); }
  const num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1;
  const den = rx * rx * y1 * y1 + ry * ry * x1 * x1;
  let coef = den === 0 ? 0 : Math.sqrt(Math.max(0, num / den));
  if (large === sweep) coef = -coef;
  const cx1 = (coef * rx * y1) / ry, cy1 = (-coef * ry * x1) / rx;
  const cx = cosP * cx1 - sinP * cy1 + (p0.x + p1.x) / 2;
  const cy = sinP * cx1 + cosP * cy1 + (p0.y + p1.y) / 2;
  const angle = (ux: number, uy: number, vx: number, vy: number) => Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
  const theta1 = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry);
  let delta = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry);
  if (!sweep && delta > 0) delta -= 2 * Math.PI;
  else if (sweep && delta < 0) delta += 2 * Math.PI;

  const segments = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 2) - 0.0001));
  const step = delta / segments;
  const k = (4 / 3) * Math.tan(step / 4);
  const onEllipse = (t: number): Pt => ({
    x: cx + rx * Math.cos(t) * cosP - ry * Math.sin(t) * sinP,
    y: cy + rx * Math.cos(t) * sinP + ry * Math.sin(t) * cosP,
  });
  const derivative = (t: number): Pt => ({
    x: -rx * Math.sin(t) * cosP - ry * Math.cos(t) * sinP,
    y: -rx * Math.sin(t) * sinP + ry * Math.cos(t) * cosP,
  });
  let t = theta1;
  for (let i = 0; i < segments; i++) {
    const t2 = t + step;
    const a = onEllipse(t), b = i === segments - 1 ? p1 : onEllipse(t2);
    const da = derivative(t), db = derivative(t2);
    p.curveTo(a.x + k * da.x, a.y + k * da.y, b.x - k * db.x, b.y - k * db.y, b.x, b.y);
    t = t2;
  }
}
