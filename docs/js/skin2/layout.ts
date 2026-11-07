/* EmuSkins — skin format 2.0, the layout resolver (docs/js/skin2/).

   Port of SkinKit's Skin2Resolver.swift and Skin2LayoutRecord.swift (section 4 of
   docs/specs/2026-11-03-skin-format-2-design.md): a pure function of the document, the environment and the
   player's edits. For each node, parents before children, in document order:

   1. apply the `when` patches that hold (in order), then evaluate `visible`; a hidden node takes no space;
   2. size it (4.2): frame → its size; inset → the parent minus the inset; a stack or grid group → the packed
      size of its children; otherwise each axis from `size`, a missing axis from `aspect` (a screen's own `aspect`
      counts), else the reference area's; then minSize/maxSize clamp;
   3. place it (4.3): frame → at its origin in the parent; inset → at the inset corner; otherwise at the `anchor`
      (default centre) of the reference area, moved by `offset` (+x right, +y down);
   4. apply the player's edit (offset, scale about the centre, opacity, hidden);
   5. record its #id (and the first screen as `screen`);
   6. lay out the children inside its frame (a stack or grid assigns their frames);
   7. expand `repeat` into copy transforms.

   The reference area is the parent, or the area `anchor.to` names; it stands in for the parent in % lengths and
   default sizes. Output frames are rounded to the half point; layout.json fixtures must match exactly. */

import type { Environment, Rect, Size, Transform } from "./geometry.js";
import { canvasRect, IDENTITY, rect, safeRect, transform } from "./geometry.js";
import type { Align, Condition, Document, HAnchor, Length, Node, VAnchor } from "./model.js";
import { applyPatch, resolveEdgeLengths, resolveLength, unitFor } from "./model.js";

/** A player's edit to one node (4.7): an offset in points at reference scale, a scale about the node's centre,
    an opacity and a hide switch. Stored per skin, per (device, orientation), per node id by the app. */
export interface Edit {
  offset?: { x: number; y: number };
  scale?: number;
  opacity?: number;
  hidden?: boolean;
}

/** One node after layout: the node with its `when` patches applied, where it is, and where it takes touches. */
export interface ResolvedNode {
  /** JSON Pointer of the node in the expanded document (/root/children/2). */
  pointer: string;
  /** The node with the `when` patches that held applied (and `when` emptied). */
  node: Node;
  /** The frame before half-point rounding. */
  exactFrame: Rect;
  /** The frame rounded to the half point; what renderers draw and the baker writes. */
  frame: Rect;
  /** Controls only: the frame outset by hit.extend, rounded. */
  hitFrame?: Rect;
  /** The node's own opacity (with the player's edit); the renderer multiplies down the tree. */
  opacity: number;
  /** `repeat`: one transform per copy in canvas points, copy 0 first (the identity). Empty without `repeat`. */
  copies: Transform[];
  /** Thumbsticks only: the knob's travel radius in canvas points. */
  travel?: number;
  children: ResolvedNode[];
}

/** A layout warning: a reference the resolver could not follow, so it used the parent instead. */
export interface LayoutWarning {
  pointer: string;
  message: string;
}

/** The resolved tree for one environment. */
export interface Resolution {
  root: ResolvedNode;
  unit: number;
  environment: Environment;
  theme?: string;
  variant?: string;
  warnings: LayoutWarning[];
}

/** This node and its descendants, parents first, in document order. */
export function resolvedPreorder(r: ResolvedNode): ResolvedNode[] {
  const out: ResolvedNode[] = [];
  const walk = (n: ResolvedNode) => { out.push(n); n.children.forEach(walk); };
  walk(r);
  return out;
}

export const resolutionNodes = (r: Resolution): ResolvedNode[] => resolvedPreorder(r.root);
export const resolutionControls = (r: Resolution): ResolvedNode[] => resolutionNodes(r).filter((n) => n.node.type === "control");
export const resolutionScreens = (r: Resolution): ResolvedNode[] => resolutionNodes(r).filter((n) => n.node.type === "screen");
export const resolutionNode = (r: Resolution, id: string): ResolvedNode | undefined => resolutionNodes(r).find((n) => n.node.id === id);

