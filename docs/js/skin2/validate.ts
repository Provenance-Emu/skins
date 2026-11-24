/* EmuSkins — skin format 2.0, the validator (docs/js/skin2/).

   Port of SkinKit's Skin2Validator.swift (sections 1, 3, 6, 8.1, 11): it loads (shape, tokens, parts, every theme
   and variant), `requires` matches the content, the limits hold, ids and references are sound, inputs fit the
   control kinds and game types, and on every trait set the skin bakes to, no two hit frames overlap. The JSON
   Schema document itself (docs/schema/skin-2.0.schema.json, SkinKit) is not ported: decoding enforces the same
   shape and ranges. */

import { rect, REQUIRED_TRAIT_FAMILIES, traitSetsFor } from "./geometry.js";
import type { JSONValue } from "./json.js";
import { parseJSON, pointerAppend, Skin2Error } from "./json.js";
import type { Condition, Document, Layout, Length, Node, Panel } from "./model.js";
import {
  documentPanels, edgeLengthsAll, findNode, inputNames, isAccessoryScreen, lengthUsesSafeArea, MAX_FILE_BYTES, MAX_NODES,
  mentionedCapabilities, nodeCount, panelCanBeShelf, panelHandleID, patchTargetID, preorder, semanticInputsOf, utf8Length,
} from "./model.js";
import {
  isKnownCapability, MAX_ACCESSORY_SCREENS, MAX_PANELS, PANEL_FLAG_PREFIX, panelOpenFlag, PICTURE_SOURCES, pictureCapability,
  SEMANTIC_INPUTS, semanticInput, TOGGLE_PANEL_INPUT,
} from "./capabilities.js";
import { MINIMUM_PROVIDED_CONTROL } from "./provided.js";
import { loadDocumentJSON } from "./preprocess.js";
import type { LoadOptions } from "./preprocess.js";
import { ACTION_INPUTS, ALL_FEATURES, COMMON_INPUTS, inputsForGameType, TOUCH_SURFACE_INPUTS, usedFeatures } from "./features.js";
import { resolve, resolutionControls } from "./layout.js";

export type Severity = "error" | "warning";

/** One validation finding. `pointer` is a JSON Pointer into skin.json (for nodes inside parts or variants, into
    the expanded document, which mirrors the source except that `use` is replaced by the part's node). */
export interface Issue {
  severity: Severity;
  pointer: string;
  message: string;
}

export interface ValidationReport {
  issues: Issue[];
  /** The base document, when it loaded. */
  document?: Document;
  errors: Issue[];
  warnings: Issue[];
  isValid: boolean;
}

/** The size controls should reach on their short side at unit 1 (a warning). */
export const MINIMUM_CONTROL_SIDE = 44;

function report(issues: Issue[], document?: Document): ValidationReport {
  const errors = issues.filter((i) => i.severity === "error");
  return { issues, document, errors, warnings: issues.filter((i) => i.severity === "warning"), isValid: errors.length === 0 };
}

export function validateText(text: string, options: Pick<LoadOptions, "library"> = {}): ValidationReport {
  const bytes = utf8Length(text);
  if (bytes > MAX_FILE_BYTES) return report([{ severity: "error", pointer: "", message: `skin.json is ${bytes} bytes; the limit is ${MAX_FILE_BYTES}` }]);
  let json: JSONValue;
  try { json = parseJSON(text); } catch (e) {
    return report([{ severity: "error", pointer: "", message: (e as Skin2Error).detail ?? String(e) }]);
  }
  return validate(json, options);
}

