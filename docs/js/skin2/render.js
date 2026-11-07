/* EmuSkins — skin format 2.0, the Canvas 2D drawer (docs/js/skin2/).

   Port of SkinKit's Skin2Renderer.swift (sections 5 and 6.4 of docs/specs/2026-11-03-skin-format-2-design.md).
   Order per node: its copies (`repeat`), then, for each copy, the control state (scale about the frame's centre,
   opacity, patches on descendants), shadows (listed order, each under the content), the content (fills,
   material, strokes; text; image; children), blur, then blend and opacity when it is composited onto its parent.
   Shadows, inner shadows and blur rasterise the node to an offscreen bitmap at the context's pixel scale and
   use a Gaussian with σ = radius / 2 (raster.ts), so the kernel is the same as the Core Graphics drawer's.
   Group opacity and blend render the node into a layer that is composited once.

   The context's user space is canvas points, top-left origin, y down. `renderToSurface` makes such a context
   over a bitmap for the reference images and for previews. Text needs fonts (the host loads opentype.js and
   passes parsed fonts in `RenderOptions.fonts`); images need decoded bitmaps in `RenderOptions.images`. */
import { IDENTITY, rect as R } from "./geometry.js";
import { nodeIsVisible } from "./layout.js";
import { resolutionControls } from "./layout.js";
import { applyPatch, patchTargetID, preorder, resolveLength } from "./model.js";
import { Path } from "./path.js";
import { Bitmap, browserSurfaceFactory, configure, contextOf, pixelScale } from "./raster.js";
import { isOpenShape, shapePath } from "./shapes.js";
import { defaultFont, textPath } from "./text.js";
export const DIRECTIONS = ["up", "down", "left", "right"];
export function stickValue(x, y) {
    const m = Math.sqrt(x * x + y * y);
    return m > 1 ? { x: x / m, y: y / m } : { x, y };
}
export function controlState(o = {}) {
    return {
        pressed: o.pressed ?? false,
        selected: o.selected ?? false,
        directions: o.directions ?? new Set(),
        stick: o.stick ? stickValue(o.stick.x, o.stick.y) : { x: 0, y: 0 },
        scaleProgress: o.scaleProgress ?? 1,
        easingOut: o.easingOut ?? false,
    };
}
/** Pressed, or a d-pad with a direction held. */
export const isPressed = (s) => s.pressed || s.directions.size > 0;
/** The `states` entries that apply, in the order they apply: selected, pressed, then pressed.up, .down, .left,
    .right. Later patches win; scales and opacities multiply. */
export function stateNames(s) {
    const out = [];
    if (s.selected)
        out.push("selected");
    if (isPressed(s))
        out.push("pressed");
    for (const d of DIRECTIONS)
        if (s.directions.has(d))
            out.push(`pressed.${d}`);
    return out;
}
/** The shape of a states.json entry: {pressed?, selected?, directions?, stick?: [x, y]}. */
export function controlStateFromJSON(raw) {
    const directions = new Set();
    for (const d of raw.directions ?? []) {
        if (!DIRECTIONS.includes(d))
            throw new Error(`unknown direction ${d}`);
        directions.add(d);
    }
    return controlState({
        pressed: raw.pressed ?? false,
        selected: raw.selected ?? false,
        directions,
        stick: raw.stick && raw.stick.length === 2 ? { x: raw.stick[0], y: raw.stick[1] } : undefined,
    });
}
/** Every file a document references: image `src`s (nodes and paints, including those set by `when`, states and
    variants-in-progress) and font families (as `fonts/<family>`). The host loads them into RenderOptions. */
