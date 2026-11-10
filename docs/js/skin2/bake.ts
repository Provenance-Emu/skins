import { traitSetsFor } from "./geometry.js";
import type { Rect, Size, TraitSet } from "./geometry.js";
import { resolve, resolvedPreorder, resolutionControls } from "./layout.js";
import type { Resolution, ResolvedNode } from "./layout.js";
import { inputNames } from "./model.js";
import type { Document } from "./model.js";
import { loadDocument } from "./preprocess.js";
import { validateText } from "./validate.js";
import type { JSONObject, JSONValue } from "./json.js";

export interface BakeArtwork {
  pdf(document: Document, resolution: Resolution, frame: Rect): Promise<Uint8Array>;
  preview(document: Document, resolution: Resolution): Promise<Uint8Array>;
  nativeSize(gameType: string): Size | undefined;
}

export interface BakedBundle {
  files: Map<string, Uint8Array>;
  variantLabel?: string;
  warnings: string[];
}

type Representations = Record<string, Record<string, Record<string, JSONObject>>>;
const classicActions = new Set(["menu", "quickSave", "quickLoad", "fastForward", "toggleAltRepresentations"]);

function classicItem(control: ResolvedNode, knob?: JSONObject): JSONObject | undefined {
  const { node, frame, hitFrame } = control;
  let inputs: JSONValue = inputNames(node);
  if (node.kind === "dpad") {
    if (!node.input || typeof node.input === "string") return undefined;
    inputs = { ...node.input };
  } else if (node.kind === "thumbstick") {
    if (typeof node.input !== "string") return undefined;
    const prefix = node.input.toLowerCase() === "cstick" ? "rightThumbstick" : node.input;
    inputs = { up: prefix + "Up", down: prefix + "Down", left: prefix + "Left", right: prefix + "Right" };
  } else {
    const names = inputNames(node).filter((name) => node.kind !== "action" || classicActions.has(name));
    if (names.length === 0) return undefined;
    inputs = names;
  }
  const item: JSONObject = { inputs, frame: { ...frame } };
  if (hitFrame) {
    item.extendedEdges = {
      top: frame.y - hitFrame.y, left: frame.x - hitFrame.x,
      bottom: hitFrame.y + hitFrame.height - (frame.y + frame.height),
      right: hitFrame.x + hitFrame.width - (frame.x + frame.width),
    };
  }
  if (node.haptic) {
    item.haptic = {};
    if (node.haptic.style !== undefined) item.haptic.style = node.haptic.style;
    if (node.haptic.intensity !== undefined) item.haptic.intensity = node.haptic.intensity;
  }
  if (node.kind === "touchSurface") item.kind = node.kind;
  if (knob) item.thumbstick = knob;
  return item;
}

function withoutKnobs(node: ResolvedNode): ResolvedNode {
  return { ...node, children: node.children.filter((child) => child.node.role !== "knob").map(withoutKnobs) };
}

function screenRank(screen: ResolvedNode): number {
  return screen.node.screenRole === "bottom" || screen.node.screenRole === "touch" ? 1 : 0;
}

/** Stable JSON shared with the Swift baker. */
function canonical(value: JSONValue): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((key) => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  }
  return JSON.stringify(value);
}

function layoutSignature(resolution: Resolution): string {
  return canonical(resolvedPreorder(resolution.root)
    .filter(({ node }) => node.type === "control" || node.type === "screen" || node.role === "knob")
    .map(({ node, frame, hitFrame }) => [
      node.id ?? null, { ...frame }, hitFrame ? { ...hitFrame } : null, node.placement ?? null,
      node.kind ?? null, typeof node.input === "object" ? { ...node.input } : node.input ?? null, node.inputs ?? [],
      node.screenRole ?? null, node.filters.map(({ name, params }) => [name, params ?? null]),
    ]));
}