export function validate(json: JSONValue, options: Pick<LoadOptions, "library"> = {}): ValidationReport {
  const run = new Run();
  let base: Document;
  try {
    base = loadDocumentJSON(json, options);
  } catch (e) {
    if (e instanceof Skin2Error) return report([{ severity: "error", pointer: e.pointer, message: e.detail }]);
    return report([{ severity: "error", pointer: "", message: String(e) }]);
  }

  const docs: Array<{ label: string; doc: Document }> = [{ label: "", doc: base }];
  for (const theme of base.themeNames) {
    try { docs.push({ label: `theme ${theme}`, doc: loadDocumentJSON(json, { ...options, theme }) }); } catch (e) {
      if (e instanceof Skin2Error) run.error(e.pointer, `theme ${theme}: ${e.detail}`);
    }
  }
  for (const variant of Object.keys(base.variants).sort()) {
    try { docs.push({ label: `variant ${variant}`, doc: loadDocumentJSON(json, { ...options, variant }) }); } catch (e) {
      if (e instanceof Skin2Error) run.error(e.pointer, `variant ${variant}: ${e.detail}`);
    }
  }

  run.checkDocumentKeys(base, json, docs.map((d) => d.doc));
  // Every tree: a theme's string tokens can reach ids, inputs and asset paths, a variant's patches anything.
  // A themed or variant tree reports only what the base tree doesn't already.
  run.checkTree(base, "");
  const reported = new Set(run.issues.map((i) => `${i.pointer}\u0000${i.message}`));
  for (const { label, doc } of docs) {
    if (label === "") continue;
    const t = new Run();
    t.checkTree(doc, label);
    const suffix = ` (${label})`;
    for (const issue of t.issues) {
      const plain = issue.message.endsWith(suffix) ? issue.message.slice(0, -suffix.length) : issue.message;
      if (!reported.has(`${issue.pointer}\u0000${plain}`)) run.add(issue);
    }
  }
  for (const { label, doc } of docs) run.checkLayout(doc, label);
  return report(run.issues, base);
}

function assetPathProblem(src: string): string | undefined {
  if (src.includes("://") || src.startsWith("data:")) return "no remote or inline URLs: src is a path under assets/";
  if (src.startsWith("/") || src.split("/").includes("..") || src.includes("\\")) {
    return "src is a relative path under assets/, without .. or a leading /";
  }
  return undefined;
}

interface Context {
  hasRepeatingAncestor?: boolean;
  control?: Node;
  /** The enclosing panel. */
  panel?: Panel;
}

const points = (v: number): string => (v === Math.round(v) ? String(v) : v.toFixed(1));

class Run {
  issues: Issue[] = [];
  /** Panel names seen so far in the tree being checked, with where. */
  private panelSeen = new Map<string, string>();
  /** The open flags of the tree's panels: the only panel.* flags a condition may read. */
  private panelFlags = new Set<string>();

  add(i: Issue): void {
    if (!this.issues.some((x) => x.severity === i.severity && x.pointer === i.pointer && x.message === i.message)) this.issues.push(i);
  }
  error(pointer: string, message: string): void { this.add({ severity: "error", pointer, message }); }
  warn(pointer: string, message: string): void { this.add({ severity: "warning", pointer, message }); }

  // ── Document level ─────────────────────────────────────────────────────

  checkDocumentKeys(doc: Document, json: JSONValue, documents: Document[]): void {
    const used = usedFeatures(json, documents);
    const listed = new Set([...doc.requires, ...doc.optional]);
    doc.requires.forEach((name, i) => {
      if (!ALL_FEATURES.includes(name)) {
        this.warn(`/requires/${i}`, `"${name}" is not a 2.0 feature name; readers that don't know it fall back to the classic skin`);
      }
    });
    for (const name of [...used].filter((u) => !listed.has(u)).sort()) {
      this.error("/requires", `the skin uses ${name} but does not list it in requires or optional`);
    }
    doc.optional.forEach((name, i) => {
      if (!ALL_FEATURES.includes(name)) this.error(`/optional/${i}`, `"${name}" is not a 2.0 feature name`);
      else if (doc.requires.includes(name)) this.error(`/optional/${i}`, `${name} is in both requires and optional; list it once`);
      else if (!used.has(name)) this.warn(`/optional/${i}`, `optional lists ${name}, which the skin does not use`);
    });
    doc.requires.forEach((name, i) => {
      if (ALL_FEATURES.includes(name) && !used.has(name)) this.warn(`/requires/${i}`, `requires lists ${name}, which the skin does not use`);
    });
    const traits = doc.bake?.traits;
    if (traits) {
      for (const family of REQUIRED_TRAIT_FAMILIES) {
        if (!traits.includes(family)) this.error("/bake/traits", `bake.traits must include ${family}: the base representations must be a complete classic skin`);
      }
    }
    doc.gameTypes.forEach((gt, i) => {
      if (inputsForGameType(gt) === undefined) this.warn(`/gameTypes/${i}`, `no input table for game type "${gt}"; its inputs are not checked`);
    });
    doc.screens?.forEach((id, i) => {
      const node = findNode(doc, id);
      if (node?.type !== "screen") this.error(`/screens/${i}`, `"${id}" is not the id of a screen node`);
      else if (isAccessoryScreen(node)) this.error(`/screens/${i}`, `"${id}" is an accessory screen; screens lists game screens`);
    });
  }