export function collectAssetPaths(doc) {
    const images = new Set(), fonts = new Set();
    const paints = (list) => { for (const p of list ?? [])
        if (p.src !== undefined)
            images.add(p.src); };
    const patch = (p) => paints(p.fills);
    preorder(doc.root, (n) => {
        if (n.src !== undefined)
            images.add(n.src);
        paints(n.fills);
        if (n.font?.family !== undefined)
            fonts.add(n.font.family);
        for (const w of n.when)
            patch(w.patch);
        for (const s of Object.values(n.states))
            for (const p of s.patch)
                patch(p);
    });
    return { images: [...images].sort(), fonts: [...fonts].sort() };
}
// ── Entry points ─────────────────────────────────────────────────────────
/** Draws `resolution` into `ctx`, whose user space is canvas points with a top-left origin and y down. */
export function drawResolution(resolution, ctx, options = {}) {
    const painter = new Painter(resolution, options);
    ctx.save();
    configure(ctx);
    painter.draw(resolution.root, ctx, undefined);
    if (options.showHitFrames) {
        ctx.strokeStyle = css({ red: 1, green: 0.2, blue: 0.2, alpha: 1 });
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        for (const c of resolutionControls(resolution)) {
            if (c.hitFrame)
                ctx.strokeRect(c.hitFrame.x + 0.5, c.hitFrame.y + 0.5, c.hitFrame.width - 1, c.hitFrame.height - 1);
        }
    }
    ctx.restore();
}
/** The canvas as a surface at `scale` pixels per point (RGBA, transparent background). */
export function renderToSurface(resolution, scale = 2, options = {}) {
    const size = resolution.environment.size;
    const w = Math.round(size.width * scale), h = Math.round(size.height * scale);
    const factory = options.surface ?? browserSurfaceFactory();
    const surface = factory(w, h);
    const ctx = contextOf(surface);
    ctx.scale(scale, scale);
    drawResolution(resolution, ctx, { ...options, surface: factory });
    return surface;
}
/** The weight of the next sample at fractional position t between two samples. Core Graphics' high-quality
    interpolation is sharper than bilinear's t: measured against the paint fixture it follows
    t² / (t² + (1 - t)²) (a clamped bilinear on the same sample positions, pixel centres at 0.5). */