/** The condition test (4.6), shared by the resolver and the renderer's state patches. */
export function conditionMatches(c: Condition, env: Environment, theme?: string, variant?: string): boolean {
  if (c.orientation !== undefined && c.orientation !== env.orientation) return false;
  if (c.device !== undefined && c.device !== env.device) return false;
  if (c.displayType !== undefined && c.displayType !== env.displayType) return false;
  if (c.flag !== undefined && !env.flags.has(c.flag)) return false;
  if (c.minWidth !== undefined && env.size.width < c.minWidth) return false;
  if (c.minHeight !== undefined && env.size.height < c.minHeight) return false;
  if (c.theme !== undefined && c.theme !== theme) return false;
  if (c.variant !== undefined && c.variant !== variant) return false;
  return true;
}

export function nodeIsVisible(node: Node, env: Environment, theme?: string, variant?: string): boolean {
  const v = node.visible;
  if (v === undefined) return true;
  if (typeof v === "boolean") return v;
  return conditionMatches(v, env, theme, variant);
}

function alignAxis(a: HAnchor | VAnchor | Align, start: number, length: number, size: number): number {
  switch (a) {
    case "leading": case "top": return start;
    case "center": return start + (length - size) / 2;
    default: return start + length - size;
  }
}

interface Measured {
  node: Node;
  index: number;
  size: Size;
}

interface GridMetrics {
  size: Size;
  cell: Size;
  spacingX: number;
  spacingY: number;
  children: Measured[];
  cells: Array<{ row: number; column: number; rows: number; columns: number }>;
}

function withoutAnchorTarget(n: Node): Node {
  if (!n.layout?.anchor) return n;
  return { ...n, layout: { ...n.layout, anchor: { ...n.layout.anchor, to: undefined } } };
}

const childPointer = (p: string, i: number) => `${p}/children/${i}`;

export class Resolver {
  readonly unit: number;
  private areas = new Map<string, Rect>();
  private screenArea?: Rect;
  private warnings: LayoutWarning[] = [];

  constructor(
    readonly document: Document,
    readonly environment: Environment,
    readonly edits: Record<string, Edit> = {},
  ) {
    this.unit = unitFor(document.reference, environment.size);
  }

  static resolve(document: Document, environment: Environment, edits: Record<string, Edit> = {}): Resolution {
    const r = new Resolver(document, environment, edits);
    const canvas = canvasRect(environment);
    const root = r.resolveNode(document.root, "/root", canvas) ?? {
      pointer: "/root", node: document.root, exactFrame: canvas, frame: canvas, opacity: 1, copies: [], children: [],
    };
    return { root, unit: r.unit, environment, theme: document.theme, variant: document.variant, warnings: r.warnings };
  }

  matches(c: Condition): boolean {
    return conditionMatches(c, this.environment, this.document.theme, this.document.variant);
  }

  /** The node with its holding `when` patches applied. */
  effective(node: Node): Node {
    let n = node;
    for (const entry of node.when) if (this.matches(entry.condition)) n = applyPatch(entry.patch, n);
    return { ...n, when: [] };
  }

  isVisible(node: Node): boolean {
    return nodeIsVisible(node, this.environment, this.document.theme, this.document.variant);
  }

  // ── Areas ──────────────────────────────────────────────────────────────

  private warn(pointer: string, message: string): void {
    if (!this.warnings.some((w) => w.pointer === pointer && w.message === message)) this.warnings.push({ pointer, message });
  }

  private area(a: string, parent: Rect, pointer: string): Rect {
    switch (a) {
      case "parent": return parent;
      case "canvas": return canvasRect(this.environment);
      case "safeArea": return safeRect(this.environment);
      case "screen":
        if (this.screenArea) return this.screenArea;
        this.warn(pointer, "anchors to screen before any screen node is laid out; using the parent");
        return parent;
      default: {
        const id = a.slice(1);
        const r = this.areas.get(id);
        if (r) return r;
        this.warn(pointer, `anchors to #${id}, which is not laid out before this node; using the parent`);
        return parent;
      }
    }
  }

