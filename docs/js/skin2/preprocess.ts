/* EmuSkins — skin format 2.0, the preprocessor and loader (docs/js/skin2/).

   Port of SkinKit's Skin2Preprocessor.swift and Skin2Document.load. Expands a 2.0 source document before typed
   decoding (sections 3.9 and 7):

   - "$name" (a whole string) becomes the token's value, with the active theme's overrides.
   - "@name" (a whole string, inside a part's node) becomes the part argument.
   - {"use": "part", "with": {…}, "id", "layout", "when", "visible"} becomes the part's node with its parameters
     substituted, then the caller's keys merged over it. Parts may use parts, 8 deep, never recursively.
   - Ids inside a part instance are scoped to it ("<instance>.body"), and #body references inside the part
     (state targets, anchors) follow.
   - The chosen variant's patches apply to the nodes they target (variants apply before `when`).

   The output drops `tokens` and `parts`; everything else (including `variants` and `themes`) stays. */

import type { Document } from "./model.js";
import { decodeDocument, FORMAT_VERSION_PATTERN, MAX_FILE_BYTES, MAX_NODES, LengthError, parseColor, parseLength, utf8Length } from "./model.js";
import type { JSONObject, JSONValue } from "./json.js";
import { isObject, parseJSON, pointerAppend, Skin2Error } from "./json.js";
import { STD_PARTS } from "./std-parts.js";

export type TokenType = "color" | "length" | "number" | "string";
export type ParamType = "string" | "number" | "length" | "color" | "shape" | "paint";

/** A token's type and value. Length values are stored in their explicit form ({"pt": 8}), so a length token can
    fill a part parameter of type `length`. */
export interface Token {
  type: TokenType;
  value: JSONValue;
}

export const MAX_PART_DEPTH = 8;
export const REFERENCE_PATTERN = /^[$@][A-Za-z_][A-Za-z0-9_]*$/;
export const TOKEN_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
/** Keys a part instance may carry besides `use` and `with`. */
export const INSTANCE_KEYS = ["id", "layout", "when", "visible"];
/** Layout fields that merge one level deep in patches; the rest are replaced. */
const MERGED_LAYOUT_KEYS = new Set(["size", "minSize", "maxSize", "anchor", "offset"]);
const TOKEN_TYPES: TokenType[] = ["color", "length", "number", "string"];
const PARAM_TYPES: ParamType[] = ["string", "number", "length", "color", "shape", "paint"];

interface Part {
  name: string;
  params: Record<string, { type: ParamType; defaultValue?: JSONValue }>;
  node: JSONObject;
  pointer: string;
}

/** Counts nodes as one expansion builds them: expansion stops at the node limit instead of building the whole
    tree and counting afterwards. */
class NodeBudget {
  count = 0;
  constructor(readonly limit = MAX_NODES) {}
  take(pointer: string): void {
    this.count += 1;
    if (this.count > this.limit) {
      throw new Skin2Error(pointer, `the skin has more than ${this.limit} nodes after expanding parts; the limit is ${this.limit}`);
    }
  }
}

interface Scope {
  params?: Record<string, JSONValue>;
  parts: string[];
  budget: NodeBudget;
  /** The outermost part instance being expanded, in the document's own tree: where a budget error points. */
  site?: string;
}

export class Preprocessor {
  readonly source: JSONObject;
  readonly library: Record<string, JSONValue>;

  /** `library` adds parts the skin may `use` without defining (the standard parts). It defaults to STD_PARTS, the
      hook where SkinKit's std.* library lands (SkinKit#123). */
  constructor(source: JSONValue, library: Record<string, JSONValue> = STD_PARTS) {
    if (!isObject(source)) throw new Skin2Error("", "a skin is a JSON object");
    this.source = source;
    this.library = library;
  }

  // ── Tokens ─────────────────────────────────────────────────────────────