export async function bakeClassic(
  source: Uint8Array, assets: ReadonlyMap<string, Uint8Array>, artwork: BakeArtwork,
): Promise<BakedBundle[]> {
  const text = new TextDecoder().decode(source);
  const report = validateText(text);
  if (!report.isValid || !report.document) {
    throw new Error(report.errors.map(({ pointer, message }) => `${pointer}: ${message}`).join("\n"));
  }
  const base = report.document;
  const traits = traitSetsFor(base.bake?.traits);
  const variants = Object.keys(base.variants).sort();
  const selectable = variants.filter((name) => base.variants[name].match?.any === true);
  const splitThemes = [...base.themeNames].sort().filter((theme) =>
    [undefined, ...variants].some((variant) => {
      const original = loadDocument(text, { variant });
      const candidate = loadDocument(text, { theme, variant });
      return traits.some(({ environment }) =>
        layoutSignature(resolve(original, environment)) !== layoutSignature(resolve(candidate, environment)));
    }));
  const inlineThemes = [...base.themeNames].sort().filter((theme) => !splitThemes.includes(theme));
  const combinations = [undefined, ...selectable].flatMap((variant) =>
    [undefined, ...splitThemes].map((theme) => ({ variant, theme })));
  const bundles: BakedBundle[] = [];
  for (const [gameIndex, gameType] of base.gameTypes.entries()) {
    const native = artwork.nativeSize(gameType);
    for (const { variant, theme } of combinations) {
      const files = new Map<string, Uint8Array>([["skin.json", source]]);
      const warnings: string[] = [];
      for (const [name, data] of assets) {
        if (name.startsWith("assets/") && !name.includes("\\") && !name.split("/").some((part) => !part || part === "." || part === "..")) {
          files.set(name, data);
        }
      }

      async function representations(doc: Document, sets: TraitSet[], prefix: string): Promise<Representations> {
        const result: Representations = {};
        for (const trait of sets) {
          const resolution = resolve(doc, trait.environment);
          const path = `bake/${prefix}-${trait.name}`;
          const rect = { x: 0, y: 0, ...trait.size };
          files.set(path + ".pdf", await artwork.pdf(doc, { ...resolution, root: withoutKnobs(resolution.root) }, rect));
          const items: JSONObject[] = [];
          const itemAssets: JSONObject = {};
          for (const [index, control] of resolutionControls(resolution).entries()) {
            let config: JSONObject | undefined;
            const knob = control.node.kind === "thumbstick"
              ? resolvedPreorder(control).find((child) => child.node.role === "knob") : undefined;
            if (knob && knob.frame.width > 0 && knob.frame.height > 0) {
              const name = `${path}-knob-${index}.pdf`;
              files.set(name, await artwork.pdf(doc, { ...resolution, root: knob }, knob.frame));
              config = { name, width: knob.frame.width, height: knob.frame.height };
              itemAssets[String(items.length)] = { resizable: name };
            }
            const item = classicItem(control, config);
            if (item) items.push(item);
            else warnings.push(`${trait.name}: skipped ${control.pointer}`);
          }
          const classicAssets: JSONObject = { resizable: path + ".pdf" };
          if (Object.keys(itemAssets).length) classicAssets.items = itemAssets;
          const screens = resolvedPreorder(resolution.root).filter((node) => node.node.type === "screen")
            .sort((a, b) => screenRank(a) - screenRank(b)).map((screen): JSONObject => {
              const entry: JSONObject = {
                outputFrame: { ...screen.frame },
                maintainAspectRatio: true, placement: screen.node.placement ?? "app",
              };
              if (native) {
                const stacksScreens = /^(nds|ds)$/.test(gameType.toLowerCase().split(".").at(-1) ?? "");
                entry.inputFrame = { x: 0, y: stacksScreens && screenRank(screen) === 1 ? native.height : 0, ...native };
              }
              if (screen.node.filters.length) entry.filters = screen.node.filters.map(({ name, params }): JSONObject =>
                params ? { name, parameters: params } : { name });
              return entry;
            });
          ((result[trait.device] ??= {})[trait.displayType] ??= {})[trait.orientation] = {
            mappingSize: { ...trait.size }, assets: classicAssets, items, screens, translucent: false,
            extendedEdges: { top: 0, left: 0, bottom: 0, right: 0 },
          };
        }
        return result;
      }

      const doc = loadDocument(text, { theme, variant });
      const labels = [variant === undefined ? undefined : base.variants[variant].label ?? variant, theme]
        .filter((label) => label !== undefined);
      const variantLabel = labels.length ? labels.join(" — ") : undefined;
      const info: JSONObject = {
        name: variantLabel === undefined ? base.name : `${base.name} — ${variantLabel}`,
        identifier: base.identifier + (gameIndex === 0 ? "" : `.game${gameIndex}`) + (variant === undefined ? "" : `.${variant}`) +
          (theme === undefined ? "" : `.theme.${theme}`),
        gameTypeIdentifier: gameType, debug: false, representations: await representations(doc, traits, "base"),
        format2: { source: "skin.json", formatVersion: base.formatVersion, requires: base.requires },
      };
      if (variant !== undefined) (info.format2 as JSONObject).variant = variant;
      if (theme !== undefined) (info.format2 as JSONObject).theme = theme;
      if (variant === undefined) {
        const overrides: JSONObject = Object.create(null);
        for (const [index, key] of variants.entries()) {
          const entry = base.variants[key];
          if (entry.match?.any === true) continue;
          const reps = await representations(loadDocument(text, { theme, variant: key }), traits, `variant-${index}`);
          if (entry.toggle === true) info.altRepresentations = reps;
          const { md5 = [], crc = [], filename = [], title = [] } = entry.match ?? {};
          for (const match of [...md5, ...crc, ...filename, ...title]) {
            if (Object.hasOwn(overrides, match)) throw new Error(`Duplicate game override: ${match}`);
            overrides[match] = reps;
          }
        }
        if (Object.keys(overrides).length) info.gameOverrides = overrides;
      }
      if (theme === undefined && inlineThemes.length) {
        const themes: JSONObject[] = [];
        for (const [index, name] of inlineThemes.entries()) {
          const themed = loadDocument(text, { theme: name, variant });
          const reps = await representations(themed, traits, `theme-${index}`);
          const themeAssets: JSONObject = {};
          for (const trait of traits) {
            const device = (themeAssets[trait.device] ??= {}) as JSONObject;
            const display = (device[trait.displayType] ??= {}) as JSONObject;
            display[trait.orientation] = reps[trait.device][trait.displayType][trait.orientation].assets;
          }
          themes.push({ id: name, name, assets: themeAssets });
        }
        info.themes = themes;
      }
      files.set("info.json", new TextEncoder().encode(canonical(info)));
      const preview = traits.find((trait) => trait.name === "iphone-edgeToEdge-portrait");
      if (preview) files.set("preview.png", await artwork.preview(doc, resolve(doc, preview.environment)));
      bundles.push({ files, variantLabel, warnings });
    }
  }
  return bundles;
}