  // ── Tree ───────────────────────────────────────────────────────────────

  checkTree(doc: Document, label: string): void {
    const suffix = label === "" ? "" : ` (${label})`;
    const count = nodeCount(doc.root);
    let accessory = 0;
    preorder(doc.root, (n) => { if (isAccessoryScreen(n)) accessory += 1; });
    if (accessory > MAX_ACCESSORY_SCREENS) {
      this.error("/root", `the skin has ${accessory} accessory screens; the limit is ${MAX_ACCESSORY_SCREENS} accessory screens${suffix}`);
    }
    const panels = documentPanels(doc);
    if (panels.length > MAX_PANELS) this.error("/root", `the skin has ${panels.length} panels; the limit is ${MAX_PANELS} panels${suffix}`);
    this.panelSeen = new Map();
    this.panelFlags = new Set(panels.map((p) => panelOpenFlag(p.name)));
    if (count > MAX_NODES) this.error("/root", `the skin has ${count} nodes after expanding parts; the limit is ${MAX_NODES}${suffix}`);
    const state = { ids: new Map<string, string>(), seenScreen: false };
    this.visit(doc.root, "/root", {}, doc, state, suffix);
  }

  private visit(n: Node, p: string, context: Context, doc: Document, state: { ids: Map<string, string>; seenScreen: boolean }, suffix: string): void {
    // Anchors are checked before this node's id is recorded: a node can't anchor to itself.
    const layouts: Array<[Layout, string]> = n.layout ? [[n.layout, `${p}/layout`]] : [];
    n.when.forEach((w, i) => { if (w.patch.layout) layouts.push([w.patch.layout, `${p}/when/${i}/layout`]); });
    for (const [l, lp] of layouts) {
      this.checkLengths(l, lp, suffix);
      const to = l.anchor?.to;
      if (to && to.startsWith("#")) {
        if (!state.ids.has(to.slice(1))) this.error(`${lp}/anchor/to`, `anchors to ${to}, which is not a node earlier in document order${suffix}`);
      } else if (to === "screen") {
        if (!state.seenScreen) this.error(`${lp}/anchor/to`, `anchors to screen, but no screen node comes earlier${suffix}`);
      }
    }

    const conditions: Array<[Condition, string]> = [];
    if (n.visible !== undefined && typeof n.visible !== "boolean") conditions.push([n.visible, `${p}/visible`]);
    n.when.forEach((w, i) => {
      conditions.push([w.condition, `${p}/when/${i}`]);
      if (w.patch.visible !== undefined && typeof w.patch.visible !== "boolean") conditions.push([w.patch.visible, `${p}/when/${i}/visible`]);
    });
    for (const [c, cp] of conditions) {
      if (c.flag !== undefined && c.flag.startsWith(PANEL_FLAG_PREFIX) && !this.panelFlags.has(c.flag)) {
        this.error(`${cp}/flag`, `"${c.flag}" is not the open flag of a panel in this skin; flags starting with ${PANEL_FLAG_PREFIX} are reserved${suffix}`);
      }
      for (const name of c.has ?? []) {
        if (!isKnownCapability(name)) {
          this.error(`${cp}/has`, `"${name}" is not a capability (${PICTURE_SOURCES.map(pictureCapability).join(", ")}, input.<name>)${suffix}`);
        }
      }
    }

    if (n.id !== undefined) {
      const first = state.ids.get(n.id);
      if (first !== undefined) this.error(`${p}/id`, `id "${n.id}" is already used at ${first}${suffix}`);
      else state.ids.set(n.id, p);
    }
    if (n.type === "screen" && !isAccessoryScreen(n)) state.seenScreen = true;

    switch (n.type) {
      case "control": this.checkControl(n, p, doc, suffix); break;
      case "screen":
        if (n.id === undefined) this.error(p, `a screen needs an id${suffix}`);
        if (isAccessoryScreen(n) && n.source !== undefined) {
          if (!PICTURE_SOURCES.includes(n.source)) {
            this.error(`${p}/source`, `"${n.source}" is not a picture source: use game or ${PICTURE_SOURCES.join(", ")}${suffix}`);
          }
          if (n.screenRole !== undefined) this.error(`${p}/role`, `an accessory screen takes no role: it is never the game picture${suffix}`);
          if (n.placement !== undefined) this.error(`${p}/placement`, `an accessory screen takes no placement${suffix}`);
          if ((n.repeat?.count ?? 1) > 1) {
            this.error(`${p}/repeat`, `an accessory screen cannot repeat${suffix}`);
          } else if (context.hasRepeatingAncestor) {
            this.error(p, `an accessory screen cannot have a repeating ancestor${suffix}`);
          }
        }
        break;
      case "group":
        if (n.panel) this.checkPanel(n.panel, n, p, context, suffix);
        if ((n.stack || n.grid) && n.layout?.size && !n.layout.frame && !n.layout.inset) {
          this.warn(`${p}/layout/size`, `a stack or grid group takes its size from its children; size is ignored (use frame or inset for a fixed size)${suffix}`);
        }
        if (n.stack?.distribute === "spaceBetween" && !n.layout?.frame && !n.layout?.inset) {
          this.warn(`${p}/stack/distribute`, `spaceBetween has no room to spread into unless the group has a frame or an inset${suffix}`);
        }
        break;
      case "image": {
        const problem = n.src !== undefined ? assetPathProblem(n.src) : undefined;
        if (problem) this.error(`${p}/src`, problem + suffix);
        break;
      }
      case "text": {
        const family = n.font?.family;
        if (family !== undefined && (family.includes("/") || family.includes("..") || family.includes(":"))) {
          this.error(`${p}/font/family`, `a font family names a file in assets/fonts/, not a path or URL${suffix}`);
        }
        if (n.font && lengthUsesSafeArea(n.font.size)) this.error(`${p}/font/size`, `safe is only allowed in offset and inset${suffix}`);
        break;
      }
      case "shape": break;
    }
    // Every paint the node can show: its own fills and those its `when` and state patches set.
    const paints: Array<[string, NonNullable<Node["fills"]>]> = [[p, n.fills]];
    n.when.forEach((w, i) => paints.push([`${p}/when/${i}`, w.patch.fills ?? []]));
    for (const name of Object.keys(n.states).sort()) {
      n.states[name].patch.forEach((patch, j) => paints.push([`${pointerAppend(`${p}/states`, name)}/patch/${j}`, patch.fills ?? []]));
    }
    for (const [base, fills] of paints) {
      fills.forEach((paint, i) => {
        const problem = paint.src !== undefined ? assetPathProblem(paint.src) : undefined;
        if (problem) this.error(`${base}/fills/${i}/src`, problem + suffix);
      });
    }
    this.checkPaintLengths(n, p, suffix);

    if (n.duplicate && n.type !== "screen" && n.type !== "control") {
      this.error(`${p}/duplicate`, `duplicate belongs on a screen or a control: it says the node does not claim its picture or input${suffix}`);
    }
    if (n.role === "knob" && context.control?.kind !== "thumbstick") this.error(`${p}/role`, `role knob belongs inside a thumbstick control${suffix}`);
    if (n.repeat && n.type === "control") this.error(`${p}/repeat`, `controls can't repeat: hit testing ignores copies${suffix}`);
    if (n.type !== "group" && n.type !== "control" && n.children.length > 0) this.warn(`${p}/children`, `only groups and controls have children${suffix}`);

    let inner = { ...context, hasRepeatingAncestor: !!context.hasRepeatingAncestor || (n.repeat?.count ?? 1) > 1 };
    if (n.panel) inner.panel = n.panel;
    if (n.type === "control" && inputNames(n).includes(TOGGLE_PANEL_INPUT)
        && (n.id === undefined || context.panel === undefined || n.id !== panelHandleID(context.panel))) {
      this.error(p, `${TOGGLE_PANEL_INPUT} belongs to a shelf's handle: the control its panel names in handle${suffix}`);
    }
    if (n.type === "control") {
      if (context.control) this.error(p, `a control inside a control is art, not a control${suffix}`);
      inner = { ...inner, control: n };
    }
    n.children.forEach((child, i) => this.visit(child, `${p}/children/${i}`, inner, doc, state, suffix));
  }