  /** The token table, with `theme`'s overrides when given. */
  tokens(theme?: string): Record<string, Token> {
    const out: Record<string, Token> = {};
    const raw = this.source.tokens;
    if (raw !== undefined) {
      if (!isObject(raw)) throw new Skin2Error("/tokens", "tokens is an object");
      for (const [name, value] of Object.entries(raw)) {
        const p = pointerAppend("/tokens", name);
        if (!TOKEN_NAME_PATTERN.test(name)) throw new Skin2Error(p, "a token name holds letters, digits and _");
        out[name] = parseToken(value, p);
      }
    }
    const themes = this.themeTable();
    for (const [themeName, overrides] of Object.entries(themes)) {
      for (const [name, value] of Object.entries(overrides)) {
        const p = pointerAppend(pointerAppend("/themes", themeName), name);
        const base = out[name];
        if (!base) throw new Skin2Error(p, `theme sets $${name}, which is not a token`);
        let t = parseToken(value, p);
        if (base.type === "length" && t.type === "number" && typeof t.value === "number") t = { type: "length", value: { pt: t.value } };
        if (t.type !== base.type) throw new Skin2Error(p, `theme gives $${name} a ${t.type}, but the token is a ${base.type}`);
        if (themeName === theme) out[name] = t;
      }
    }
    if (theme !== undefined && themes[theme] === undefined) throw new Skin2Error("/themes", `no theme named "${theme}"`);
    return out;
  }

  private themeTable(): Record<string, JSONObject> {
    const raw = this.source.themes;
    if (raw === undefined) return {};
    if (!isObject(raw)) throw new Skin2Error("/themes", "themes is an object");
    const out: Record<string, JSONObject> = {};
    for (const [name, value] of Object.entries(raw)) {
      if (!isObject(value)) throw new Skin2Error(pointerAppend("/themes", name), "a theme is an object of token values");
      out[name] = value;
    }
    return out;
  }

  // ── Parts ──────────────────────────────────────────────────────────────

  private part(name: string, at: string): Part {
    const local = isObject(this.source.parts) ? this.source.parts : undefined;
    let pointer: string, raw: JSONValue;
    if (local && name in local) {
      raw = local[name];
      pointer = pointerAppend("/parts", name);
    } else if (name in this.library) {
      raw = this.library[name];
      pointer = `library:${name}`;
    } else if (name.startsWith("std.")) {
      throw new Skin2Error(at, `the standard parts library (${name}) is not available in this reader`);
    } else {
      throw new Skin2Error(at, `no part named "${name}"`);
    }
    if (!isObject(raw)) throw new Skin2Error(pointer, 'a part is {"params": {…}, "node": {…}}');
    const node = raw.node;
    if (!isObject(node)) throw new Skin2Error(pointer, "a part needs a node object");
    const params: Part["params"] = {};
    if (raw.params !== undefined) {
      if (!isObject(raw.params)) throw new Skin2Error(`${pointer}/params`, "params is an object");
      for (const [pname, spec] of Object.entries(raw.params)) {
        const pp = pointerAppend(`${pointer}/params`, pname);
        if (!TOKEN_NAME_PATTERN.test(pname)) throw new Skin2Error(pp, "a parameter name holds letters, digits and _");
        const t = isObject(spec) ? spec.type : undefined;
        if (typeof t !== "string" || !PARAM_TYPES.includes(t as ParamType)) {
          throw new Skin2Error(pp, "a parameter has a type: string, number, length, color, shape or paint");
        }
        params[pname] = { type: t as ParamType, defaultValue: (spec as JSONObject).default };
      }
    }
    return { name, params, node, pointer };
  }

  // ── Expansion ──────────────────────────────────────────────────────────

  /** The expanded document. */
  expand(theme?: string, variant?: string): JSONObject {
    const v = this.source.formatVersion;
    if (typeof v === "string" && !FORMAT_VERSION_PATTERN.test(v)) {
      throw new Skin2Error("/formatVersion", `this reader reads format 2.x, found "${v}"`);
    }
    const tokens = this.tokens(theme);
    const out: JSONObject = { ...this.source };
    delete out.tokens;
    delete out.parts;
    const root = this.source.root;
    if (root === undefined) throw new Skin2Error("", 'missing required key "root"');
    const budget = new NodeBudget();
    const expandedRoot = this.expandValue(root, "/root", { parts: [], budget }, tokens, true);
    if (this.source.variants !== undefined) {
      const expandedVariants = this.expandValue(this.source.variants, "/variants", { parts: [], budget }, tokens, false);
      out.variants = expandedVariants;
      if (variant !== undefined) applyVariant(variant, expandedVariants, expandedRoot);
    } else if (variant !== undefined) {
      throw new Skin2Error("/variants", `no variant named "${variant}"`);
    }
    out.root = expandedRoot;
    return out;
  }

