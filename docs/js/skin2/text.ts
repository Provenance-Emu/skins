/* EmuSkins — skin format 2.0, text as glyph outlines (docs/js/skin2/).

   Port of SkinKit's Skin2Text.swift (section 9.3): the line is shaped (cmap, the font's `liga` ligatures and its
   GPOS pair kerning, no hinting, no subpixel positioning) and each glyph's outline is filled as a path, so text
   is a shape and two renderers on two text stacks draw the same pixels from the same font file. The default face
   is Outfit (SIL OFL 1.1), bundled as fonts/Outfit-Regular.ttf and Outfit-Bold.ttf next to these modules; the
   SkinKit renderer ships the same files. `regular` and `medium` use Regular, `semibold` and `bold` use Bold.

   The shaper reads the tables opentype.js parses (https://opentype.js.org). This module only needs the shape of
   the Font object, so it does not import the library: the host loads opentype.js and passes parsed fonts. */

import type { FontWeight, TextAlign } from "./model.js";
import { Path } from "./path.js";

/** The slice of an opentype.js Glyph this module reads. */
export interface GlyphLike {
  index: number;
  advanceWidth?: number;
  getPath(x: number, y: number, fontSize: number): { commands: Array<{ type: string; x?: number; y?: number; x1?: number; y1?: number; x2?: number; y2?: number }> };
}

interface CoverageLike {
  format: number;
  glyphs?: number[];
  ranges?: Array<{ start: number; end: number }>;
}

interface LigatureLike {
  ligGlyph: number;
  components: number[];
}

interface GsubLookupLike {
  lookupType: number;
  subtables: Array<{ coverage?: CoverageLike; ligatureSets?: LigatureLike[][] }>;
}

/** The slice of an opentype.js Font this module reads. */
export interface FontLike {
  unitsPerEm: number;
  /** hhea ascender / descender (descender is negative) in font units. */
  ascender: number;
  descender: number;
  charToGlyphIndex(char: string): number;
  glyphs: { get(index: number): GlyphLike };
  getKerningValue(left: number, right: number): number;
  tables?: {
    gsub?: {
      features: Array<{ tag: string; feature: { lookupListIndexes?: number[]; lookupListIndices?: number[] } }>;
      lookups: GsubLookupLike[];
    };
  };
}

/** The bundled default faces, and fonts a skin ships in assets/fonts/ by file name. */
export interface FontSet {
  regular: FontLike;
  bold: FontLike;
  /** `family` (a file name in assets/fonts/) → parsed font. */
  families?: Map<string, FontLike>;
}

export function defaultFont(fonts: FontSet, weight: FontWeight): FontLike {
  return weight === "semibold" || weight === "bold" ? fonts.bold : fonts.regular;
}

function coverageIndex(c: CoverageLike | undefined, glyph: number): number {
  if (!c) return -1;
  if (c.glyphs) return c.glyphs.indexOf(glyph);
  let base = 0;
  for (const r of (c.ranges as Array<{ start: number; end: number; index?: number }> | undefined) ?? []) {
    if (glyph >= r.start && glyph <= r.end) return (r.index ?? base) + (glyph - r.start);
    base += r.end - r.start + 1;
  }
  return -1;
}

/** Applies the font's `liga` lookups (ligature substitution, GSUB type 4) to a run of glyph indexes. */
function applyLigatures(font: FontLike, glyphs: number[]): number[] {
  const gsub = font.tables?.gsub;
  if (!gsub) return glyphs;
  const lookupIndexes = new Set<number>();
  for (const f of gsub.features) {
    if (f.tag === "liga") for (const i of f.feature.lookupListIndexes ?? f.feature.lookupListIndices ?? []) lookupIndexes.add(i);
  }
  let out = glyphs;
  for (const li of [...lookupIndexes].sort((a, b) => a - b)) {
    const lookup = gsub.lookups[li];
    if (!lookup || lookup.lookupType !== 4) continue;
    const next: number[] = [];
    for (let i = 0; i < out.length; ) {
      let replaced = false;
      for (const st of lookup.subtables) {
        const ci = coverageIndex(st.coverage, out[i]);
        const set = ci >= 0 ? st.ligatureSets?.[ci] : undefined;
        if (!set) continue;
        for (const lig of set) {
          const n = lig.components.length;
          if (lig.components.every((g, k) => out[i + 1 + k] === g)) {
            next.push(lig.ligGlyph);
            i += n + 1;
            replaced = true;
            break;
          }
        }
        if (replaced) break;
      }
      if (!replaced) next.push(out[i++]);
    }
    out = next;
  }
  return out;
}

export interface ShapedLine {
  glyphs: GlyphLike[];
  /** Advance of each glyph in font units, kerning included. */
  advances: number[];
  /** Total advance in font units. */
  width: number;
}

export function shapeLine(font: FontLike, text: string): ShapedLine {
  const indexes = [...text].map((ch) => font.charToGlyphIndex(ch));
  const shaped = applyLigatures(font, indexes);
  const glyphs = shaped.map((i) => font.glyphs.get(i));
  const advances = glyphs.map((g, i) => {
    const kern = i + 1 < glyphs.length ? font.getKerningValue(g.index, glyphs[i + 1].index) || 0 : 0;
    return (g.advanceWidth ?? 0) + kern;
  });
  return { glyphs, advances, width: advances.reduce((s, a) => s + a, 0) };
}

/** The outline of `text` laid out in `frame`: one line, vertically centred on the font's ascent and descent,
    aligned by `align`. `size` is in canvas points. With `fit`, the size shrinks (to 60 % at most) until the line
    fits the frame's width. */
export function textPath(
  text: string, font: FontLike, size: number, align: TextAlign, fit: boolean,
  frame: { x: number; y: number; width: number; height: number },
): Path {
  const line = shapeLine(font, text);
  let pointSize = size;
  const scaleFor = (s: number) => s / font.unitsPerEm;
  let width = line.width * scaleFor(pointSize);
  if (fit && width > frame.width && width > 0) {
    pointSize = size * Math.max(0.6, frame.width / width);
    width = line.width * scaleFor(pointSize);
  }
  const ascent = font.ascender * scaleFor(pointSize);
  const descent = -font.descender * scaleFor(pointSize);
  const x = align === "leading" ? frame.x : align === "center" ? frame.x + frame.width / 2 - width / 2 : frame.x + frame.width - width;
  const baseline = frame.y + frame.height / 2 + (ascent - descent) / 2;
  const out = new Path();
  let pen = x;
  line.glyphs.forEach((g, i) => {
    for (const c of g.getPath(pen, baseline, pointSize).commands) {
      switch (c.type) {
        case "M": out.moveTo(c.x!, c.y!); break;
        case "L": out.lineTo(c.x!, c.y!); break;
        case "C": out.curveTo(c.x1!, c.y1!, c.x2!, c.y2!, c.x!, c.y!); break;
        case "Q": out.quadTo(c.x1!, c.y1!, c.x!, c.y!); break;
        case "Z": out.close(); break;
      }
    }
    pen += line.advances[i] * scaleFor(pointSize);
  });
  return out;
}