  /** The area a node's % lengths, default size and anchor refer to. */
  private referenceArea(n: Node, parent: Rect, pointer: string): Rect {
    const L = n.layout;
    if (!L || L.frame || L.inset || !L.anchor?.to) return parent;
    return this.area(L.anchor.to, parent, pointer);
  }

  private length(l: Length | undefined, along: number): number | undefined {
    return l === undefined ? undefined : resolveLength(l, along, this.unit, this.environment.safeArea);
  }

  // ── Size ───────────────────────────────────────────────────────────────

  private measure(n: Node, parent: Rect, pointer: string): Size {
    const L = n.layout;
    const ref = this.referenceArea(n, parent, pointer);
    let w: number, h: number;
    if (L?.frame) {
      w = this.length(L.frame[2], parent.width) ?? 0;
      h = this.length(L.frame[3], parent.height) ?? 0;
    } else if (L?.inset) {
      const i = resolveEdgeLengths(L.inset, parent.width, parent.height, this.unit, this.environment.safeArea);
      w = parent.width - i.left - i.right;
      h = parent.height - i.top - i.bottom;
    } else if (n.stack) {
      const s = this.stackMetrics(n, n.stack, ref, pointer).size;
      w = s.width; h = s.height;
    } else if (n.grid) {
      const s = this.gridMetrics(n, n.grid, ref, undefined, pointer).size;
      w = s.width; h = s.height;
    } else {
      let ow = this.length(L?.size?.width, ref.width);
      let oh = this.length(L?.size?.height, ref.height);
      const aspect = L?.aspect ?? (n.type === "screen" ? n.aspect : undefined);
      if (aspect !== undefined) {
        if (ow !== undefined && oh === undefined) oh = ow / aspect;
        else if (oh !== undefined && ow === undefined) ow = oh * aspect;
      }
      w = ow ?? ref.width;
      h = oh ?? ref.height;
    }
    let v: number | undefined;
    if ((v = this.length(L?.minSize?.width, ref.width)) !== undefined) w = Math.max(w, v);
    if ((v = this.length(L?.minSize?.height, ref.height)) !== undefined) h = Math.max(h, v);
    if ((v = this.length(L?.maxSize?.width, ref.width)) !== undefined) w = Math.min(w, v);
    if ((v = this.length(L?.maxSize?.height, ref.height)) !== undefined) h = Math.min(h, v);
    return { width: Math.max(0, w), height: Math.max(0, h) };
  }

  // ── Place ──────────────────────────────────────────────────────────────

  private place(n: Node, size: Size, parent: Rect, pointer: string): Rect {
    const L = n.layout;
    if (L?.frame) {
      return {
        x: parent.x + (this.length(L.frame[0], parent.width) ?? 0),
        y: parent.y + (this.length(L.frame[1], parent.height) ?? 0),
        width: size.width, height: size.height,
      };
    }
    if (L?.inset) {
      const i = resolveEdgeLengths(L.inset, parent.width, parent.height, this.unit, this.environment.safeArea);
      return { x: parent.x + i.left, y: parent.y + i.top, width: size.width, height: size.height };
    }
    const ref = this.referenceArea(n, parent, pointer);
    const x = alignAxis(L?.anchor?.x ?? "center", ref.x, ref.width, size.width);
    const y = alignAxis(L?.anchor?.y ?? "center", ref.y, ref.height, size.height);
    return {
      x: x + (this.length(L?.offset?.x, ref.width) ?? 0),
      y: y + (this.length(L?.offset?.y, ref.height) ?? 0),
      width: size.width, height: size.height,
    };
  }

  // ── Resolve ────────────────────────────────────────────────────────────

  resolveNode(raw: Node, pointer: string, parent: Rect): ResolvedNode | undefined {
    const n = this.effective(raw);
    if (!this.isVisible(n)) return undefined;
    const size = this.measure(n, parent, pointer);
    const frame = this.place(n, size, parent, pointer);
    const ref = this.referenceArea(n, parent, pointer);
    return this.finish(n, pointer, frame, ref, parent);
  }

