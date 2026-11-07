/* EmuSkins — skin format 2.0, the typed model and its decoder (docs/js/skin2/).

   Port of SkinKit's Skin2Length / Skin2Layout / Skin2Paint / Skin2Node / Skin2Document (SkinKit2Core), sections
   2, 3, 4.6 and 5 of docs/specs/2026-11-03-skin-format-2-design.md. `decodeDocument` takes the expanded JSON the
   preprocessor (preprocess.ts) produces and returns the typed tree, failing with a Skin2Error that names a JSON
   Pointer, like the Swift decoder does. Unknown keys are ignored; wrong types fail.

   Pure ES module: no DOM, no network. */
import { insetValue, traitFamilyKnown, TRAIT_FAMILY_NAMES } from "./geometry.js";
import { isObject, pointerAppend, Skin2Error, typeName } from "./json.js";
export const MAX_LENGTH_DEPTH = 4;
export const PERCENT_PATTERN = /^-?[0-9]+(\.[0-9]+)?%$/;
const EDGES = ["top", "left", "bottom", "right"];
export class LengthError extends Error {
}
export function lengthDepth(l) {
    switch (l.op) {
        case "pt":
        case "frac":
        case "safe": return 0;
        default: return 1 + Math.max(0, ...l.items.map(lengthDepth));
    }
}
export function lengthUsesSafeArea(l) {
    if (!l)
        return false;
    switch (l.op) {
        case "safe": return true;
        case "pt":
        case "frac": return false;
        default: return l.items.some(lengthUsesSafeArea);
    }
}
/** Resolves to canvas points. `along` is the size % refers to; `unit` scales points. */
export function resolveLength(l, along, unit, safeArea) {
    switch (l.op) {
        case "pt": return l.value * unit;
        case "frac": return l.value * along;
        case "safe": return insetValue(safeArea, l.edge);
        case "max": return Math.max(...l.items.map((i) => resolveLength(i, along, unit, safeArea)));
        case "min": return Math.min(...l.items.map((i) => resolveLength(i, along, unit, safeArea)));
        case "sum": return l.items.reduce((s, i) => s + resolveLength(i, along, unit, safeArea), 0);
    }
}
/** Parses the JSON forms. Errors name what was wrong; the caller adds the location. */
export function parseLength(json) {
    let out;
    if (typeof json === "number") {
        out = { op: "pt", value: json };
    }
    else if (typeof json === "string") {
        if (!PERCENT_PATTERN.test(json)) {
            throw new LengthError(`"${json}" is not a length: use a number of points, "N%", or {"pt": N}`);
        }
        out = { op: "frac", value: Number(json.slice(0, -1)) / 100 };
    }
    else if (isObject(json)) {
        const keys = Object.keys(json);
        if (keys.length !== 1)
            throw new LengthError("a length object has exactly one key: pt, frac, max, min, sum or safe");
        const key = keys[0], value = json[key];
        switch (key) {
            case "pt":
                if (typeof value !== "number")
                    throw new LengthError('"pt" takes a number');
                out = { op: "pt", value };
                break;
            case "frac":
                if (typeof value !== "number")
                    throw new LengthError('"frac" takes a number');
                out = { op: "frac", value };
                break;
            case "safe":
                if (typeof value !== "string" || !EDGES.includes(value))
                    throw new LengthError('"safe" takes top, left, bottom or right');
                out = { op: "safe", edge: value };
                break;
            case "max":
            case "min":
            case "sum":
                if (!Array.isArray(value) || value.length < 2)
                    throw new LengthError(`"${key}" takes an array of at least two lengths`);
                out = { op: key, items: value.map(parseLength) };
                break;
            default:
                throw new LengthError(`unknown length operator "${key}": the only ones are pt, frac, max, min, sum, safe`);
        }
    }
    else {
        throw new LengthError(`expected a length (number, "N%" or a length object), found ${typeName(json)}`);
    }
    if (lengthDepth(out) > MAX_LENGTH_DEPTH)
        throw new LengthError(`length expressions nest at most ${MAX_LENGTH_DEPTH} operators deep`);
    return out;
}
export function edgeLengthsAll(e) {
    return e ? [e.top, e.left, e.bottom, e.right].filter((l) => l !== undefined) : [];
}
/** Top and bottom resolve against `height`, left and right against `width`. */
export function resolveEdgeLengths(e, width, height, unit, safeArea) {
    return {
        top: e.top ? resolveLength(e.top, height, unit, safeArea) : 0,
        left: e.left ? resolveLength(e.left, width, unit, safeArea) : 0,
        bottom: e.bottom ? resolveLength(e.bottom, height, unit, safeArea) : 0,
        right: e.right ? resolveLength(e.right, width, unit, safeArea) : 0,
    };
}
export const COLOR_PATTERN = /^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$/;
/** #RRGGBB or #RRGGBBAA, sRGB; null when the string is neither. */
export function parseColor(hex) {
    if (!COLOR_PATTERN.test(hex))
        return null;
    const v = parseInt(hex.slice(1), 16);
    if (hex.length === 9) {
        return { red: ((v >>> 24) & 0xff) / 255, green: ((v >>> 16) & 0xff) / 255, blue: ((v >>> 8) & 0xff) / 255, alpha: (v & 0xff) / 255 };
    }
    return { red: ((v >>> 16) & 0xff) / 255, green: ((v >>> 8) & 0xff) / 255, blue: (v & 0xff) / 255, alpha: 1 };
}
export const MAX_PATH_BYTES = 4096;
export const ID_BODY = "[A-Za-z_][A-Za-z0-9_.-]*";
export const ID_PATTERN = new RegExp(`^${ID_BODY}$`);
/** Applies a patch (a `when` entry, a state or a variant). size, minSize, maxSize, anchor and offset merge
    field by field, so {"size": {"width": 96}} keeps the height; every other field is replaced whole. null
    clears a field at either level. */
