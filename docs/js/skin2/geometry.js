/* EmuSkins — skin format 2.0, geometry, environment and trait sets (docs/js/skin2/).

   Port of SkinKit's Skin2Geometry.swift and Skin2Environment.swift. Plain number geometry so the resolver's
   output maps one-to-one onto layout.json. Top-left origin, y down, canvas points. */
export const ZERO_INSETS = { top: 0, left: 0, bottom: 0, right: 0 };
export function insetValue(i, edge) {
    return i[edge];
}
export const rect = {
    of(size) {
        return { x: 0, y: 0, width: size.width, height: size.height };
    },
    maxX: (r) => r.x + r.width,
    maxY: (r) => r.y + r.height,
    midX: (r) => r.x + r.width / 2,
    midY: (r) => r.y + r.height / 2,
    /** Grows each edge outward by the inset (negative values shrink). */
    outset(r, i) {
        return { x: r.x - i.left, y: r.y - i.top, width: r.width + i.left + i.right, height: r.height + i.top + i.bottom };
    },
    inset(r, i) {
        return rect.outset(r, { top: -i.top, left: -i.left, bottom: -i.bottom, right: -i.right });
    },
    /** True when the two rectangles share area; rectangles that only touch along an edge do not overlap. */
    overlaps(a, b) {
        return a.x < rect.maxX(b) && b.x < rect.maxX(a) && a.y < rect.maxY(b) && b.y < rect.maxY(a);
    },
    /** Edges rounded to the half point (section 2, "Rounding"): floor(2v + 0.5) / 2 on each edge. */
    roundedToHalfPoint(r) {
        const x0 = halfPoint(r.x), x1 = halfPoint(rect.maxX(r));
        const y0 = halfPoint(r.y), y1 = halfPoint(rect.maxY(r));
        return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
    },
    /** [x, y, width, height], the form layout.json and classic frames use. */
    array: (r) => [r.x, r.y, r.width, r.height],
};
/** Half-point rounding, ties toward +infinity. Negative zero becomes zero. */
export function halfPoint(v) {
    const r = Math.floor(2 * v + 0.5) / 2;
    return r === 0 ? 0 : r;
}
/** Rounds to `places` decimals (transform matrices in layout.json), ties toward +infinity. */
export function roundDecimals(v, places) {
    const f = Math.pow(10, places);
    const r = Math.floor(v * f + 0.5) / f;
    return r === 0 ? 0 : r;
}
export const IDENTITY = { a: 1, b: 0, c: 0, d: 1, tx: 0, ty: 0 };
export const transform = {
    translation: (x, y) => ({ a: 1, b: 0, c: 0, d: 1, tx: x, ty: y }),
    rotation(degrees) {
        const r = (degrees * Math.PI) / 180;
        const cos = Math.cos(r), sin = Math.sin(r);
        return { a: cos, b: sin, c: -sin, d: cos, tx: 0, ty: 0 };
    },
    scale: (s) => ({ a: s, b: 0, c: 0, d: s, tx: 0, ty: 0 }),
    /** `t` applied first, then `next`. */
    then(t, next) {
        return {
            a: t.a * next.a + t.b * next.c,
            b: t.a * next.b + t.b * next.d,
            c: t.c * next.a + t.d * next.c,
            d: t.c * next.b + t.d * next.d,
            tx: t.tx * next.a + t.ty * next.c + next.tx,
            ty: t.tx * next.b + t.ty * next.d + next.ty,
        };
    },
    /** [a, b, c, d, tx, ty]: the matrix rounded to 4 decimals and the translation to the half point. */
    roundedArray: (t) => [
        roundDecimals(t.a, 4), roundDecimals(t.b, 4), roundDecimals(t.c, 4), roundDecimals(t.d, 4),
        halfPoint(t.tx), halfPoint(t.ty),
    ],
};
export const ORIENTATIONS = ["portrait", "landscape"];
export const DEVICES = ["iphone", "ipad", "tv", "mac", "web"];
export const DISPLAY_TYPES = ["standard", "edgeToEdge", "splitView"];
export function makeEnvironment(size, o = {}) {
    return {
        size,
        safeArea: o.safeArea ?? ZERO_INSETS,
        orientation: o.orientation ?? (size.height >= size.width ? "portrait" : "landscape"),
        device: o.device ?? "iphone",
        displayType: o.displayType ?? "edgeToEdge",
        flags: o.flags ?? new Set(),
    };
}
export const canvasRect = (e) => rect.of(e.size);
export const safeRect = (e) => rect.inset(canvasRect(e), e.safeArea);
function t(device, displayType, orientation, w, h, top, left, bottom, right) {
    const size = { width: w, height: h };
    const safeArea = { top, left, bottom, right };
    return {
        device, displayType, orientation, size, safeArea,
        name: `${device}-${displayType}-${orientation}`,
        family: `${device}.${displayType}`,
        environment: makeEnvironment(size, { safeArea, orientation, device, displayType }),
    };
}
/** Section 8.1, in table order. */
export const TRAIT_SETS = [
    t("iphone", "standard", "portrait", 414, 736, 0, 0, 0, 0),
    t("iphone", "standard", "landscape", 736, 414, 0, 0, 0, 0),
    t("iphone", "edgeToEdge", "portrait", 393, 852, 59, 0, 34, 0),
    t("iphone", "edgeToEdge", "landscape", 852, 393, 0, 59, 21, 59),
    t("ipad", "standard", "portrait", 834, 1194, 24, 0, 20, 0),
    t("ipad", "standard", "landscape", 1194, 834, 24, 0, 20, 0),
    t("ipad", "splitView", "portrait", 639, 1194, 24, 0, 20, 0),
    t("ipad", "splitView", "landscape", 639, 834, 24, 0, 20, 0),
    t("tv", "standard", "landscape", 1920, 1080, 60, 80, 60, 80),
];
export const TRAIT_FAMILY_NAMES = [...new Set(TRAIT_SETS.map((s) => s.family))];
/** The families every skin bakes: the base representations must be a complete classic skin. */
export const REQUIRED_TRAIT_FAMILIES = ["iphone.standard", "iphone.edgeToEdge"];
export function traitFamilyKnown(name) {
    return TRAIT_FAMILY_NAMES.includes(name);
}
/** The trait sets a skin bakes to: bake.traits, or all of them. */
export function traitSetsFor(bakeTraits) {
    return bakeTraits ? TRAIT_SETS.filter((s) => bakeTraits.includes(s.family)) : TRAIT_SETS;
}