  /** Steps 4–7 for a node whose frame is known. `measureArea` is the area the node was measured against (its
      stack or grid content is measured against it again); `parent` is the parent's frame. */
  private finish(n: Node, pointer: string, placed: Rect, measureArea: Rect, parent: Rect): ResolvedNode | undefined {
    let frame = { ...placed };
    let opacity = n.opacity ?? 1;
    const edit = n.id !== undefined ? this.edits[n.id] : undefined;
    if (edit) {
      if (edit.hidden === true) return undefined;
      if (edit.offset) { frame.x += edit.offset.x * this.unit; frame.y += edit.offset.y * this.unit; }
      if (edit.scale !== undefined && edit.scale > 0) {
        const s = edit.scale;
        frame = { x: rect.midX(frame) - (frame.width * s) / 2, y: rect.midY(frame) - (frame.height * s) / 2, width: frame.width * s, height: frame.height * s };
      }
      if (edit.opacity !== undefined) opacity *= edit.opacity;
    }
    if (n.id !== undefined) this.areas.set(n.id, frame);
    if (n.type === "screen" && !this.screenArea) this.screenArea = frame;

    let hitFrame: Rect | undefined;
    let travel: number | undefined;
    if (n.type === "control") {
      const e = n.hit?.extend
        ? resolveEdgeLengths(n.hit.extend, frame.width, frame.height, this.unit, this.environment.safeArea)
        : { top: 0, left: 0, bottom: 0, right: 0 };
      hitFrame = rect.roundedToHalfPoint(rect.outset(frame, e));
      if (n.kind === "thumbstick") {
        const short = Math.min(frame.width, frame.height);
        travel = this.length(n.travel, short) ?? 0.35 * short;
      }
    }

    let children: ResolvedNode[] = [];
    if (n.stack) {
      children = this.layoutStack(n, n.stack, frame, measureArea, pointer);
    } else if (n.grid) {
      children = this.layoutGrid(n, n.grid, frame, measureArea, pointer);
    } else {
      n.children.forEach((child, i) => {
        const r = this.resolveNode(child, childPointer(pointer, i), frame);
        if (r) children.push(r);
      });
    }

    const copies: Transform[] = [];
    if (n.repeat) {
      const rep = n.repeat;
      const pivot = rep.pivot === "parent" ? { x: rect.midX(parent), y: rect.midY(parent) } : { x: rect.midX(frame), y: rect.midY(frame) };
      const ox = this.length(rep.offset?.x, parent.width) ?? 0;
      const oy = this.length(rep.offset?.y, parent.height) ?? 0;
      for (let i = 0; i < rep.count; i++) {
        const t = transform.then(
          transform.then(
            transform.then(transform.translation(-pivot.x, -pivot.y), transform.scale(Math.pow(rep.scale ?? 1, i))),
            transform.rotation((rep.rotate ?? 0) * i),
          ),
          transform.translation(pivot.x + ox * i, pivot.y + oy * i),
        );
        copies.push(i === 0 ? IDENTITY : t);
      }
    }

    return { pointer, node: n, exactFrame: frame, frame: rect.roundedToHalfPoint(frame), hitFrame, opacity, copies, travel, children };
  }

  // ── Stacks (4.4) ───────────────────────────────────────────────────────

  /** Visible children with their `when` applied and their sizes measured against `area`. */
  private measuredChildren(n: Node, area: Rect, pointer: string): Measured[] {
    const out: Measured[] = [];
    n.children.forEach((child, i) => {
      const c = this.effective(child);
      if (!this.isVisible(c)) return;
      // A stacked or gridded child is placed by its group: its own `anchor.to` does not apply.
      out.push({ node: c, index: i, size: this.measure(withoutAnchorTarget(c), area, childPointer(pointer, i)) });
    });
    return out;
  }