  private checkPanel(panel: Panel, n: Node, p: string, context: Context, suffix: string): void {
    if (context.panel) this.error(`${p}/panel`, `a panel can't be inside a panel${suffix}`);
    const first = this.panelSeen.get(panel.name);
    if (first !== undefined) this.error(`${p}/panel/name`, `panel name "${panel.name}" is already used at ${first}${suffix}`);
    else this.panelSeen.set(panel.name, p);
    panel.needs.forEach((name, i) => {
      if (!isKnownCapability(name)) this.error(`${p}/panel/needs/${i}`, `"${name}" is not a capability${suffix}`);
    });
    if (!panelCanBeShelf(n)) return;
    const id = panelHandleID(panel);
    if (id === undefined) {
      this.error(`${p}/panel/handle`, `a shelf needs a handle: the #id of an action control in the group whose input is ${TOGGLE_PANEL_INPUT}${suffix}`);
      return;
    }
    let handle: Node | undefined;
    for (const child of n.children) preorder(child, (x) => { if (!handle && x.id === id) handle = x; });
    const found = handle as Node | undefined;
    if (!found || found.type !== "control") {
      this.error(`${p}/panel/handle`, `#${id} is not a control inside this group${suffix}`);
      return;
    }
    const names = inputNames(found);
    if (found.kind !== "action" || names.length !== 1 || names[0] !== TOGGLE_PANEL_INPUT) {
      this.error(`${p}/panel/handle`, `#${id} must be an action control whose input is ${TOGGLE_PANEL_INPUT}${suffix}`);
    }
  }

