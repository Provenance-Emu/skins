/* EmuSkins — skin format 2.0, offscreen bitmaps and masks (docs/js/skin2/).

   Port of SkinKit's Skin2Raster.swift. Shadows, inner shadows and blur rasterise a node to an offscreen bitmap
   and run a separable Gaussian with σ = radius / 2 on it, so the kernel is known and the same in both renderers
   (section 9.3): a normalised kernel of radius ⌈3σ⌉ pixels, zero outside the bitmap. Canvas shadowBlur is not
   used. */
/** A factory for browsers: OffscreenCanvas where it exists, else a canvas element. */
export function browserSurfaceFactory() {
    return (w, h) => {
        if (typeof OffscreenCanvas !== "undefined")
            return new OffscreenCanvas(w, h);
        const c = document.createElement("canvas");
        c.width = w;
        c.height = h;
        return c;
    };
}
export function contextOf(s) {
    const ctx = s.getContext("2d");
    if (!ctx)
        throw new Error("could not get a 2D context");
    return ctx;
}
/** Pixels per point along the context's current transform (the square root of its determinant). */
export function pixelScale(ctx) {
    const t = ctx.getTransform();
    const s = Math.sqrt(Math.abs(t.a * t.d - t.b * t.c));
    return s > 0 ? s : 1;
}
/** Pixels kept in a buffer: a 4096 × 4096 limit keeps a stray huge shadow from allocating gigabytes. */
export const MAX_SIDE = 4096;
/** A normalised Gaussian kernel with radius ⌈3σ⌉ pixels (one tap when σ is under a tenth of a pixel). */
export function gaussianKernel(sigma) {
    if (!(sigma >= 0.1))
        return new Float32Array([1]);
    const radius = Math.ceil(3 * sigma);
    const k = new Float32Array(2 * radius + 1);
    let sum = 0;
    for (let i = -radius; i <= radius; i++) {
        const v = Math.exp(-(i * i) / (2 * sigma * sigma));
        k[i + radius] = v;
        sum += v;
    }
    for (let i = 0; i < k.length; i++)
        k[i] /= sum;
    return k;
}
/** Separable convolution of `channels` interleaved float channels, zero outside the image. */
function convolve(data, width, height, channels, kernel) {
    const radius = (kernel.length - 1) / 2;
    const tmp = new Float32Array(data.length);
    // Horizontal.
    for (let y = 0; y < height; y++) {
        const row = y * width * channels;
        for (let x = 0; x < width; x++) {
            const lo = Math.max(0, x - radius), hi = Math.min(width - 1, x + radius);
            for (let c = 0; c < channels; c++) {
                let acc = 0;
                for (let sx = lo; sx <= hi; sx++)
                    acc += data[row + sx * channels + c] * kernel[sx - x + radius];
                tmp[row + x * channels + c] = acc;
            }
        }
    }
    // Vertical.
    for (let y = 0; y < height; y++) {
        const lo = Math.max(0, y - radius), hi = Math.min(height - 1, y + radius);
        for (let x = 0; x < width; x++) {
            for (let c = 0; c < channels; c++) {
                let acc = 0;
                for (let sy = lo; sy <= hi; sy++)
                    acc += tmp[(sy * width + x) * channels + c] * kernel[sy - y + radius];
                data[(y * width + x) * channels + c] = acc;
            }
        }
    }
}
/** Antialiasing and smoothing settings shared by every context the renderer draws into. */
export function configure(ctx) {
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
}
/** An offscreen RGBA bitmap over `region` (canvas points) at `scale` pixels per point. Its context's user space
    is canvas points, y down, the same as the context the renderer draws into. */