  /** `isNode`: `value` sits where a node goes (the root, a part's node, an element of `children`). */
  private expandValue(value: JSONValue, p: string, scope: Scope, tokens: Record<string, Token>, isNode = false): JSONValue {
    if (typeof value === "string") {
      if (!REFERENCE_PATTERN.test(value)) return value;
      const name = value.slice(1);
      if (value.startsWith("$")) {
        const t = tokens[name];
        if (!t) throw new Skin2Error(p, `unknown token $${name}`);
        return t.value;
      }
      if (!scope.params) throw new Skin2Error(p, `@${name} is a part parameter; it only means something inside a part's node`);
      if (!(name in scope.params)) throw new Skin2Error(p, `part ${scope.parts[scope.parts.length - 1] ?? ""} has no parameter @${name}`);
      return scope.params[name];
    }
    if (Array.isArray(value)) {
      return value.map((v, i) => this.expandValue(v, pointerAppend(p, i), scope, tokens));
    }
    if (isObject(value)) {
      if ("use" in value) return this.instantiate(value, p, scope, tokens);
      if (isNode) scope.budget.take(scope.site ?? p);
      const out: JSONObject = {};
      // Children first, so a runaway tree stops before the rest of each node is expanded.
      if (Array.isArray(value.children)) {
        const cp = pointerAppend(p, "children");
        out.children = value.children.map((c, i) => this.expandValue(c, pointerAppend(cp, i), scope, tokens, true));
      }
      for (const [k, v] of Object.entries(value)) {
        if (k in out) continue;
        out[k] = this.expandValue(v, pointerAppend(p, k), scope, tokens);
      }
      return out;
    }
    return value;
  }

  private instantiate(o: JSONObject, p: string, scope: Scope, tokens: Record<string, Token>): JSONValue {
    const name = o.use;
    if (typeof name !== "string") throw new Skin2Error(`${p}/use`, "use names a part");
    const extra = Object.keys(o).sort().find((k) => k !== "use" && k !== "with" && !INSTANCE_KEYS.includes(k));
    if (extra !== undefined) throw new Skin2Error(pointerAppend(p, extra), "a part instance takes only use, with, id, layout, when and visible");
    if (scope.parts.includes(name)) {
      throw new Skin2Error(`${p}/use`, `part ${name} uses itself (${[...scope.parts, name].join(" → ")})`);
    }
    if (scope.parts.length >= MAX_PART_DEPTH) throw new Skin2Error(`${p}/use`, `parts nest at most ${MAX_PART_DEPTH} deep`);
    const part = this.part(name, `${p}/use`);
    const site = scope.site ?? p;

    // Arguments in the caller's scope, then defaults (tokens only), then type checks.
    const args: Record<string, JSONValue> = {};
    const withValue = o.with ?? {};
    if (!isObject(withValue)) throw new Skin2Error(`${p}/with`, "with is an object of arguments");
    for (const [key, raw] of Object.entries(withValue)) {
      const ap = pointerAppend(`${p}/with`, key);
      if (!(key in part.params)) throw new Skin2Error(ap, `part ${name} has no parameter "${key}"`);
      args[key] = this.expandValue(raw, ap, scope, tokens);
    }
    for (const [key, spec] of Object.entries(part.params)) {
      if (key in args) continue;
      const dp = pointerAppend(`${part.pointer}/params`, key);
      if (spec.defaultValue === undefined) throw new Skin2Error(`${p}/with`, `part ${name} needs "${key}"`);
      args[key] = this.expandValue(spec.defaultValue, `${dp}/default`, { parts: [], budget: scope.budget, site }, tokens);
    }
    for (const [key, value] of Object.entries(args)) {
      const message = typeError(value, part.params[key].type);
      if (message) {
        const ap = key in withValue ? pointerAppend(`${p}/with`, key) : `${pointerAppend(`${part.pointer}/params`, key)}/default`;
        throw new Skin2Error(ap, `${name}.${key} is a ${part.params[key].type}: ${message}`);
      }
    }

    let body = this.expandValue(part.node, `${part.pointer}/node`, { params: args, parts: [...scope.parts, name], budget: scope.budget, site }, tokens, true);
    if (!isObject(body)) throw new Skin2Error(`${part.pointer}/node`, "a part's node is an object");
    let node: JSONObject = body;

    // Scope the part's inner ids to this instance.
    let instanceID: string | undefined;
    if (o.id !== undefined) {
      const e = this.expandValue(o.id, `${p}/id`, scope, tokens);
      if (typeof e === "string") instanceID = e;
    }
    const inner = new Set<string>();
    for (const child of Array.isArray(node.children) ? node.children : []) collectIDs(child, inner);
    if (inner.size > 0) {
      if (instanceID === undefined) {
        throw new Skin2Error(p, `part ${name} names inner nodes (${[...inner].sort().join(", ")}); give this instance an id`);
      }
      body = qualify(node, inner, instanceID, true);
      if (isObject(body)) node = body;
    }

    for (const key of [...INSTANCE_KEYS].sort()) {
      if (!(key in o)) continue;
      const value = this.expandValue(o[key], pointerAppend(p, key), scope, tokens);
      if (key === "layout" && node.layout !== undefined) node.layout = mergeLayoutJSON(node.layout, value);
      else if (value === null) delete node[key];
      else node[key] = value;
    }
    return node;
  }
}