function imageWeight(t) {
    const a = t * t, b = (1 - t) * (1 - t);
    return a / (a + b);
}
const NO_INSETS = { top: 0, left: 0, bottom: 0, right: 0 };
function css(c, opacity = 1) {
    return `rgba(${Math.round(c.red * 255)},${Math.round(c.green * 255)},${Math.round(c.blue * 255)},${c.alpha * opacity})`;
}
function rgbBytes(c) {
    return [Math.round(c.red * 255), Math.round(c.green * 255), Math.round(c.blue * 255)];
}
const COMPOSITE = {
    normal: "source-over",
    multiply: "multiply",
    screen: "screen",
    overlay: "overlay",
    softLight: "soft-light",
    // Canvas has no plus-lighter everywhere; `lighter` is the same additive blend.
    plus: "lighter",
};
function outsetRect(r, d) {
    return { x: r.x - d, y: r.y - d, width: r.width + 2 * d, height: r.height + 2 * d };
}
function unionRect(a, b) {
    if (!a)
        return b;
    const x0 = Math.min(a.x, b.x), y0 = Math.min(a.y, b.y), x1 = Math.max(R.maxX(a), R.maxX(b)), y1 = Math.max(R.maxY(a), R.maxY(b));
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}
function applyingTransform(r, t) {
    const pts = [[r.x, r.y], [R.maxX(r), r.y], [r.x, R.maxY(r)], [R.maxX(r), R.maxY(r)]].map(([x, y]) => [t.a * x + t.c * y + t.tx, t.b * x + t.d * y + t.ty]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys);
    return { x: x0, y: y0, width: Math.max(...xs) - x0, height: Math.max(...ys) - y0 };
}
class Painter {
    resolution;
    options;
    unit;
    factory;
    noiseTile;
    constructor(resolution, options) {
        this.resolution = resolution;
        this.options = options;
        this.unit = resolution.unit;
        this.factory = options.surface ?? browserSurfaceFactory();
    }
    len(l, along) {
        return l ? resolveLength(l, along, this.unit, NO_INSETS) : undefined;
    }
    // ── Tree ───────────────────────────────────────────────────────────────
    draw(r, ctx, control) {
        if (r.node.role === "highlight" && !(control && isPressed(control.state)))
            return;
        const transforms = r.copies.length === 0 ? [IDENTITY] : r.copies;
        transforms.forEach((t, i) => {
            let n = r.node;
            const list = n.id !== undefined ? control?.patches.get(n.id) : undefined;
            if (list)
                for (const { copy, patch } of list)
                    if (copy === undefined || copy === i)
                        n = applyPatch(patch, n);
            const env = this.resolution.environment;
            if (!nodeIsVisible(n, env, this.resolution.theme, this.resolution.variant))
                return;
            ctx.save();
            ctx.transform(t.a, t.b, t.c, t.d, t.tx, t.ty);
            this.drawSingle(r, n, ctx, control);
            ctx.restore();
        });
    }
    drawSingle(r, n, ctx, outer) {
        const frame = r.frame;
        let control = outer;
        // The resolved opacity carries the player's edit; a patched opacity replaces the node's own part.
        const own = r.node.opacity ?? 1;
        const editFactor = own > 0 ? r.opacity / own : 1;
        let opacity = (n.opacity ?? 1) * editFactor;
        if (n.type === "control") {
            const state = (n.id !== undefined ? this.options.states?.[n.id] : undefined) ?? controlState();
            const patches = new Map();
            let scale = 1;
            for (const name of stateNames(state)) {
                const s = n.states[name];
                if (!s)
                    continue;
                if (s.scale !== undefined)
                    scale *= s.scale;
                if (s.opacity !== undefined)
                    opacity *= s.opacity;
                for (const p of s.patch) {
                    const target = patchTargetID(p);
                    if (!target)
                        continue;
                    const list = patches.get(target.id) ?? [];
                    list.push({ copy: target.copy, patch: p });
                    patches.set(target.id, list);
                }
            }
            if (state.easingOut && !isPressed(state)) {
                const v = n.states["pressed"]?.scale;
                if (v !== undefined)
                    scale *= v;
            }
            scale = 1 + (scale - 1) * Math.min(Math.max(state.scaleProgress, 0), 1);
            if (scale !== 1) {
                ctx.translate(R.midX(frame), R.midY(frame));
                ctx.scale(scale, scale);
                ctx.translate(-R.midX(frame), -R.midY(frame));
            }
            const travel = r.travel ?? 0;
            control = { state, patches, knob: { w: state.stick.x * travel, h: state.stick.y * travel } };
        }
        if (n.role === "knob" && control && (control.knob.w !== 0 || control.knob.h !== 0)) {
            ctx.translate(control.knob.w, control.knob.h);
        }
        const shadows = n.effects.filter((e) => e.type === "shadow" && !e.inner);
        const innerShadows = n.effects.filter((e) => e.type === "shadow" && e.inner);
        const blurs = n.effects.filter((e) => e.type === "blur");
        const blendEffect = [...n.effects].reverse().find((e) => e.type === "blend");
        const blend = blendEffect?.mode ?? "normal";
        if (shadows.length === 0 && innerShadows.length === 0 && blurs.length === 0) {
            const layered = opacity < 1 || blend !== "normal";
            if (!layered) {
                this.drawContent(r, n, ctx, control);
                return;
            }
            const pad = this.effectPadding(n.effects);
            const region = outsetRect(this.visualBounds(r, n), pad);
            this.layer(ctx, region, opacity, blend, (c) => this.drawContent(r, n, c, control));
            return;
        }
        // Rasterised path: shadows, inner shadows and blur.
        const pad = this.effectPadding(n.effects);
        const region = outsetRect(this.visualBounds(r, n), pad);
        const content = Bitmap.make(this.factory, region, pixelScale(ctx));
        if (!content)
            return;
        this.drawContent(r, n, content.context, control);
        // A shape's shadow is cast by the union of its fills (5.3); anything else by its whole content.
        let silhouette = content;
        if (n.type === "shape" && n.fills.length > 0 && n.shape) {
            const fillsOnly = Bitmap.make(this.factory, region, pixelScale(ctx));
            if (fillsOnly) {
                this.fillShape(shapePath(n.shape, frame, this.unit), n.fills, undefined, frame, fillsOnly.context);
                silhouette = fillsOnly;
            }
        }
        const alpha = silhouette.alpha();
        const sigmas = blurs.map((e) => this.len(e.radius, Math.min(frame.width, frame.height)) ?? 0);
        const sigma = sigmas.length > 0 ? Math.max(...sigmas) : 0;
        this.layer(ctx, content.region, opacity, blend, (c) => {
            for (const s of shadows)
                this.drawShadow(s, alpha, c);
            if (sigma > 0)
                content.blur(sigma / 2);
            const cr = content.region;
            c.drawImage(content.surface, cr.x, cr.y, cr.width, cr.height);
            for (const s of innerShadows)
                this.drawInnerShadow(s, alpha, c);
        });
    }
    /** Renders `body` into a layer covering `local` (in the current user space) and composites it once with
        `alpha` and `blend`: Core Graphics' transparency layer. */
    layer(ctx, local, alpha, blend, body) {
        const m = ctx.getTransform();
        const pts = [[local.x, local.y], [R.maxX(local), local.y], [local.x, R.maxY(local)], [R.maxX(local), R.maxY(local)]]
            .map(([x, y]) => [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f]);
        const cw = ctx.canvas.width, ch = ctx.canvas.height;
        const x0 = Math.max(0, Math.floor(Math.min(...pts.map((p) => p[0])))), y0 = Math.max(0, Math.floor(Math.min(...pts.map((p) => p[1]))));
        const x1 = Math.min(cw, Math.ceil(Math.max(...pts.map((p) => p[0])))), y1 = Math.min(ch, Math.ceil(Math.max(...pts.map((p) => p[1]))));
        if (!(x1 > x0 && y1 > y0))
            return;
        const surface = this.factory(x1 - x0, y1 - y0);
        const c = contextOf(surface);
        configure(c);
        c.setTransform(m.a, m.b, m.c, m.d, m.e - x0, m.f - y0);
        body(c);
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.globalAlpha = alpha;
        ctx.globalCompositeOperation = COMPOSITE[blend];
        ctx.drawImage(surface, x0, y0);
        ctx.restore();
    }
    drawContent(r, n, ctx, control) {
        const frame = r.frame;
        switch (n.type) {
            case "shape":
                if (n.shape)
                    this.drawShape(n.shape, n, frame, ctx);
                break;
            case "text":
                this.drawText(n, frame, ctx);
                break;
            case "image": {
                const image = n.src !== undefined ? this.options.images?.get(n.src) : undefined;
                if (image) {
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(frame.x, frame.y, frame.width, frame.height);
                    ctx.clip();
                    this.drawImage(image, n.mode ?? "fit", 1, n.tint, frame, ctx);
                    ctx.restore();
                }
                break;
            }
            case "screen":
                if (this.options.screenPlaceholders)
                    this.drawScreen(frame, ctx);
                break;
            default:
                break;
        }
        for (const child of r.children)
            this.draw(child, ctx, control);
    }
    // ── Shapes, paint, strokes (5.1, 5.2, 5.4) ─────────────────────────────
    drawShape(shape, n, frame, ctx) {
        const path = shapePath(shape, frame, this.unit);
        const open = isOpenShape(shape);
        if (!open)
            this.fillShape(path, n.fills, n.material, frame, ctx);
        for (const stroke of n.strokes)
            this.drawStroke(stroke, path, open, frame, ctx);
    }
    fillShape(path, fills, material, frame, ctx) {
        for (const paint of fills)
            this.fill(path, paint, frame, ctx);
        if (material)
            this.drawMaterial(material, path, frame, ctx);
    }
    pathTo(ctx, path) {
        ctx.beginPath();
        path.replay(ctx);
    }
    gradientStops(g, paint, opacity) {
        const sorted = paint.stops.map((s, i) => ({ s, i })).sort((a, b) => a.s.at - b.s.at || a.i - b.i).map((x) => x.s);
        for (const s of sorted)
            g.addColorStop(s.at, css(s.color, (s.opacity ?? 1) * opacity));
    }
    fill(path, paint, frame, ctx) {
        const opacity = paint.opacity ?? 1;
        const at = (p, fallback) => p ? { x: frame.x + p.x * frame.width, y: frame.y + p.y * frame.height } : fallback;
        ctx.save();
        switch (paint.type) {
            case "solid":
                ctx.fillStyle = css(paint.color ?? { red: 0, green: 0, blue: 0, alpha: 1 }, opacity);
                this.pathTo(ctx, path);
                ctx.fill();
                break;
            case "linear": {
                const a = at(paint.start, { x: R.midX(frame), y: frame.y }), b = at(paint.end, { x: R.midX(frame), y: R.maxY(frame) });
                const g = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
                this.gradientStops(g, paint, opacity);
                ctx.fillStyle = g;
                this.pathTo(ctx, path);
                ctx.fill();
                break;
            }
            case "radial": {
                const c = at(paint.center, { x: R.midX(frame), y: R.midY(frame) });
                const radius = (paint.radius ?? 0.5) * Math.max(frame.width, frame.height);
                const g = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, radius);
                this.gradientStops(g, paint, opacity);
                ctx.fillStyle = g;
                this.pathTo(ctx, path);
                ctx.fill();
                break;
            }
            case "angular": {
                const c = at(paint.center, { x: R.midX(frame), y: R.midY(frame) });
                const make = ctx.createConicGradient;
                if (!make)
                    break;
                // 0° along +x; the angle grows toward +y, which is clockwise on the y-down canvas.
                const g = make.call(ctx, ((paint.startAngle ?? 0) * Math.PI) / 180, c.x, c.y);
                this.gradientStops(g, paint, opacity);
                ctx.fillStyle = g;
                this.pathTo(ctx, path);
                ctx.fill();
                break;
            }
            case "image": {
                const image = paint.src !== undefined ? this.options.images?.get(paint.src) : undefined;
                if (!image)
                    break;
                this.pathTo(ctx, path);
                ctx.clip();
                ctx.globalAlpha = opacity;
                this.drawImage(image, paint.mode ?? "tile", paint.scale ?? 1, undefined, frame, ctx);
                break;
            }
        }
        ctx.restore();
    }
    drawStroke(s, path, open, frame, ctx) {
        const short = Math.min(frame.width, frame.height);
        const width = this.len(s.width, short) ?? 0;
        if (!(width > 0))
            return;
        ctx.save();
        const align = open ? "center" : s.align;
        switch (align) {
            case "center":
                ctx.lineWidth = width;
                break;
            case "inner":
                this.pathTo(ctx, path);
                ctx.clip();
                ctx.lineWidth = width * 2;
                break;
            case "outer": {
                const b = path.bounds();
                const outside = new Path();
                if (b)
                    outside.addRect(b.minX - width * 2 - 1, b.minY - width * 2 - 1, b.maxX - b.minX + 2 * (width * 2 + 1), b.maxY - b.minY + 2 * (width * 2 + 1));
                outside.addPath(path);
                this.pathTo(ctx, outside);
                ctx.clip("evenodd");
                ctx.lineWidth = width * 2;
                break;
            }
        }
        const dash = s.dash.map((d) => this.len(d, short) ?? 0);
        if (dash.length > 0 && dash.some((d) => d > 0))
            ctx.setLineDash(dash);
        ctx.lineCap = s.cap;
        ctx.lineJoin = s.join;
        ctx.strokeStyle = css(s.color, s.opacity ?? 1);
        this.pathTo(ctx, path);
        ctx.stroke();
        ctx.restore();
    }
    /** Materials as recipes of the primitives (5.4). `params` are not read yet. */
    drawMaterial(m, path, frame, ctx) {
        const i = m.intensity;
        if (!(i > 0))
            return;
        ctx.save();
        this.pathTo(ctx, path);
        ctx.clip();
        const white = { red: 1, green: 1, blue: 1, alpha: 1 }, black = { red: 0, green: 0, blue: 0, alpha: 1 };
        const gradient = (g, list) => {
            for (const [c, a, at] of list)
                g.addColorStop(at, css(c, a));
            return g;
        };
        // Core Graphics draws a gradient with no extend options only between its start and end; the rect restricts
        // the fill to that span.
        const span = (x, y, w, h, g) => {
            ctx.fillStyle = g;
            ctx.fillRect(x, y, w, h);
        };
        switch (m.name) {
            case "gloss": {
                // A top-half white-to-clear sheen plus a dark band along the bottom edge (the inner shadow).
                const cx = R.midX(frame);
                span(frame.x, frame.y, frame.width, frame.height / 2, gradient(ctx.createLinearGradient(cx, frame.y, cx, R.midY(frame)), [[white, 0.45 * i, 0], [white, 0, 1]]));
                const bandTop = R.maxY(frame) - frame.height * 0.2;
                span(frame.x, bandTop, frame.width, R.maxY(frame) - bandTop, gradient(ctx.createLinearGradient(cx, bandTop, cx, R.maxY(frame)), [[black, 0, 0], [black, 0.3 * i, 1]]));
                break;
            }
            case "brushedMetal": {
                const make = ctx.createConicGradient;
                if (make) {
                    const g = gradient(make.call(ctx, 0, R.midX(frame), R.midY(frame)), [
                        [white, 0.35 * i, 0], [black, 0.25 * i, 0.25], [white, 0.35 * i, 0.5], [black, 0.25 * i, 0.75], [white, 0.35 * i, 1],
                    ]);
                    ctx.fillStyle = g;
                    ctx.fillRect(frame.x, frame.y, frame.width, frame.height);
                }
                this.drawNoise(0.15 * i, frame, ctx);
                break;
            }
            case "plasticGrain":
                this.drawNoise(0.08 * i, frame, ctx);
                break;
            case "crt": {
                ctx.fillStyle = css(black, 0.35 * i);
                const pitch = 3 * this.unit, line = this.unit;
                for (let y = frame.y; y < R.maxY(frame); y += pitch)
                    ctx.fillRect(frame.x, y, frame.width, line);
                const c = { x: R.midX(frame), y: R.midY(frame) };
                const g = gradient(ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, 0.75 * Math.max(frame.width, frame.height)), [[black, 0, 0.5], [black, 0.5 * i, 1]]);
                ctx.fillStyle = g;
                ctx.fillRect(frame.x - 1, frame.y - 1, frame.width + 2, frame.height + 2);
                break;
            }
        }
        ctx.restore();
    }
    /** A tiled 64 × 64 grey noise image drawn at 32 × 32 points (deterministic: xorshift32 from a fixed seed). */
    drawNoise(alpha, frame, ctx) {
        const tile = this.noise();
        ctx.save();
        ctx.globalAlpha = alpha;
        const side = 32;
        for (let y = Math.floor(frame.y / side) * side; y < R.maxY(frame); y += side) {
            for (let x = Math.floor(frame.x / side) * side; x < R.maxX(frame); x += side) {
                ctx.drawImage(tile, x, y, side, side);
            }
        }
        ctx.restore();
    }
    noise() {
        if (this.noiseTile)
            return this.noiseTile;
        const surface = this.factory(64, 64);
        const c = contextOf(surface);
        const img = c.createImageData(64, 64);
        let state = 0x9e3779b9;
        for (let i = 0; i < 64 * 64; i++) {
            state ^= state << 13;
            state ^= state >>> 17;
            state ^= state << 5;
            state >>>= 0;
            const v = state >>> 24;
            img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
            img.data[i * 4 + 3] = 255;
        }
        c.putImageData(img, 0, 0);
        this.noiseTile = surface;
        return surface;
    }
    // ── Effects (5.3) ──────────────────────────────────────────────────────
    effectPadding(effects) {
        let pad = 2;
        for (const e of effects) {
            if (e.type !== "shadow" && e.type !== "blur")
                continue;
            const r = this.len(e.radius, 0) ?? 0;
            const spread = this.len(e.spread, 0) ?? 0;
            const offset = e.offset.length === 2 ? Math.max(Math.abs(this.len(e.offset[0], 0) ?? 0), Math.abs(this.len(e.offset[1], 0) ?? 0)) : 0;
            pad = Math.max(pad, 1.5 * r + Math.abs(spread) + offset + 2);
        }
        return pad;
    }
    shadowGeometry(s) {
        const r = this.len(s.radius, 0) ?? 0;
        const spread = this.len(s.spread, 0) ?? 0;
        const offset = s.offset.length === 2 ? { w: this.len(s.offset[0], 0) ?? 0, h: this.len(s.offset[1], 0) ?? 0 } : { w: 0, h: 0 };
        return { sigma: r / 2, spread, offset };
    }
    /** One drop shadow: the silhouette, spread, blurred (σ = radius / 2), moved by the offset and filled with the
        shadow colour. */
    drawShadow(s, silhouette, ctx) {
        const g = this.shadowGeometry(s);
        const m = silhouette.clone();
        m.spread(g.spread);
        m.blur(g.sigma);
        const color = s.color ?? { red: 0, green: 0, blue: 0, alpha: 1 };
        const image = m.tinted(this.factory, rgbBytes(color), color.alpha * (s.opacity ?? 1));
        ctx.save();
        ctx.translate(g.offset.w, g.offset.h);
        ctx.drawImage(image, m.region.x, m.region.y, m.region.width, m.region.height);
        ctx.restore();
    }
    /** An inner shadow: the inverted silhouette, spread inward, blurred and moved, drawn over the content and
        clipped to the silhouette. */
    drawInnerShadow(s, silhouette, ctx) {
        const g = this.shadowGeometry(s);
        const m = silhouette.clone();
        m.invert();
        m.spread(g.spread);
        m.blur(g.sigma);
        const color = s.color ?? { red: 0, green: 0, blue: 0, alpha: 1 };
        const shadow = m.tinted(this.factory, rgbBytes(color), color.alpha * (s.opacity ?? 1));
        const clip = silhouette.tinted(this.factory, [0, 0, 0], 1);
        const cw = ctx.canvas.width, ch = ctx.canvas.height;
        const scratch = this.factory(cw, ch);
        const c = contextOf(scratch);
        configure(c);
        const t = ctx.getTransform();
        c.setTransform(t.a, t.b, t.c, t.d, t.e, t.f);
        c.save();
        c.translate(g.offset.w, g.offset.h);
        c.drawImage(shadow, m.region.x, m.region.y, m.region.width, m.region.height);
        c.restore();
        c.globalCompositeOperation = "destination-in";
        const sr = silhouette.region;
        c.drawImage(clip, sr.x, sr.y, sr.width, sr.height);
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(scratch, 0, 0);
        ctx.restore();
    }
    /** Where a node can draw, in its parent's space: its frame, its strokes, its text, and its children's bounds
        (through their copies and a thumbstick's travel). Effects add their own padding on top. */
    visualBounds(r, n) {
        let b = r.frame;
        const short = Math.min(b.width, b.height);
        const stroke = Math.max(0, ...n.strokes.map((s) => this.len(s.width, short) ?? 0));
        b = outsetRect(b, stroke + 1);
        if (n.type === "text" && n.text) {
            const tb = this.textPathFor(n.text, n, r.frame)?.bounds();
            if (tb)
                b = unionRect(b, outsetRect({ x: tb.minX, y: tb.minY, width: tb.maxX - tb.minX, height: tb.maxY - tb.minY }, 1));
        }
        const travel = r.travel ?? 0;
        for (const child of r.children) {
            const pad = this.effectPadding(child.node.effects);
            let cb = outsetRect(this.visualBounds(child, child.node), pad);
            if (child.node.role === "knob")
                cb = outsetRect(cb, travel);
            if (child.copies.length > 0) {
                let u;
                for (const t of child.copies)
                    u = unionRect(u, applyingTransform(cb, t));
                cb = u;
            }
            b = unionRect(b, cb);
        }
        return b;
    }
    // ── Text ───────────────────────────────────────────────────────────────
    fontFor(n) {
        const fonts = this.options.fonts;
        if (!fonts)
            return undefined;
        const family = n.font?.family;
        const face = family !== undefined ? fonts.families?.get(family) : undefined;
        return face ?? defaultFont(fonts, n.font?.weight ?? "regular");
    }
    textPathFor(text, n, frame) {
        const font = this.fontFor(n);
        if (!font)
            return undefined;
        const size = n.font ? this.len(n.font.size, frame.height) ?? 12 * this.unit : 12 * this.unit;
        return textPath(text, font, size, n.align ?? "center", n.fit ?? false, frame);
    }
    drawText(n, frame, ctx) {
        if (!n.text)
            return;
        const path = this.textPathFor(n.text, n, frame);
        if (!path)
            return;
        this.pathTo(ctx, path);
        ctx.fillStyle = css(n.color ?? { red: 1, green: 1, blue: 1, alpha: 1 });
        ctx.fill();
    }
    // ── Images and screens ─────────────────────────────────────────────────
    /** fit/fill keep the aspect ratio and centre; stretch fills the frame; tile repeats the image at its pixel
        size × `scale` in points from the frame's top-left. A tint draws the image as a template. */
    drawImage(image, mode, scale, tint, frame, ctx) {
        const iw = image.width, ih = image.height;
        if (!(iw > 0 && ih > 0))
            return;
        const rects = [];
        switch (mode) {
            case "stretch":
                rects.push(frame);
                break;
            case "fit":
            case "fill": {
                const s = mode === "fit" ? Math.min(frame.width / iw, frame.height / ih) : Math.max(frame.width / iw, frame.height / ih);
                const w = iw * s, h = ih * s;
                rects.push({ x: R.midX(frame) - w / 2, y: R.midY(frame) - h / 2, width: w, height: h });
                break;
            }
            case "tile": {
                const tw = iw * scale, th = ih * scale;
                for (let y = frame.y; y < R.maxY(frame) && rects.length < 4096; y += th) {
                    for (let x = frame.x; x < R.maxX(frame) && rects.length < 4096; x += tw)
                        rects.push({ x, y, width: tw, height: th });
                }
                break;
            }
        }
        for (const rect of rects) {
            if (tint)
                this.drawTinted(image, rect, tint, ctx);
            else
                this.paintImage(ctx, image, rect);
        }
    }
    sourcePixels = new WeakMap();
    /** Straight RGBA bytes of an image, read once. */
    pixelsOfImage(image) {
        let px = this.sourcePixels.get(image);
        if (!px) {
            const s = this.factory(image.width, image.height);
            const c = contextOf(s);
            c.drawImage(image, 0, 0);
            px = c.getImageData(0, 0, image.width, image.height).data;
            this.sourcePixels.set(image, px);
        }
        return px;
    }
    /** Draws `image` into `rect`. Where the transform only scales and translates, the image is resampled here:
        destination pixels at the rect's fractional edges get partial coverage (Core Graphics antialiases them;
        canvases snap drawImage's destination to whole pixels), and samples are weighted by imageWeight. Only for
        upscaling: a downscale goes through drawImage, whose filter averages the source pixels it covers. */
    paintImage(ctx, image, rect) {
        const m = ctx.getTransform();
        const source = image;
        const dx0 = m.a * rect.x + m.e, dx1 = m.a * R.maxX(rect) + m.e;
        const dy0 = m.d * rect.y + m.f, dy1 = m.d * R.maxY(rect) + m.f;
        const px0 = Math.floor(dx0), px1 = Math.ceil(dx1), py0 = Math.floor(dy0), py1 = Math.ceil(dy1);
        const w = px1 - px0, h = py1 - py0;
        const upscaling = dx1 - dx0 >= image.width && dy1 - dy0 >= image.height;
        if (m.b !== 0 || m.c !== 0 || !(m.a > 0 && m.d > 0) || !(w > 0 && h > 0) || w * h > 4096 * 4096 || !upscaling) {
            ctx.drawImage(source, rect.x, rect.y, rect.width, rect.height);
            return;
        }
        const iw = image.width, ih = image.height;
        const src = this.pixelsOfImage(image);
        const tile = this.factory(w, h);
        const tileCtx = contextOf(tile);
        const out = tileCtx.createImageData(w, h);
        const fetch = (x, y, o, acc) => {
            const cx = Math.min(iw - 1, Math.max(0, x)), cy = Math.min(ih - 1, Math.max(0, y));
            const i = (cy * iw + cx) * 4, a = src[i + 3] / 255;
            acc[0] += src[i] * a * o;
            acc[1] += src[i + 1] * a * o;
            acc[2] += src[i + 2] * a * o;
            acc[3] += a * o;
        };
        const acc = [0, 0, 0, 0];
        for (let y = 0; y < h; y++) {
            const covY = Math.min(py0 + y + 1, dy1) - Math.max(py0 + y, dy0);
            if (covY <= 0)
                continue;
            const v = ((py0 + y + 0.5 - dy0) / (dy1 - dy0)) * ih - 0.5;
            const y0 = Math.floor(v), wy = imageWeight(v - y0);
            for (let x = 0; x < w; x++) {
                const covX = Math.min(px0 + x + 1, dx1) - Math.max(px0 + x, dx0);
                if (covX <= 0)
                    continue;
                const u = ((px0 + x + 0.5 - dx0) / (dx1 - dx0)) * iw - 0.5;
                const x0 = Math.floor(u), wx = imageWeight(u - x0);
                acc[0] = acc[1] = acc[2] = acc[3] = 0;
                fetch(x0, y0, (1 - wx) * (1 - wy), acc);
                fetch(x0 + 1, y0, wx * (1 - wy), acc);
                fetch(x0, y0 + 1, (1 - wx) * wy, acc);
                fetch(x0 + 1, y0 + 1, wx * wy, acc);
                const a = acc[3];
                if (a <= 0)
                    continue;
                const o = (y * w + x) * 4;
                out.data[o] = Math.round(acc[0] / a);
                out.data[o + 1] = Math.round(acc[1] / a);
                out.data[o + 2] = Math.round(acc[2] / a);
                out.data[o + 3] = Math.round(a * covX * covY * 255);
            }
        }
        tileCtx.putImageData(out, 0, 0);
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.imageSmoothingEnabled = false;
        ctx.drawImage(tile, px0, py0);
        ctx.restore();
    }
    drawTinted(image, rect, tint, ctx) {
        const s = pixelScale(ctx);
        const w = Math.max(1, Math.ceil(rect.width * s)), h = Math.max(1, Math.ceil(rect.height * s));
        const surface = this.factory(w, h);
        const c = contextOf(surface);
        configure(c);
        c.drawImage(image, 0, 0, w, h);
        c.globalCompositeOperation = "source-in";
        c.fillStyle = css(tint);
        c.fillRect(0, 0, w, h);
        ctx.drawImage(surface, rect.x, rect.y, rect.width, rect.height);
    }
    drawScreen(frame, ctx) {
        ctx.save();
        ctx.fillStyle = "rgb(16,16,24)";
        ctx.fillRect(frame.x, frame.y, frame.width, frame.height);
        ctx.strokeStyle = "rgb(64,64,80)";
        ctx.lineWidth = 1;
        ctx.strokeRect(frame.x + 0.5, frame.y + 0.5, frame.width - 1, frame.height - 1);
        ctx.restore();
    }
}