  private checkLengths(l: Layout, p: string, suffix: string): void {
    const noSafe: Array<[Length | undefined, string]> = [];
    (l.frame ?? []).forEach((f, i) => noSafe.push([f, `${p}/frame/${i}`]));
    for (const [name, s] of [["size", l.size], ["minSize", l.minSize], ["maxSize", l.maxSize]] as const) {
      noSafe.push([s?.width, `${p}/${name}/width`]);
      noSafe.push([s?.height, `${p}/${name}/height`]);
    }
    for (const [length, lp] of noSafe) if (lengthUsesSafeArea(length)) this.error(lp, `safe is only allowed in offset and inset${suffix}`);
  }

  private checkPaintLengths(n: Node, p: string, suffix: string): void {
    const all: Array<[Length | undefined, string]> = [
      [n.travel, `${p}/travel`], [n.stack?.spacing, `${p}/stack/spacing`],
      [n.grid?.spacingX, `${p}/grid/spacing`], [n.grid?.spacingY, `${p}/grid/spacing`],
      [n.repeat?.offset?.x, `${p}/repeat/offset/x`], [n.repeat?.offset?.y, `${p}/repeat/offset/y`],
      [n.shape?.cornerRadius, `${p}/shape/cornerRadius`],
    ];
    for (const l of edgeLengthsAll(n.hit?.extend)) all.push([l, `${p}/hit/extend`]);
    (n.shape?.corners ?? []).forEach((c, i) => all.push([c, `${p}/shape/corners/${i}`]));
    n.strokes.forEach((s, i) => {
      all.push([s.width, `${p}/strokes/${i}/width`]);
      for (const d of s.dash) all.push([d, `${p}/strokes/${i}/dash`]);
    });
    n.effects.forEach((e, i) => {
      all.push([e.radius, `${p}/effects/${i}/radius`]);
      all.push([e.spread, `${p}/effects/${i}/spread`]);
      for (const o of e.offset) all.push([o, `${p}/effects/${i}/offset`]);
    });
    for (const [length, lp] of all) if (lengthUsesSafeArea(length)) this.error(lp, `safe is only allowed in offset and inset${suffix}`);
  }