  private stackMetrics(n: Node, stack: NonNullable<Node["stack"]>, area: Rect, pointer: string) {
    const vertical = stack.axis === "vertical";
    const spacing = this.length(stack.spacing, vertical ? area.height : area.width) ?? 0;
    const children = this.measuredChildren(n, area, pointer);
    let main = 0, cross = 0;
    for (const c of children) {
      main += vertical ? c.size.height : c.size.width;
      cross = Math.max(cross, vertical ? c.size.width : c.size.height);
    }
    main += spacing * Math.max(0, children.length - 1);
    return { size: vertical ? { width: cross, height: main } : { width: main, height: cross }, children, spacing };
  }

  private layoutStack(n: Node, stack: NonNullable<Node["stack"]>, frame: Rect, area: Rect, pointer: string): ResolvedNode[] {
    const m = this.stackMetrics(n, stack, area, pointer);
    const vertical = stack.axis === "vertical";
    const total = m.children.reduce((s, c) => s + (vertical ? c.size.height : c.size.width), 0);
    let gap = m.spacing;
    if (stack.distribute === "spaceBetween" && m.children.length > 1) {
      gap = Math.max(m.spacing, ((vertical ? frame.height : frame.width) - total) / (m.children.length - 1));
    }
    let cursor = vertical ? frame.y : frame.x;
    const out: ResolvedNode[] = [];
    for (const c of m.children) {
      const L = c.node.layout;
      let x: number, y: number;
      if (vertical) {
        y = cursor;
        x = alignAxis(L?.anchor?.x ?? stack.align, frame.x, frame.width, c.size.width);
        cursor += c.size.height + gap;
      } else {
        x = cursor;
        y = alignAxis(L?.anchor?.y ?? stack.align, frame.y, frame.height, c.size.height);
        cursor += c.size.width + gap;
      }
      x += this.length(L?.offset?.x, area.width) ?? 0;
      y += this.length(L?.offset?.y, area.height) ?? 0;
      const r = this.finish(c.node, childPointer(pointer, c.index), { x, y, width: c.size.width, height: c.size.height }, area, frame);
      if (r) out.push(r);
    }
    return out;
  }

  // ── Grids (4.4) ────────────────────────────────────────────────────────

  /** Row-major placement with spans; cells are equal. With `fixed` (a group sized by frame or inset) the cells
      divide it; otherwise a cell is as large as the largest child needs. */
  private gridMetrics(n: Node, grid: NonNullable<Node["grid"]>, area: Rect, fixed: Size | undefined, pointer: string): GridMetrics {
    const columns = grid.columns;
    const sx = this.length(grid.spacingX, area.width) ?? 0;
    const sy = this.length(grid.spacingY, area.height) ?? 0;
    const children = this.measuredChildren(n, area, pointer);
    const occupied = new Set<string>();
    const cells: GridMetrics["cells"] = [];
    let rowCount = 0;
    for (const c of children) {
      const spanC = Math.min(Math.max(c.node.layout?.span?.columns ?? 1, 1), columns);
      const spanR = Math.max(c.node.layout?.span?.rows ?? 1, 1);
      let row = 0, col = 0;
      search: for (;;) {
        for (let cc = 0; cc <= columns - spanC; cc++) {
          let free = true;
          for (let dr = 0; dr < spanR && free; dr++) for (let dc = 0; dc < spanC && free; dc++) if (occupied.has(`${row + dr},${cc + dc}`)) free = false;
          if (free) { col = cc; break search; }
        }
        row += 1;
      }
      for (let dr = 0; dr < spanR; dr++) for (let dc = 0; dc < spanC; dc++) occupied.add(`${row + dr},${col + dc}`);
      cells.push({ row, column: col, rows: spanR, columns: spanC });
      rowCount = Math.max(rowCount, row + spanR);
    }
    let cell: Size;
    if (fixed) {
      cell = {
        width: (fixed.width - sx * (columns - 1)) / columns,
        height: rowCount > 0 ? (fixed.height - sy * (rowCount - 1)) / rowCount : 0,
      };
    } else {
      cell = { width: 0, height: 0 };
      children.forEach((c, i) => {
        const slot = cells[i];
        cell.width = Math.max(cell.width, (c.size.width - sx * (slot.columns - 1)) / slot.columns);
        cell.height = Math.max(cell.height, (c.size.height - sy * (slot.rows - 1)) / slot.rows);
      });
    }
    const size = {
      width: columns * cell.width + sx * (columns - 1),
      height: rowCount > 0 ? rowCount * cell.height + sy * (rowCount - 1) : 0,
    };
    return { size: fixed ?? size, cell, spacingX: sx, spacingY: sy, children, cells };
  }