export function mergeLayout(base, p) {
    function pick(b, patch, key, merge) {
        if (patch !== undefined)
            return b !== undefined && merge ? merge(b, patch) : patch;
        return p.cleared.has(key) ? undefined : b;
    }
    const mergeSize = (b, q) => ({
        width: q.width ?? (q.cleared.has("width") ? undefined : b.width),
        height: q.height ?? (q.cleared.has("height") ? undefined : b.height),
        cleared: new Set(),
    });
    const mergeOffset = (b, q) => ({
        x: q.x ?? (q.cleared.has("x") ? undefined : b.x),
        y: q.y ?? (q.cleared.has("y") ? undefined : b.y),
        cleared: new Set(),
    });
    const mergeAnchor = (b, q) => ({
        x: q.x ?? (q.cleared.has("x") ? undefined : b.x),
        y: q.y ?? (q.cleared.has("y") ? undefined : b.y),
        to: q.to ?? (q.cleared.has("to") ? undefined : b.to),
        cleared: new Set(),
    });
    return {
        frame: pick(base.frame, p.frame, "frame"),
        inset: pick(base.inset, p.inset, "inset"),
        size: pick(base.size, p.size, "size", mergeSize),
        aspect: pick(base.aspect, p.aspect, "aspect"),
        minSize: pick(base.minSize, p.minSize, "minSize", mergeSize),
        maxSize: pick(base.maxSize, p.maxSize, "maxSize", mergeSize),
        anchor: pick(base.anchor, p.anchor, "anchor", mergeAnchor),
        offset: pick(base.offset, p.offset, "offset", mergeOffset),
        span: pick(base.span, p.span, "span"),
        cleared: new Set(),
    };
}
export const PATCH_TARGET_PATTERN = /^#[A-Za-z_][A-Za-z0-9_.-]*(\[[0-9]+\])?$/;
/** The target's node id and copy index. */
export function patchTargetID(p) {
    if (!p.target || !p.target.startsWith("#"))
        return undefined;
    const body = p.target.slice(1);
    const open = body.indexOf("[");
    if (open >= 0 && body.endsWith("]"))
        return { id: body.slice(0, open), copy: Number(body.slice(open + 1, -1)) };
    return { id: body };
}
/** The node with this patch applied (a copy; the input is not changed). */
export function applyPatch(p, node) {
    const n = { ...node };
    if (p.layout)
        n.layout = mergeLayout(n.layout ?? emptyLayout(), p.layout);
    else if (p.cleared.has("layout"))
        n.layout = undefined;
    if (p.visible !== undefined)
        n.visible = p.visible;
    else if (p.cleared.has("visible"))
        n.visible = undefined;
    if (p.opacity !== undefined)
        n.opacity = p.opacity;
    else if (p.cleared.has("opacity"))
        n.opacity = undefined;
    if (p.fills)
        n.fills = p.fills;
    if (p.strokes)
        n.strokes = p.strokes;
    if (p.text !== undefined)
        n.text = p.text;
    return n;
}
export function emptyLayout() {
    return { cleared: new Set() };
}
export const MAX_REPEAT = 64;
export const STATE_NAMES = new Set(["pressed", "selected", "pressed.up", "pressed.down", "pressed.left", "pressed.right"]);
/** Every input name the control sends: `input` (one name or the d-pad's four) plus `inputs`. */
export function inputNames(n) {
    const i = n.input;
    const fromInput = i === undefined ? [] : typeof i === "string" ? [i] : [i.up, i.down, i.left, i.right];
    return [...fromInput, ...(n.inputs ?? [])];
}
/** This node and its descendants, depth first, parents before children. */
export function preorder(n, body) {
    body(n);
    for (const c of n.children)
        preorder(c, body);
}
export function nodeCount(n) {
    return 1 + n.children.reduce((s, c) => s + nodeCount(c), 0);
}
/** unit = clamp(min(w, h) / shortSide, minScale, maxScale) */
export function unitFor(ref, size) {
    return Math.min(Math.max(Math.min(size.width, size.height) / ref.shortSide, ref.minScale), ref.maxScale);
}
export const FORMAT_VERSION_PATTERN = /^2\.[0-9]+$/;
/** skin.json size limit (section 11). */
export const MAX_FILE_BYTES = 512 * 1024;
/** Node limit after part expansion (section 11). */
export const MAX_NODES = 2000;
export function findNode(doc, id) {
    let found;
    preorder(doc.root, (n) => { if (!found && n.id === id)
        found = n; });
    return found;
}
// ── Decoder ──────────────────────────────────────────────────────────────
function fail(p, message) {
    throw new Skin2Error(p, message);
}
function wrapLength(json, p) {
    try {
        return parseLength(json);
    }
    catch (e) {
        if (e instanceof LengthError)
            fail(p, e.message);
        throw e;
    }
}
function obj(v, p) {
    if (!isObject(v))
        fail(p, `expected an object, found ${typeName(v)}`);
    return v;
}
/** The value at `k`, or undefined when absent or null. */
function get(o, k) {
    const v = o[k];
    return v === null ? undefined : v;
}
function optStr(o, k, p) {
    const v = get(o, k);
    if (v === undefined)
        return undefined;
    if (typeof v !== "string")
        fail(pointerAppend(p, k), `expected a string, found ${typeName(v)}`);
    return v;
}
function reqStr(o, k, p) {
    const v = optStr(o, k, p);
    if (v === undefined)
        fail(p, `missing required key "${k}"`);
    return v;
}
function optNum(o, k, p) {
    const v = get(o, k);
    if (v === undefined)
        return undefined;
    if (typeof v !== "number")
        fail(pointerAppend(p, k), `expected a number, found ${typeName(v)}`);
    return v;
}
function reqNum(o, k, p) {
    const v = optNum(o, k, p);
    if (v === undefined)
        fail(p, `missing required key "${k}"`);
    return v;
}
function optInt(o, k, p) {
    const v = optNum(o, k, p);
    if (v !== undefined && !Number.isInteger(v))
        fail(pointerAppend(p, k), `expected an integer, found ${v}`);
    return v;
}
function optBool(o, k, p) {
    const v = get(o, k);
    if (v === undefined)
        return undefined;
    if (typeof v !== "boolean")
        fail(pointerAppend(p, k), `expected a boolean, found ${typeName(v)}`);
    return v;
}
function optUnit(o, k, p) {
    const v = optNum(o, k, p);
    if (v !== undefined)
        ensure(v >= 0 && v <= 1, p, k, `must be between 0 and 1, found ${v}`);
    return v;
}
function optArr(o, k, p) {
    const v = get(o, k);
    if (v === undefined)
        return undefined;
    if (!Array.isArray(v))
        fail(pointerAppend(p, k), `expected an array, found ${typeName(v)}`);
    return v;
}
function optEnum(o, k, p, values) {
    const v = optStr(o, k, p);
    if (v !== undefined && !values.includes(v))
        fail(pointerAppend(p, k), `"${v}" is not one of ${values.join(", ")}`);
    return v;
}
function reqEnum(o, k, p, values) {
    const v = optEnum(o, k, p, values);
    if (v === undefined)
        fail(p, `missing required key "${k}"`);
    return v;
}
function ensure(ok, p, k, message) {
    if (!ok)
        fail(pointerAppend(p, k), message);
}
function optLength(o, k, p) {
    const v = get(o, k);
    return v === undefined ? undefined : wrapLength(v, pointerAppend(p, k));
}
function lengthList(o, k, p) {
    const a = optArr(o, k, p);
    return a?.map((v, i) => wrapLength(v, pointerAppend(pointerAppend(p, k), i)));
}
function colorAt(v, p) {
    if (typeof v !== "string")
        fail(p, `expected a string, found ${typeName(v)}`);
    const c = parseColor(v);
    if (!c)
        fail(p, `"${v}" is not a colour: use #RRGGBB or #RRGGBBAA`);
    return c;
}
function optColor(o, k, p) {
    const v = get(o, k);
    return v === undefined ? undefined : colorAt(v, pointerAppend(p, k));
}
function reqColor(o, k, p) {
    const c = optColor(o, k, p);
    if (!c)
        fail(p, `missing required key "${k}"`);
    return c;
}
function unitPoint(o, k, p) {
    const v = get(o, k);
    if (v === undefined)
        return undefined;
    const pp = pointerAppend(p, k);
    if (!Array.isArray(v) || v.length !== 2)
        fail(pp, "a point is [x, y] with two numbers");
    if (typeof v[0] !== "number" || typeof v[1] !== "number")
        fail(pp, "a point is [x, y] with two numbers");
    return { x: v[0], y: v[1] };
}
/** Keys of `o` that are present with an explicit null. */
function nullKeys(o) {
    return new Set(Object.keys(o).filter((k) => o[k] === null));
}
function decodeSizeLengths(v, p) {
    const o = obj(v, p);
    return { width: optLength(o, "width", p), height: optLength(o, "height", p), cleared: nullKeys(o) };
}
function decodeOffsetLengths(v, p) {
    const o = obj(v, p);
    return { x: optLength(o, "x", p), y: optLength(o, "y", p), cleared: nullKeys(o) };
}
function decodeEdgeLengths(v, p) {
    if (isObject(v) && Object.keys(v).some((k) => EDGES.includes(k))) {
        return { top: optLength(v, "top", p), left: optLength(v, "left", p), bottom: optLength(v, "bottom", p), right: optLength(v, "right", p) };
    }
    const l = wrapLength(v, p);
    return { top: l, left: l, bottom: l, right: l };
}
export function areaFromString(s) {
    if (s === "parent" || s === "canvas" || s === "safeArea" || s === "screen")
        return s;
    return s.startsWith("#") && ID_PATTERN.test(s.slice(1)) ? s : undefined;
}
function decodeAnchor(v, p) {
    const o = obj(v, p);
    let to;
    const raw = optStr(o, "to", p);
    if (raw !== undefined) {
        to = areaFromString(raw);
        if (to === undefined)
            fail(pointerAppend(p, "to"), `"${raw}" is not an area: parent, canvas, safeArea, screen or #id`);
    }
    return {
        x: optEnum(o, "x", p, ["leading", "center", "trailing"]),
        y: optEnum(o, "y", p, ["top", "center", "bottom"]),
        to,
        cleared: nullKeys(o),
    };
}
function decodeLayout(v, p) {
    const o = obj(v, p);
    const frame = lengthList(o, "frame", p);
    if (frame)
        ensure(frame.length === 4, p, "frame", "frame is [x, y, width, height]");
    const aspect = optNum(o, "aspect", p);
    if (aspect !== undefined)
        ensure(aspect > 0, p, "aspect", "aspect must be above 0");
    const sub = (k, f) => {
        const x = get(o, k);
        return x === undefined ? undefined : f(x, pointerAppend(p, k));
    };
    return {
        frame,
        inset: sub("inset", decodeEdgeLengths),
        size: sub("size", decodeSizeLengths),
        aspect,
        minSize: sub("minSize", decodeSizeLengths),
        maxSize: sub("maxSize", decodeSizeLengths),
        anchor: sub("anchor", decodeAnchor),
        offset: sub("offset", decodeOffsetLengths),
        span: sub("span", (sv, sp) => {
            const so = obj(sv, sp);
            const columns = optInt(so, "columns", sp) ?? 1, rows = optInt(so, "rows", sp) ?? 1;
            ensure(columns >= 1, sp, "columns", "span columns is at least 1");
            ensure(rows >= 1, sp, "rows", "span rows is at least 1");
            return { columns, rows };
        }),
        cleared: nullKeys(o),
    };
}
function decodeCondition(o, p) {
    const c = {};
    const orientation = optEnum(o, "orientation", p, ["portrait", "landscape"]);
    const device = optEnum(o, "device", p, ["iphone", "ipad", "tv", "mac", "web"]);
    const displayType = optEnum(o, "displayType", p, ["standard", "edgeToEdge", "splitView"]);
    const flag = optStr(o, "flag", p);
    const minWidth = optNum(o, "minWidth", p), minHeight = optNum(o, "minHeight", p);
    const theme = optStr(o, "theme", p), variant = optStr(o, "variant", p);
    if (orientation !== undefined)
        c.orientation = orientation;
    if (device !== undefined)
        c.device = device;
    if (displayType !== undefined)
        c.displayType = displayType;
    if (flag !== undefined)
        c.flag = flag;
    if (minWidth !== undefined)
        c.minWidth = minWidth;
    if (minHeight !== undefined)
        c.minHeight = minHeight;
    if (theme !== undefined)
        c.theme = theme;
    if (variant !== undefined)
        c.variant = variant;
    return c;
}
function decodeVisibility(v, p) {
    if (typeof v === "boolean")
        return v;
    return decodeCondition(obj(v, p), p);
}
function decodeStop(v, p) {
    if (!Array.isArray(v) || (v.length !== 2 && v.length !== 3))
        fail(p, "a stop is [colour, at] or [colour, opacity, at]");
    const color = colorAt(v[0], pointerAppend(p, 0));
    const opacity = v.length === 3 ? v[1] : undefined;
    const at = v[v.length - 1];
    if (typeof at !== "number" || (opacity !== undefined && typeof opacity !== "number"))
        fail(p, "stop opacity and position are numbers");
    if (at < 0 || at > 1 || (opacity !== undefined && (opacity < 0 || opacity > 1))) {
        fail(p, "stop opacity and position are between 0 and 1");
    }
    return { color, opacity: opacity, at };
}
const PAINT_TYPES = ["solid", "linear", "radial", "angular", "image"];
const IMAGE_MODES = ["fit", "fill", "stretch", "tile"];
function decodePaint(v, p) {
    const o = obj(v, p);
    const type = reqEnum(o, "type", p, PAINT_TYPES);
    const stopsRaw = optArr(o, "stops", p);
    const paint = {
        type,
        color: optColor(o, "color", p),
        opacity: optUnit(o, "opacity", p),
        start: unitPoint(o, "start", p),
        end: unitPoint(o, "end", p),
        center: unitPoint(o, "center", p),
        radius: optNum(o, "radius", p),
        startAngle: optNum(o, "startAngle", p),
        stops: stopsRaw ? stopsRaw.map((s, i) => decodeStop(s, pointerAppend(pointerAppend(p, "stops"), i))) : [],
        src: optStr(o, "src", p),
        mode: optEnum(o, "mode", p, IMAGE_MODES),
        scale: optNum(o, "scale", p),
    };
    if (paint.radius !== undefined)
        ensure(paint.radius > 0, p, "radius", "radius must be above 0");
    if (paint.scale !== undefined)
        ensure(paint.scale > 0, p, "scale", "scale must be above 0");
    switch (type) {
        case "solid":
            ensure(paint.color !== undefined, p, "color", "a solid paint needs a color");
            break;
        case "linear":
            ensure(paint.start !== undefined, p, "start", "a linear paint needs start");
            ensure(paint.end !== undefined, p, "end", "a linear paint needs end");
            ensure(paint.stops.length >= 2, p, "stops", "a gradient needs at least two stops");
            break;
        case "radial":
            ensure(paint.center !== undefined, p, "center", "a radial paint needs center");
            ensure(paint.radius !== undefined, p, "radius", "a radial paint needs radius");
            ensure(paint.stops.length >= 2, p, "stops", "a gradient needs at least two stops");
            break;
        case "angular":
            ensure(paint.center !== undefined, p, "center", "an angular paint needs center");
            ensure(paint.stops.length >= 2, p, "stops", "a gradient needs at least two stops");
            break;
        case "image":
            ensure(paint.src !== undefined, p, "src", "an image paint needs src");
            ensure(paint.mode !== "stretch", p, "mode", "an image paint's mode is tile, fit or fill");
            break;
    }
    return paint;
}
function decodeStroke(v, p) {
    const o = obj(v, p);
    const width = optLength(o, "width", p);
    if (!width)
        fail(p, 'missing required key "width"');
    return {
        color: reqColor(o, "color", p),
        opacity: optUnit(o, "opacity", p),
        width,
        align: optEnum(o, "align", p, ["center", "inner", "outer"]) ?? "center",
        dash: lengthList(o, "dash", p) ?? [],
        cap: optEnum(o, "cap", p, ["butt", "round", "square"]) ?? "butt",
        join: optEnum(o, "join", p, ["miter", "round", "bevel"]) ?? "miter",
    };
}
function decodeEffect(v, p) {
    const o = obj(v, p);
    const type = reqEnum(o, "type", p, ["shadow", "blur", "blend", "ci"]);
    const paramsRaw = get(o, "params");
    const e = {
        type,
        color: optColor(o, "color", p),
        opacity: optUnit(o, "opacity", p),
        radius: optLength(o, "radius", p),
        offset: lengthList(o, "offset", p) ?? [],
        spread: optLength(o, "spread", p),
        inner: optBool(o, "inner", p) ?? false,
        mode: optEnum(o, "mode", p, ["normal", "multiply", "screen", "overlay", "softLight", "plus"]),
        name: optStr(o, "name", p),
        params: paramsRaw === undefined ? {} : obj(paramsRaw, pointerAppend(p, "params")),
    };
    ensure(e.offset.length === 0 || e.offset.length === 2, p, "offset", "offset is [x, y]");
    switch (type) {
        case "shadow":
            ensure(e.color !== undefined, p, "color", "a shadow needs a color");
            break;
        case "blur":
            ensure(e.radius !== undefined, p, "radius", "a blur needs a radius");
            break;
        case "blend":
            ensure(e.mode !== undefined, p, "mode", "a blend needs a mode");
            break;
        case "ci":
            ensure(e.name !== undefined, p, "name", "a Core Image effect needs a filter name");
            break;
    }
    return e;
}
function decodeMaterial(v, p) {
    const o = obj(v, p);
    const paramsRaw = get(o, "params");
    return {
        name: reqEnum(o, "name", p, ["gloss", "brushedMetal", "plasticGrain", "crt"]),
        intensity: optUnit(o, "intensity", p) ?? 1,
        params: paramsRaw === undefined ? {} : obj(paramsRaw, pointerAppend(p, "params")),
    };
}
function decodeFont(v, p) {
    const o = obj(v, p);
    const size = optLength(o, "size", p);
    if (!size)
        fail(p, 'missing required key "size"');
    return { family: optStr(o, "family", p), size, weight: optEnum(o, "weight", p, ["regular", "medium", "semibold", "bold"]) ?? "regular" };
}
const SHAPE_KINDS = [
    "rect", "squircle", "ellipse", "capsule", "polygon", "star", "arc", "line", "cross", "kidney", "trapezoid", "path",
];
function decodeShape(v, p) {
    const o = obj(v, p);
    const raw = reqStr(o, "kind", p);
    const kind = raw === "circle" ? "ellipse" : raw;
    if (!SHAPE_KINDS.includes(kind))
        fail(pointerAppend(p, "kind"), `unknown shape kind "${raw}"`);
    const boxRaw = optArr(o, "box", p);
    const shape = {
        kind,
        cornerRadius: optLength(o, "cornerRadius", p),
        corners: lengthList(o, "corners", p),
        sides: optInt(o, "sides", p),
        rotation: optNum(o, "rotation", p),
        points: optInt(o, "points", p),
        innerRatio: optUnit(o, "innerRatio", p),
        startAngle: optNum(o, "startAngle", p),
        endAngle: optNum(o, "endAngle", p),
        inner: optUnit(o, "inner", p),
        from: unitPoint(o, "from", p),
        to: unitPoint(o, "to", p),
        armRatio: optUnit(o, "armRatio", p),
        bulge: optUnit(o, "bulge", p),
        taper: optNum(o, "taper", p),
        d: optStr(o, "d", p),
        box: boxRaw?.map((n, i) => {
            if (typeof n !== "number")
                fail(pointerAppend(pointerAppend(p, "box"), i), `expected a number, found ${typeName(n)}`);
            return n;
        }),
    };
    if (shape.corners)
        ensure(shape.corners.length === 4, p, "corners", "corners is [topLeft, topRight, bottomRight, bottomLeft]");
    if (shape.sides !== undefined)
        ensure(shape.sides >= 3, p, "sides", "a polygon has at least 3 sides");
    if (shape.points !== undefined)
        ensure(shape.points >= 3, p, "points", "a star has at least 3 points");
    if (shape.taper !== undefined)
        ensure(shape.taper >= 0 && shape.taper < 0.5, p, "taper", "taper is at least 0 and below 0.5");
    if (shape.d !== undefined)
        ensure(utf8Length(shape.d) <= MAX_PATH_BYTES, p, "d", `path data is at most ${MAX_PATH_BYTES} bytes`);
    if (shape.box)
        ensure(shape.box.length === 4 && shape.box[2] > 0 && shape.box[3] > 0, p, "box", "box is [x, y, width, height] with a positive size");
    switch (kind) {
        case "polygon":
            ensure(shape.sides !== undefined, p, "sides", "a polygon needs sides");
            break;
        case "star":
            ensure(shape.points !== undefined, p, "points", "a star needs points");
            break;
        case "arc":
            ensure(shape.startAngle !== undefined, p, "startAngle", "an arc needs startAngle");
            ensure(shape.endAngle !== undefined, p, "endAngle", "an arc needs endAngle");
            break;
        case "line":
            ensure(shape.from !== undefined, p, "from", "a line needs from");
            ensure(shape.to !== undefined, p, "to", "a line needs to");
            break;
        case "path":
            ensure(shape.d !== undefined, p, "d", "a path needs d");
            ensure(shape.box !== undefined, p, "box", "a path needs box");
            break;
        default: break;
    }
    return shape;
}
export function utf8Length(s) {
    return new TextEncoder().encode(s).length;
}
function decodePatch(v, p) {
    const o = obj(v, p);
    const target = optStr(o, "target", p);
    if (target !== undefined)
        ensure(PATCH_TARGET_PATTERN.test(target), p, "target", "a target is #id or #id[index]");
    const fills = optArr(o, "fills", p), strokes = optArr(o, "strokes", p);
    const patch = { cleared: nullKeys(o) };
    if (target !== undefined)
        patch.target = target;
    const layout = get(o, "layout");
    if (layout !== undefined)
        patch.layout = decodeLayout(layout, pointerAppend(p, "layout"));
    const visible = get(o, "visible");
    if (visible !== undefined)
        patch.visible = decodeVisibility(visible, pointerAppend(p, "visible"));
    const opacity = optUnit(o, "opacity", p);
    if (opacity !== undefined)
        patch.opacity = opacity;
    if (fills)
        patch.fills = fills.map((f, i) => decodePaint(f, pointerAppend(pointerAppend(p, "fills"), i)));
    if (strokes)
        patch.strokes = strokes.map((s, i) => decodeStroke(s, pointerAppend(pointerAppend(p, "strokes"), i)));
    const text = optStr(o, "text", p);
    if (text !== undefined)
        patch.text = text;
    return patch;
}
function decodeConditional(v, p) {
    const o = obj(v, p);
    const patch = decodePatch(v, p);
    delete patch.target;
    return { condition: decodeCondition(o, p), patch };
}
function decodeState(v, p) {
    const o = obj(v, p);
    const scale = optNum(o, "scale", p);
    if (scale !== undefined)
        ensure(scale > 0, p, "scale", "a state's scale must be above 0");
    const patches = optArr(o, "patch", p) ?? [];
    const patch = patches.map((x, i) => decodePatch(x, pointerAppend(pointerAppend(p, "patch"), i)));
    ensure(patch.every((x) => x.target !== undefined), p, "patch", "every state patch names a target (#id)");
    return { scale, opacity: optUnit(o, "opacity", p), patch };
}
const ALIGNS = ["leading", "center", "trailing"];
function decodeStack(v, p) {
    const o = obj(v, p);
    return {
        axis: reqEnum(o, "axis", p, ["vertical", "horizontal"]),
        spacing: optLength(o, "spacing", p),
        align: optEnum(o, "align", p, ALIGNS) ?? "center",
        distribute: optEnum(o, "distribute", p, ["packed", "spaceBetween"]) ?? "packed",
    };
}
function decodeGrid(v, p) {
    const o = obj(v, p);
    const columns = optInt(o, "columns", p);
    if (columns === undefined)
        fail(p, 'missing required key "columns"');
    ensure(columns >= 1, p, "columns", "a grid has at least one column");
    const grid = { columns, align: optEnum(o, "align", p, ALIGNS) ?? "center" };
    const sp = get(o, "spacing");
    if (sp !== undefined) {
        if (isObject(sp) && ("x" in sp || "y" in sp)) {
            const xy = decodeOffsetLengths(sp, pointerAppend(p, "spacing"));
            grid.spacingX = xy.x;
            grid.spacingY = xy.y;
        }
        else {
            grid.spacingX = grid.spacingY = wrapLength(sp, pointerAppend(p, "spacing"));
        }
    }
    return grid;
}
function decodeRepeat(v, p) {
    const o = obj(v, p);
    const count = optInt(o, "count", p);
    if (count === undefined)
        fail(p, 'missing required key "count"');
    ensure(count >= 1 && count <= MAX_REPEAT, p, "count", `repeat count is 1 to ${MAX_REPEAT}`);
    const scale = optNum(o, "scale", p);
    if (scale !== undefined)
        ensure(scale > 0, p, "scale", "repeat scale must be above 0");
    const off = get(o, "offset");
    return {
        count,
        offset: off === undefined ? undefined : decodeOffsetLengths(off, pointerAppend(p, "offset")),
        rotate: optNum(o, "rotate", p),
        scale,
        pivot: optEnum(o, "pivot", p, ["self", "parent"]) ?? "self",
    };
}
function strList(o, k, p) {
    const a = optArr(o, k, p);
    return a?.map((s, i) => {
        if (typeof s !== "string")
            fail(pointerAppend(pointerAppend(p, k), i), `expected a string, found ${typeName(s)}`);
        return s;
    });
}
function decodeInput(v, p) {
    if (typeof v === "string")
        return v;
    const o = obj(v, p);
    return { up: reqStr(o, "up", p), down: reqStr(o, "down", p), left: reqStr(o, "left", p), right: reqStr(o, "right", p) };
}
const NODE_TYPES = ["group", "shape", "image", "text", "control", "screen"];
const CONTROL_KINDS = ["button", "dpad", "thumbstick", "trigger", "touchSurface", "action"];
export function decodeNode(v, p) {
    const o = obj(v, p);
    const type = reqEnum(o, "type", p, NODE_TYPES);
    const n = { type, when: [], effects: [], children: [], fills: [], strokes: [], states: {}, filters: [] };
    const id = optStr(o, "id", p);
    if (id !== undefined) {
        ensure(ID_PATTERN.test(id), p, "id", "an id starts with a letter or _ and holds letters, digits, _, - and .");
        n.id = id;
    }
    const layout = get(o, "layout");
    if (layout !== undefined)
        n.layout = decodeLayout(layout, pointerAppend(p, "layout"));
    n.when = (optArr(o, "when", p) ?? []).map((w, i) => decodeConditional(w, pointerAppend(pointerAppend(p, "when"), i)));
    const visible = get(o, "visible");
    if (visible !== undefined)
        n.visible = decodeVisibility(visible, pointerAppend(p, "visible"));
    n.opacity = optUnit(o, "opacity", p);
    n.effects = (optArr(o, "effects", p) ?? []).map((e, i) => decodeEffect(e, pointerAppend(pointerAppend(p, "effects"), i)));
    const rep = get(o, "repeat");
    if (rep !== undefined)
        n.repeat = decodeRepeat(rep, pointerAppend(p, "repeat"));
    if (type === "screen")
        n.screenRole = optEnum(o, "role", p, ["main", "top", "bottom", "touch"]);
    else
        n.role = optEnum(o, "role", p, ["knob", "base", "highlight"]);
    const kids = () => (optArr(o, "children", p) ?? []).map((c, i) => decodeNode(c, pointerAppend(pointerAppend(p, "children"), i)));
    switch (type) {
        case "group": {
            n.children = kids();
            const stack = get(o, "stack"), grid = get(o, "grid");
            if (stack !== undefined)
                n.stack = decodeStack(stack, pointerAppend(p, "stack"));
            if (grid !== undefined)
                n.grid = decodeGrid(grid, pointerAppend(p, "grid"));
            ensure(n.stack === undefined || n.grid === undefined, p, "grid", "a group has a stack or a grid, not both");
            break;
        }
        case "shape": {
            const shape = get(o, "shape");
            if (shape === undefined)
                fail(p, 'missing required key "shape"');
            n.shape = decodeShape(shape, pointerAppend(p, "shape"));
            n.fills = (optArr(o, "fills", p) ?? []).map((f, i) => decodePaint(f, pointerAppend(pointerAppend(p, "fills"), i)));
            n.strokes = (optArr(o, "strokes", p) ?? []).map((s, i) => decodeStroke(s, pointerAppend(pointerAppend(p, "strokes"), i)));
            const material = get(o, "material");
            if (material !== undefined)
                n.material = decodeMaterial(material, pointerAppend(p, "material"));
            break;
        }
        case "image":
            n.src = reqStr(o, "src", p);
            n.mode = optEnum(o, "mode", p, IMAGE_MODES);
            n.tint = optColor(o, "tint", p);
            break;
        case "text": {
            n.text = reqStr(o, "text", p);
            const font = get(o, "font");
            if (font !== undefined)
                n.font = decodeFont(font, pointerAppend(p, "font"));
            n.color = optColor(o, "color", p);
            n.align = optEnum(o, "align", p, ALIGNS);
            n.fit = optBool(o, "fit", p);
            break;
        }
        case "control": {
            n.children = kids();
            n.kind = reqEnum(o, "kind", p, CONTROL_KINDS);
            const input = get(o, "input");
            if (input !== undefined)
                n.input = decodeInput(input, pointerAppend(p, "input"));
            n.inputs = strList(o, "inputs", p);
            const hit = get(o, "hit");
            if (hit !== undefined) {
                const ho = obj(hit, pointerAppend(p, "hit"));
                const ext = get(ho, "extend");
                n.hit = { extend: ext === undefined ? undefined : decodeEdgeLengths(ext, pointerAppend(pointerAppend(p, "hit"), "extend")) };
            }
            n.travel = optLength(o, "travel", p);
            const states = get(o, "states");
            if (states !== undefined) {
                const so = obj(states, pointerAppend(p, "states"));
                for (const name of Object.keys(so)) {
                    if (!STATE_NAMES.has(name)) {
                        fail(pointerAppend(p, "states"), `unknown state "${name}": use pressed, selected or pressed.up/down/left/right`);
                    }
                    n.states[name] = decodeState(so[name], pointerAppend(pointerAppend(p, "states"), name));
                }
            }
            const haptic = get(o, "haptic");
            if (haptic !== undefined) {
                const ho = obj(haptic, pointerAppend(p, "haptic"));
                n.haptic = { style: optStr(ho, "style", pointerAppend(p, "haptic")), intensity: optUnit(ho, "intensity", pointerAppend(p, "haptic")) };
            }
            break;
        }
        case "screen": {
            n.aspect = optNum(o, "aspect", p);
            const filters = optArr(o, "filters", p) ?? [];
            n.filters = filters.map((f, i) => {
                const fp = pointerAppend(pointerAppend(p, "filters"), i);
                const fo = obj(f, fp);
                const params = get(fo, "params");
                return { name: reqStr(fo, "name", fp), params: params === undefined ? undefined : obj(params, pointerAppend(fp, "params")) };
            });
            n.placement = optEnum(o, "placement", p, ["app", "controller"]);
            if (n.aspect !== undefined)
                ensure(n.aspect > 0, p, "aspect", "aspect must be above 0");
            break;
        }
    }
    return n;
}
const VARIANT_TARGET = /^#[A-Za-z_][A-Za-z0-9_.-]*$/;
function decodeVariant(v, p) {
    const o = obj(v, p);
    const variant = { label: optStr(o, "label", p), toggle: optBool(o, "toggle", p), patch: [] };
    const match = get(o, "match");
    if (match !== undefined) {
        const mp = pointerAppend(p, "match"), mo = obj(match, mp);
        variant.match = {
            md5: strList(mo, "md5", mp), crc: strList(mo, "crc", mp), filename: strList(mo, "filename", mp),
            title: strList(mo, "title", mp), any: optBool(mo, "any", mp),
        };
    }
    variant.patch = (optArr(o, "patch", p) ?? []).map((x, i) => {
        const pp = pointerAppend(pointerAppend(p, "patch"), i);
        const po = obj(x, pp);
        const target = reqStr(po, "target", pp);
        ensure(VARIANT_TARGET.test(target), pp, "target", "a variant patch targets #id");
        const fields = { ...po };
        delete fields.target;
        return { target, fields };
    });
    return variant;
}
/** True when a variant is a player-selectable layout (`match.any`). */
export function isPlayerSelectable(v) {
    return v.match?.any === true;
}
/** Decodes an already expanded document (see preprocess.ts). */
export function decodeDocument(expanded) {
    const p = "";
    const o = obj(expanded, p);
    const formatVersion = reqStr(o, "formatVersion", p);
    ensure(FORMAT_VERSION_PATTERN.test(formatVersion), p, "formatVersion", `this reader reads format 2.x, found "${formatVersion}"`);
    const gameTypes = strList(o, "gameTypes", p);
    if (!gameTypes)
        fail(p, 'missing required key "gameTypes"');
    ensure(gameTypes.length > 0, p, "gameTypes", "a skin lists at least one game type");
    const refRaw = get(o, "reference");
    if (refRaw === undefined)
        fail(p, 'missing required key "reference"');
    const rp = pointerAppend(p, "reference"), ro = obj(refRaw, rp);
    const reference = { shortSide: reqNum(ro, "shortSide", rp), minScale: reqNum(ro, "minScale", rp), maxScale: reqNum(ro, "maxScale", rp) };
    ensure(reference.shortSide > 0, rp, "shortSide", "shortSide must be above 0");
    ensure(reference.minScale > 0, rp, "minScale", "minScale must be above 0");
    ensure(reference.maxScale >= reference.minScale, rp, "maxScale", "maxScale must be at least minScale");
    const rootRaw = get(o, "root");
    if (rootRaw === undefined)
        fail(p, 'missing required key "root"');
    const root = decodeNode(rootRaw, "/root");
    ensure(root.type === "group", p, "root", "root is a group");
    const variantsRaw = get(o, "variants");
    const variants = {};
    if (variantsRaw !== undefined) {
        const vo = obj(variantsRaw, "/variants");
        for (const name of Object.keys(vo))
            variants[name] = decodeVariant(vo[name], pointerAppend("/variants", name));
    }
    const themesRaw = get(o, "themes");
    const themeNames = themesRaw === undefined ? [] : Object.keys(obj(themesRaw, "/themes")).sort();
    let bake;
    const bakeRaw = get(o, "bake");
    if (bakeRaw !== undefined) {
        const bo = obj(bakeRaw, "/bake");
        const traits = strList(bo, "traits", "/bake");
        bake = { traits };
        for (const t of traits ?? []) {
            if (!traitFamilyKnown(t))
                fail("/bake", `unknown bake trait "${t}": use ${TRAIT_FAMILY_NAMES.join(", ")}`);
        }
    }
    return {
        formatVersion,
        requires: strList(o, "requires", p) ?? [],
        identifier: reqStr(o, "identifier", p),
        name: reqStr(o, "name", p),
        author: optStr(o, "author", p),
        gameTypes,
        reference,
        screens: strList(o, "screens", p),
        bake,
        root,
        variants,
        themeNames,
    };
}