  private checkControl(n: Node, p: string, doc: Document, suffix: string): void {
    const kind = n.kind;
    if (!kind) return;
    if (n.id === undefined) this.error(p, `a control needs an id${suffix}`);
    const names = inputNames(n);
    const isDirections = typeof n.input === "object";
    if (isDirections && kind !== "dpad") this.error(`${p}/input`, `only a d-pad takes {up, down, left, right}${suffix}`);
    if (kind === "dpad" && !isDirections) this.error(`${p}/input`, `a d-pad's input is {"up", "down", "left", "right"}${suffix}`);
    if (names.length === 0) this.error(p, `a control needs input or inputs${suffix}`);

    // Semantic inputs (dotted names): from the registry, momentary, on a button or a trigger.
    const semantic = semanticInputsOf(n);
    for (const name of semantic) {
      const entry = semanticInput(name);
      if (!entry) this.error(p, `"${name}" is not a semantic input (${SEMANTIC_INPUTS.map((e) => e.name).join(", ")})${suffix}`);
      else if (entry.kind === "twoPosition") this.error(p, `"${name}" is a two-position switch; the switch control is not built yet${suffix}`);
      else if (kind !== "button" && kind !== "trigger") this.error(p, `"${name}" is a semantic input: put it on a button or a trigger, not a ${kind}${suffix}`);
    }
    if (semantic.length > 0 && kind !== "button" && kind !== "trigger") return;

    switch (kind) {
      case "touchSurface":
        for (const name of names) {
          if (!TOUCH_SURFACE_INPUTS.has(name)) this.error(p, `a touch surface takes ${[...TOUCH_SURFACE_INPUTS].sort().join(", ")}, not "${name}"${suffix}`);
        }
        break;
      case "action":
        if (names.length !== 1) this.error(p, `an action control fires exactly one app action${suffix}`);
        for (const name of names) {
          if (!ACTION_INPUTS.has(name)) this.error(p, `"${name}" is not an app action (${[...ACTION_INPUTS].sort().join(", ")})${suffix}`);
        }
        break;
      default:
        for (const gt of doc.gameTypes) {
          const system = inputsForGameType(gt);
          if (!system) continue;
          for (const name of names) {
            if (!system.has(name) && !COMMON_INPUTS.has(name) && !ACTION_INPUTS.has(name) && !semantic.includes(name)) this.error(p, `"${name}" is not an input of game type ${gt}${suffix}`);
          }
        }
    }

    // States: names per kind, targets inside this control.
    const inner = new Map<string, Node>();
    for (const child of n.children) preorder(child, (x) => { if (x.id !== undefined) inner.set(x.id, x); });
    let knobs = 0;
    for (const child of n.children) preorder(child, (x) => { if (x.role === "knob") knobs += 1; });
    if (kind === "thumbstick" && knobs === 0) this.warn(p, `a thumbstick has no role: knob child to move${suffix}`);
    for (const name of Object.keys(n.states).sort()) {
      const state = n.states[name];
      const sp = pointerAppend(`${p}/states`, name);
      if (name.startsWith("pressed.") && kind !== "dpad") this.error(sp, `per-direction states are for d-pads${suffix}`);
      state.patch.forEach((patch, i) => {
        const t = patchTargetID(patch);
        if (!t) return;
        const tp = `${sp}/patch/${i}/target`;
        const target = inner.get(t.id);
        if (!target) { this.error(tp, `#${t.id} is not inside this control${suffix}`); return; }
        if (t.copy !== undefined) {
          const count = target.repeat?.count ?? 1;
          if (t.copy >= count) this.error(tp, `#${t.id} has ${count} cop${count === 1 ? "y" : "ies"}; [${t.copy}] is out of range${suffix}`);
        }
      });
    }
  }