  private layoutGrid(n: Node, grid: NonNullable<Node["grid"]>, frame: Rect, area: Rect, pointer: string): ResolvedNode[] {
    const L = n.layout;
    const fixed = L?.frame || L?.inset ? { width: frame.width, height: frame.height } : undefined;
    const m = this.gridMetrics(n, grid, area, fixed, pointer);
    const out: ResolvedNode[] = [];
    m.children.forEach((c, i) => {
      const slot = m.cells[i];
      const span: Rect = {
        x: frame.x + slot.column * (m.cell.width + m.spacingX),
        y: frame.y + slot.row * (m.cell.height + m.spacingY),
        width: slot.columns * m.cell.width + (slot.columns - 1) * m.spacingX,
        height: slot.rows * m.cell.height + (slot.rows - 1) * m.spacingY,
      };
      const p = childPointer(pointer, c.index);
      const size = this.measure(withoutAnchorTarget(c.node), span, p);
      const anchor = c.node.layout?.anchor;
      let x = alignAxis(anchor?.x ?? grid.align, span.x, span.width, size.width);
      let y = alignAxis(anchor?.y ?? "center", span.y, span.height, size.height);
      x += this.length(c.node.layout?.offset?.x, span.width) ?? 0;
      y += this.length(c.node.layout?.offset?.y, span.height) ?? 0;
      const r = this.finish(c.node, p, { x, y, width: size.width, height: size.height }, span, frame);
      if (r) out.push(r);
    });
    return out;
  }
}

export function resolve(document: Document, environment: Environment, edits: Record<string, Edit> = {}): Resolution {
  return Resolver.resolve(document, environment, edits);
}

// ── layout.json (9.2) ────────────────────────────────────────────────────

export interface LayoutRecordNode {
  path: string;
  id?: string;
  type: string;
  kind?: string;
  frame: number[];
  hitFrame?: number[];
  copies?: number[][];
}

export interface LayoutRecord {
  trait?: string;
  canvas: { width: number; height: number; safeArea: { top: number; left: number; bottom: number; right: number } };
  device: string;
  displayType: string;
  orientation: string;
  theme?: string;
  variant?: string;
  nodes: LayoutRecordNode[];
}

/** `expected/<trait>.layout.json`: every visible node's resolved frame and hit frame for one environment. The
    Swift resolver records it; this resolver must reproduce it exactly. Frames are rounded to the half point,
    copy transforms to 4 decimals (matrix) and the half point (translation). Optional keys are left out. */
export function layoutRecord(r: Resolution, trait?: string): LayoutRecord {
  const e = r.environment;
  const rec: LayoutRecord = {
    canvas: {
      width: e.size.width, height: e.size.height,
      safeArea: { top: e.safeArea.top, left: e.safeArea.left, bottom: e.safeArea.bottom, right: e.safeArea.right },
    },
    device: e.device,
    displayType: e.displayType,
    orientation: e.orientation,
    nodes: resolutionNodes(r).map((n) => {
      const out: LayoutRecordNode = { path: n.pointer, type: n.node.type, frame: rect.array(n.frame) };
      if (n.node.id !== undefined) out.id = n.node.id;
      if (n.node.kind !== undefined) out.kind = n.node.kind;
      if (n.hitFrame) out.hitFrame = rect.array(n.hitFrame);
      if (n.copies.length > 0) out.copies = n.copies.map(transform.roundedArray);
      return out;
    }),
  };
  if (trait !== undefined) rec.trait = trait;
  if (r.theme !== undefined) rec.theme = r.theme;
  if (r.variant !== undefined) rec.variant = r.variant;
  return rec;
}