export class Bitmap {
    region;
    scale;
    width;
    height;
    surface;
    context;
    constructor(region, scale, width, height, surface, context) {
        this.region = region;
        this.scale = scale;
        this.width = width;
        this.height = height;
        this.surface = surface;
        this.context = context;
    }
    static make(factory, region, scale) {
        const x = Math.min(region.x, region.x + region.width), y = Math.min(region.y, region.y + region.height);
        const rw = Math.abs(region.width), rh = Math.abs(region.height);
        if (!(rw > 0 && rh > 0 && scale > 0 && Number.isFinite(rw) && Number.isFinite(rh)))
            return undefined;
        let s = scale;
        const longest = Math.max(rw, rh) * s;
        if (longest > MAX_SIDE)
            s *= MAX_SIDE / longest;
        const w = Math.max(1, Math.ceil(rw * s)), h = Math.max(1, Math.ceil(rh * s));
        const surface = factory(w, h);
        const ctx = contextOf(surface);
        ctx.scale(s, s);
        ctx.translate(-x, -y);
        configure(ctx);
        return new Bitmap({ x, y, width: w / s, height: h / s }, s, w, h, surface, ctx);
    }
    /** The alpha channel as a mask. */
    alpha() {
        const data = this.context.getImageData(0, 0, this.width, this.height);
        const mask = new Mask(this.width, this.height, this.region, this.scale);
        for (let i = 0; i < mask.bytes.length; i++)
            mask.bytes[i] = data.data[i * 4 + 3];
        return mask;
    }
    /** Blurs the bitmap in place with a Gaussian of σ = `sigma` points (premultiplied channels, so translucent
        edges don't bleed their colour). */
    blur(sigma) {
        const kernel = gaussianKernel(sigma * this.scale);
        if (kernel.length <= 1)
            return;
        const img = this.context.getImageData(0, 0, this.width, this.height);
        const px = img.data;
        const f = new Float32Array(this.width * this.height * 4);
        for (let i = 0; i < px.length; i += 4) {
            const a = px[i + 3] / 255;
            f[i] = px[i] * a;
            f[i + 1] = px[i + 1] * a;
            f[i + 2] = px[i + 2] * a;
            f[i + 3] = px[i + 3];
        }
        convolve(f, this.width, this.height, 4, kernel);
        for (let i = 0; i < px.length; i += 4) {
            const a = f[i + 3];
            if (a <= 0) {
                px[i] = px[i + 1] = px[i + 2] = px[i + 3] = 0;
                continue;
            }
            px[i] = Math.min(255, Math.round((f[i] * 255) / a));
            px[i + 1] = Math.min(255, Math.round((f[i + 1] * 255) / a));
            px[i + 2] = Math.min(255, Math.round((f[i + 2] * 255) / a));
            px[i + 3] = Math.min(255, Math.round(a));
        }
        this.context.save();
        this.context.setTransform(1, 0, 0, 1, 0, 0);
        this.context.globalCompositeOperation = "copy";
        this.context.putImageData(img, 0, 0);
        this.context.restore();
    }
}
/** An 8-bit coverage mask over `region` (canvas points) at `scale` pixels per point; row 0 is the top. */
export class Mask {
    width;
    height;
    region;
    scale;
    bytes;
    constructor(width, height, region, scale) {
        this.width = width;
        this.height = height;
        this.region = region;
        this.scale = scale;
        this.bytes = new Uint8Array(width * height);
    }
    clone() {
        const m = new Mask(this.width, this.height, this.region, this.scale);
        m.bytes.set(this.bytes);
        return m;
    }
    blur(sigma) {
        const kernel = gaussianKernel(sigma * this.scale);
        if (kernel.length <= 1)
            return;
        const f = Float32Array.from(this.bytes);
        convolve(f, this.width, this.height, 1, kernel);
        for (let i = 0; i < f.length; i++)
            this.bytes[i] = Math.min(255, Math.max(0, Math.round(f[i])));
    }
    /** Grows (positive) or shrinks (negative) the covered area by `points`, with a round structuring element. */
    spread(points) {
        const r = Math.round(Math.abs(points) * this.scale);
        if (r <= 0)
            return;
        const offsets = [];
        for (let dy = -r; dy <= r; dy++)
            for (let dx = -r; dx <= r; dx++)
                if (dx * dx + dy * dy <= r * r)
                    offsets.push([dx, dy]);
        const src = this.bytes, out = new Uint8Array(src.length);
        const grow = points > 0;
        for (let y = 0; y < this.height; y++) {
            for (let x = 0; x < this.width; x++) {
                let v = grow ? 0 : 255;
                for (const [dx, dy] of offsets) {
                    const sx = x + dx, sy = y + dy;
                    const s = sx < 0 || sy < 0 || sx >= this.width || sy >= this.height ? 0 : src[sy * this.width + sx];
                    if (grow ? s > v : s < v)
                        v = s;
                }
                out[y * this.width + x] = v;
            }
        }
        this.bytes = out;
    }
    invert() {
        for (let i = 0; i < this.bytes.length; i++)
            this.bytes[i] = 255 - this.bytes[i];
    }
    /** The mask as a surface of one colour whose alpha is the mask times `alpha`, to draw into `region`. */
    tinted(factory, rgb, alpha) {
        const surface = factory(this.width, this.height);
        const ctx = contextOf(surface);
        const img = ctx.createImageData(this.width, this.height);
        for (let i = 0; i < this.bytes.length; i++) {
            img.data[i * 4] = rgb[0];
            img.data[i * 4 + 1] = rgb[1];
            img.data[i * 4 + 2] = rgb[2];
            img.data[i * 4 + 3] = Math.round(this.bytes[i] * alpha);
        }
        ctx.putImageData(img, 0, 0);
        return surface;
    }
}