/** "#RRGGBB" (colour), a number, or the typed form {"color" | "length" | "number" | "string": value}. */
export function parseToken(value: JSONValue, p: string): Token {
  if (typeof value === "number") return { type: "number", value };
  if (typeof value === "string") {
    if (!parseColor(value)) throw new Skin2Error(p, 'a short token is a colour (#RRGGBB[AA]) or a number; write {"string": …} for text');
    return { type: "color", value };
  }
  if (isObject(value)) {
    const keys = Object.keys(value);
    if (keys.length !== 1 || !TOKEN_TYPES.includes(keys[0] as TokenType)) {
      throw new Skin2Error(p, 'a typed token is {"color" | "length" | "number" | "string": value}');
    }
    const type = keys[0] as TokenType, inner = value[type];
    switch (type) {
      case "color":
        if (typeof inner !== "string" || !parseColor(inner)) throw new Skin2Error(p, "a color token is #RRGGBB or #RRGGBBAA");
        return { type, value: inner };
      case "number":
        if (typeof inner !== "number") throw new Skin2Error(p, "a number token holds a number");
        return { type, value: inner };
      case "string":
        if (typeof inner !== "string") throw new Skin2Error(p, "a string token holds a string");
        return { type, value: inner };
      case "length": {
        let length;
        try { length = parseLength(inner); } catch (e) {
          if (e instanceof LengthError) throw new Skin2Error(p, e.message);
          throw e;
        }
        if (length.op === "pt" && typeof inner === "number") return { type, value: { pt: length.value } };
        if (length.op === "frac" && typeof inner === "string") return { type, value: { frac: length.value } };
        return { type, value: inner };
      }
    }
  }
  throw new Skin2Error(p, "a token is a colour string, a number or a typed token object");
}

/** A message when `value` is not a valid argument of `type`, else undefined. */
export function typeError(value: JSONValue, type: ParamType): string | undefined {
  switch (type) {
    case "string": return typeof value === "string" ? undefined : "expected a string";
    case "number": return typeof value === "number" ? undefined : "expected a number";
    case "color": return typeof value === "string" && parseColor(value) ? undefined : "expected a colour (#RRGGBB[AA])";
    case "shape": return isObject(value) && typeof value.kind === "string" ? undefined : "expected a shape object with a kind";
    case "paint": return isObject(value) && typeof value.type === "string" ? undefined : "expected a paint object with a type";
    case "length":
      if (!isObject(value)) {
        return 'a length argument is explicit: {"pt": N}, {"frac": F} or a max/min/sum (a bare number would be ambiguous)';
      }
      try { parseLength(value); return undefined; } catch (e) { return (e as Error).message; }
  }
}

function collectIDs(v: JSONValue, ids: Set<string>): void {
  if (!isObject(v)) return;
  if (v.type !== undefined && typeof v.id === "string") ids.add(v.id);
  for (const child of Array.isArray(v.children) ? v.children : []) collectIDs(child, ids);
}