  // ── Layout on the bake trait sets ──────────────────────────────────────

  checkLayout(doc: Document, label: string): void {
    const suffix = label === "" ? "" : `, ${label}`;
    const reportedPairs = new Set<string>();
    const reportedSmall = new Set<string>();
    const reportedHandles = new Set<string>();
    // Shelves open independently. The panel limit bounds the number of flag sets to 64.
    if (documentPanels(doc).length > MAX_PANELS) return;
    const shelfNames = new Set<string>();
    preorder(doc.root, (node) => { if (node.panel && panelCanBeShelf(node)) shelfNames.add(node.panel.name); });
    const names = [...shelfNames].sort();
    const capabilities = mentionedCapabilities(doc);
    const situations: Array<{ capabilities: Set<string>; flags: Set<string>; label: string }> = [];
    for (let mask = 0; mask < 1 << names.length; mask++) {
      const open = names.filter((_, i) => (mask & (1 << i)) !== 0);
      const flags = new Set(open.map(panelOpenFlag));
      const label = open.length === 0 ? "" : `, open shelves: ${open.join(", ")}`;
      situations.push({ capabilities: new Set(), flags, label });
      if (capabilities.size > 0) situations.push({ capabilities, flags, label: ", capabilities on" + label });
    }
    for (const base of traitSetsFor(doc.bake?.traits)) for (const situation of situations) {
      const trait = { name: base.name + situation.label, environment: { ...base.environment, capabilities: situation.capabilities, flags: situation.flags } };
      const r = resolve(doc, trait.environment);
      for (const w of r.warnings) this.error(w.pointer, `${w.message} (${trait.name}${suffix})`);
      for (const panel of r.panels) {
        if (panel.presentation !== "shelf") continue;
        const handle = resolutionControls(r).find((c) => c.panelName === panel.panel.name && c.node.id === panelHandleID(panel.panel));
        const hit = handle?.hitFrame;
        if (!handle || !hit) continue;
        const side = MINIMUM_PROVIDED_CONTROL;
        if ((hit.width < side.width - 0.0001 || hit.height < side.height - 0.0001) && !reportedHandles.has(`${handle.pointer}size`)) {
          reportedHandles.add(`${handle.pointer}size`);
          this.error(handle.pointer, `the handle #${handle.node.id ?? "?"} takes touches in ${points(hit.width)} × ${points(hit.height)} pt; a shelf's handle needs at least ${side.width} × ${side.height} pt (${trait.name}${suffix})`);
        }
        if (!panel.handleReachable && !reportedHandles.has(`${handle.pointer}safe`)) {
          reportedHandles.add(`${handle.pointer}safe`);
          this.error(handle.pointer, `the handle #${handle.node.id ?? "?"} is outside the safe area on ${trait.name}${suffix}: the player could not reach it`);
        }
      }
      const controls = resolutionControls(r).filter((c) => c.node.kind !== "touchSurface");
      controls.forEach((a, i) => {
        if (!a.hitFrame) return;
        for (const b of controls.slice(i + 1)) {
          if (!b.hitFrame || !rect.overlaps(a.hitFrame, b.hitFrame)) continue;
          const pair = `${a.pointer}\u0000${b.pointer}`;
          if (reportedPairs.has(pair)) continue;
          reportedPairs.add(pair);
          this.error(a.pointer, `hit frame of #${a.node.id ?? "?"} overlaps #${b.node.id ?? "?"} on ${trait.name}${suffix}`);
        }
      });
      for (const c of resolutionControls(r)) {
        const side = Math.min(c.exactFrame.width, c.exactFrame.height) / r.unit;
        if (side < MINIMUM_CONTROL_SIDE - 0.0001 && !reportedSmall.has(c.pointer)) {
          reportedSmall.add(c.pointer);
          this.warn(c.pointer, `#${c.node.id ?? "?"} is ${side.toFixed(1)} pt on its short side at unit 1; controls should be at least ${MINIMUM_CONTROL_SIDE} pt (${trait.name}${suffix})`);
        }
      }
    }
  }
}