/** Prefixes inner node ids and the #id references (`to`, `target`) that point at them. */
function qualify(v: JSONValue, ids: Set<string>, prefix: string, isRoot: boolean): JSONValue {
  if (Array.isArray(v)) return v.map((x) => qualify(x, ids, prefix, false));
  if (isObject(v)) {
    const out: JSONObject = {};
    const isNode = v.type !== undefined;
    for (const [k, value] of Object.entries(v)) {
      if (k === "id" && isNode && !isRoot && typeof value === "string" && ids.has(value)) {
        out[k] = `${prefix}.${value}`;
      } else if ((k === "to" || k === "target") && typeof value === "string" && value.startsWith("#")) {
        const body = value.slice(1);
        const name = body.split("[", 1)[0];
        out[k] = ids.has(name) ? `#${prefix}.${body}` : value;
      } else {
        out[k] = qualify(value, ids, prefix, false);
      }
    }
    return out;
  }
  return v;
}

/** Layout merge on JSON, as mergeLayout does on typed values. */
export function mergeLayoutJSON(base: JSONValue, patch: JSONValue): JSONValue {
  if (!isObject(base) || !isObject(patch)) return patch;
  const out: JSONObject = { ...base };
  for (const [k, v] of Object.entries(patch)) {
    if (v === null) {
      delete out[k];
    } else if (MERGED_LAYOUT_KEYS.has(k) && isObject(out[k]) && isObject(v)) {
      const sub: JSONObject = { ...(out[k] as JSONObject) };
      for (const [sk, sv] of Object.entries(v)) {
        if (sv === null) delete sub[sk];
        else sub[sk] = sv;
      }
      out[k] = sub;
    } else {
      out[k] = v;
    }
  }
  return out;
}

/** Sets node fields from a variant patch: `layout` merges, null removes a field, anything else replaces it. */
function applyFields(fields: JSONObject, node: JSONObject): void {
  for (const [k, v] of Object.entries(fields)) {
    if (k === "layout" && node.layout !== undefined && v !== null) node.layout = mergeLayoutJSON(node.layout, v);
    else if (v === null) delete node[k];
    else node[k] = v;
  }
}

function applyVariant(name: string, variants: JSONValue, root: JSONValue): void {
  const vp = pointerAppend("/variants", name);
  const variant = isObject(variants) ? variants[name] : undefined;
  if (variant === undefined) throw new Skin2Error("/variants", `no variant named "${name}"`);
  const patches = isObject(variant) ? variant.patch ?? [] : [];
  if (!Array.isArray(patches)) throw new Skin2Error(`${vp}/patch`, "patch is an array");
  patches.forEach((patch, i) => {
    const pp = pointerAppend(`${vp}/patch`, i);
    if (!isObject(patch) || typeof patch.target !== "string" || !patch.target.startsWith("#")) {
      throw new Skin2Error(pp, 'a variant patch is {"target": "#id", …fields}');
    }
    const fields = { ...patch };
    delete fields.target;
    const id = patch.target.slice(1);
    if (!patchNode(root, id, fields)) throw new Skin2Error(`${pp}/target`, `no node with id "${id}"`);
  });
}

function patchNode(v: JSONValue, id: string, fields: JSONObject): boolean {
  if (!isObject(v)) return false;
  if (v.id === id) {
    applyFields(fields, v);
    return true;
  }
  if (!Array.isArray(v.children)) return false;
  return v.children.some((c) => patchNode(c, id, fields));
}

// ── Loading ──────────────────────────────────────────────────────────────

export interface LoadOptions {
  theme?: string;
  variant?: string;
  /** Parts the skin may `use` without defining. Defaults to STD_PARTS. */
  library?: Record<string, JSONValue>;
}

/** Loads skin.json text: parses it, expands tokens (with `theme`'s overrides), parts and `variant`'s patches,
    then decodes. */
export function loadDocument(text: string, options: LoadOptions = {}): Document {
  const bytes = utf8Length(text);
  if (bytes > MAX_FILE_BYTES) throw new Skin2Error("", `skin.json is ${bytes} bytes; the limit is ${MAX_FILE_BYTES}`);
  return loadDocumentJSON(parseJSON(text), options);
}

export function loadDocumentJSON(raw: JSONValue, options: LoadOptions = {}): Document {
  const expanded = new Preprocessor(raw, options.library).expand(options.theme, options.variant);
  const doc = decodeDocument(expanded);
  doc.theme = options.theme;
  doc.variant = options.variant;
  return doc;
}
