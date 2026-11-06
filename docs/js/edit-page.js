/* EmuSkins — skin editor page (docs/edit.html).

   Browser glue around the shared skin stack (skin/: zip, info, validate, art,
   source, inputs.json) and the editor's pure modules (editor/: doc, history,
   model, geometry, snap, artwork, draft). The canvas is editor/surface.js.

   Everything happens in this page: the skin is read from a dropped file or a
   URL, edited as patches on the raw info.json (so unknown keys survive), and
   written back with zip.js. Nothing is uploaded.

   HOOK for the merge tool (SkinKit#77, docs/js/skin/merge.js): window.emuskinsEditor.openSkin({ info, files, label })
   opens a skin built in memory (files is { "relative/name": Uint8Array }), so a merge result goes through the same
   editor and download. A "Merge" mode mounts its UI in #ed-merge-slot (docs/edit.html).
*/

import { readSkin, readEntry, writeSkin, SkinReadError } from "./skin/zip.js";
import { urlSource, catalogSource, fileSource, corsFallbackText, sourceParams } from "./skin/source.js";
import { rasterize, SVG_NOTE, artKind } from "./skin/art.js";
import { knownInputs } from "./skin/info.js";
import { classifyInfo, validate, computeVariants, findAsset } from "./skin/validate.js";
import { SkinDoc, exportFiles } from "./editor/doc.js";
import { History } from "./editor/history.js";
import * as M from "./editor/model.js";
import * as G from "./editor/geometry.js";
import { snapTargets, snapMove, snapResize, SNAP_PX } from "./editor/snap.js";
import { planReplace } from "./editor/artwork.js";
import { makeDraft, applyDraft, saveDraft, loadDraft, clearDraft } from "./editor/draft.js";
import { Surface } from "./editor/surface.js";

const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  doc: null, history: null, archive: null, label: "",
  trait: null, sel: null,           // sel: { kind: "item" | "screen", index }
  zoom: "fit", snap: true, lock: true,
  readOnly: M.isPhone(navigator.userAgent),
  inputsTable: null,
  view: G.makeView({ width: 1, height: 1 }, 1),
  bg: new Map(), renderToken: 0, draftTimer: null,
};

// The input picker's table is data shared with the converter.
const inputsTable = fetch("js/skin/inputs.json").then(r => (r.ok ? r.json() : null)).catch(() => null);

// ── UI helpers ───────────────────────────────────────────────────────────

function show(id, text) {
  const el = $(id);
  if (text != null) el.innerHTML = text;
  el.classList.add("visible");
}
const hide = id => $(id).classList.remove("visible");
function fail(msg) { hide("ed-status"); show("ed-error", msg); }

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c);
  return node;
}

// ── Loading ──────────────────────────────────────────────────────────────

async function loadArchive(data, label) {
  hide("ed-error");
  show("ed-status", `Reading ${esc(label)}…`);
  let buf, skin;
  try {
    buf = new Uint8Array(data.arrayBuffer ? await data.arrayBuffer() : data);
    skin = await readSkin(buf, { label });
  } catch (e) {
    if (!(e instanceof SkinReadError)) throw e;
    if (e.code === "too_large") return fail(`${esc(label)} is ${Math.round(e.size / 1048576)} MB. One skin should be well under 80 MB; this is probably a pack of skins.`);
    if (e.code === "not_zip") return fail(`${esc(label)} is not a zip archive. Skins are zip files with an info.json inside.`);
    if (e.code === "no_info_json") return fail("No info.json in the archive, so this is not a Delta or Manic skin.");
    return fail(`info.json could not be parsed: ${esc(e.message.replace(/^info\.json could not be (?:parsed|read): /, ""))}`);
  }
  const doc = new SkinDoc({ info: skin.info, names: skin.entries, read: n => readEntry(skin, n), label });
  hide("ed-status");
  await openDoc(doc, buf);
}

function downloadThenDrop(url, label) {
  const t = corsFallbackText(label);
  hide("ed-error");
  show("ed-status", `<strong>${esc(t.heading)}</strong> ${esc(t.body)} <a href="${esc(url)}" download>${esc(t.link)}</a> ${esc(t.after)}`);
}

async function openSource(result) {
  if (result.ok) return loadArchive(result.data, result.label);
  if (result.reason === "not_in_catalog") return fail(`No skin with id <code>${esc(result.id)}</code> in the catalog. Drop the file above instead.`);
  if (result.reason === "http") return fail(`Download failed: HTTP ${result.status}. <a href="${esc(result.url)}" download>Try it directly</a>, then drop the file above.`);
  return downloadThenDrop(result.url, result.label);
}

async function fetchArchive(url, label) {
  hide("ed-error");
  show("ed-status", `Downloading ${esc(label || url)}…`);
  return openSource(await urlSource(url, label));
}

async function loadFromCatalog(id) {
  show("ed-status", "Looking the skin up in the catalog…");
  const result = await catalogSource(id);
  if (result.skin) $("ed-url").value = result.skin.downloadURL || "";
  return openSource(result);
}

/** Open a skin built in memory: { info, files: { name: bytes }, label }. The merge tool's way in. */
export async function openSkin({ info, files, label = "skin" }) {
  const doc = new SkinDoc({ info, names: Object.keys(files), read: async n => files[n] || null, label });
  return openDoc(doc, null);
}
window.emuskinsEditor = { openSkin };

async function openDoc(doc, archive) {
  S.inputsTable = await inputsTable;
  S.doc = doc;
  S.archive = archive;
  S.history = new History(doc);
  S.history.subscribe(updateToolbar);
  S.label = doc.label;
  S.sel = null;
  S.bg.clear();
  const traits = M.listTraits(doc.info);
  S.trait = (traits.find(t => t.key === "iphone/edgeToEdge/portrait") || traits[0] || {}).key || null;
  hide("ed-draft");
  $("ed-workspace").hidden = false;
  $("ed-readonly").classList.toggle("visible", S.readOnly);
  renderAll();
  $("ed-workspace").scrollIntoView({ block: "start" });
}

// ── Rendering ────────────────────────────────────────────────────────────

const layout = () => (S.doc && S.trait ? M.getLayout(S.doc.info, S.trait) : null);
const selItem = () => (S.sel && S.sel.kind === "item" ? (layout().items || [])[S.sel.index] : null);
const selScreen = () => (S.sel && S.sel.kind === "screen" ? (layout().screens || [])[S.sel.index] : null);

function renderAll() {
  const traits = M.listTraits(S.doc.info);
  if (!traits.some(t => t.key === S.trait)) { S.trait = traits[0] ? traits[0].key : null; S.sel = null; }
  const l = layout();
  if (S.sel && !(S.sel.kind === "item" ? (l.items || [])[S.sel.index] : (l.screens || [])[S.sel.index])) S.sel = null;
  renderToolbar(traits);
  renderCanvas();
  renderPanels();
}

function renderToolbar(traits) {
  const sel = $("ed-trait");
  sel.textContent = "";
  for (const t of traits) sel.append(el("option", { value: t.key, text: t.key }));
  sel.value = S.trait || "";
  updateToolbar();
}

function updateToolbar() {
  const h = S.history;
  $("ed-undo").disabled = S.readOnly || !h.canUndo;
  $("ed-redo").disabled = S.readOnly || !h.canRedo;
  $("ed-undo").title = h.canUndo ? `Undo: ${h.undoLabel}` : "";
  $("ed-redo").title = h.canRedo ? `Redo: ${h.redoLabel}` : "";
  for (const id of ["ed-add-item", "ed-add-layout", "ed-download"]) $(id).disabled = S.readOnly;
}

const itemLabel = (item, i) => {
  const d = M.describeInputs(item && item.inputs).text;
  return d || `Button ${i + 1}`;
};

function currentScale() {
  const l = layout();
  const mapping = (l && l.mappingSize) || { width: 400, height: 800 };
  if (S.zoom !== "fit") return Number(S.zoom);
  const availW = Math.max(200, $("ed-canvas-scroll").clientWidth - 24);
  const availH = Math.max(320, window.innerHeight - 200);
  return G.fitScale(mapping, availW, availH);
}

function renderCanvas() {
  const l = layout();
  if (!l) return;
  const mapping = l.mappingSize || { width: 400, height: 800 };
  const view = G.makeView(mapping, currentScale());
  S.view = view;
  const rects = [];
  (l.screens || []).forEach((s, i) => {
    if (s && s.outputFrame) rects.push({ key: `screen:${i}`, kind: "screen", index: i, label: `Screen ${i + 1}`, frame: G.normFrame(s.outputFrame), ext: null, selected: isSel("screen", i) });
  });
  (l.items || []).forEach((it, i) => {
    if (it && it.frame) rects.push({ key: `item:${i}`, kind: "item", index: i, label: itemLabel(it, i), frame: G.normFrame(it.frame), ext: G.effectiveEdges(it, l), selected: isSel("item", i) });
  });
  surface.setDisabled(S.readOnly);
  surface.render(view, rects, `Layout ${S.trait}`);
  paintBackground(l, view);
  renderInputStrip(l);
}

const isSel = (kind, index) => !!S.sel && S.sel.kind === kind && S.sel.index === index;

const BG_ORDER = ["resizable", "large", "medium", "small"];
const BG_MAX_PX = 2048;

async function paintBackground(l, view) {
  const token = ++S.renderToken;
  const canvas = $("ed-bg"), note = $("ed-art-note");
  canvas.style.width = `${view.pxWidth}px`;
  canvas.style.height = `${view.pxHeight}px`;
  const files = S.doc.fileNames();
  const assets = l.assets && typeof l.assets === "object" ? l.assets : {};
  const name = BG_ORDER.map(k => assets[k]).filter(v => typeof v === "string" && v).map(r => findAsset(files, r)).find(Boolean);
  if (!name) {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    note.textContent = "This layout names no artwork that is in the file, so it has no background.";
    return;
  }
  try {
    const mapping = l.mappingSize || { width: 400, height: 800 };
    const k = Math.min(2, BG_MAX_PX / Math.max(mapping.width, mapping.height));
    const w = Math.max(1, Math.round(mapping.width * k)), h = Math.max(1, Math.round(mapping.height * k));
    const key = `${name}@${S.doc.stamp(name)}:${w}x${h}`;
    let cached = S.bg.get(key);
    if (!cached) {
      cached = await rasterize(await S.doc.readFile(name), name, w, h);
      S.bg.set(key, cached);
    }
    if (token !== S.renderToken) return;
    canvas.width = cached.canvas.width;
    canvas.height = cached.canvas.height;
    canvas.getContext("2d").drawImage(cached.canvas, 0, 0);
    note.textContent = cached.note || (artKind(name) === "svg" ? SVG_NOTE : "");
  } catch (e) {
    if (token === S.renderToken) note.textContent = `Could not draw ${name}: ${e.message}`;
  }
}

function renderInputStrip(l) {
  const wrap = $("ed-input-wrap");
  const s = selScreen();
  if (!s || !s.inputFrame) { wrap.hidden = true; return; }
  wrap.hidden = false;
  const strip = G.inputStripSize(l.screens);
  const view = G.makeView(strip, G.fitScale(strip, 320, 240, 2));
  inputSurface.setDisabled(S.readOnly);
  inputSurface.render(view, [{ key: `input:${S.sel.index}`, kind: "screen", index: S.sel.index, label: `Screen ${S.sel.index + 1} input`, frame: G.normFrame(s.inputFrame), ext: null, selected: true }], "Screen input frame");
}

// ── Canvas interaction ───────────────────────────────────────────────────

function parseKey(key) {
  const [kind, index] = key.split(":");
  return { kind, index: Number(index) };
}

function frameOf(kind, index) {
  const l = layout();
  if (kind === "item") return G.normFrame(l.items[index].frame);
  if (kind === "screen") return G.normFrame(l.screens[index].outputFrame);
  return G.normFrame(l.screens[index].inputFrame);
}

function select(sel) {
  const same = (!sel && !S.sel) || (sel && S.sel && sel.kind === S.sel.kind && sel.index === S.sel.index);
  if (same) return;
  S.sel = sel;
  renderCanvas();
  renderPanels();
}

const mainHandlers = {
  select: key => select(key ? parseKey(key) : null),
  drag: ({ key, mode, handle, startFrame, dx, dy, shift, alt }) => {
    const { kind, index } = parseKey(key);
    const lockAspect = (kind !== "item" && S.lock) || shift;
    if (mode === "move") {
      const raw = G.moveFrame(startFrame, dx, dy);
      if (S.snap && !alt) {
        const r = snapMove(raw, snapTargets(layout(), { kind, index }), SNAP_PX / S.view.scale);
        return { frame: G.roundFrame(r.frame), guides: r.guides };
      }
      return { frame: G.roundFrame(raw), guides: null };
    }
    let frame = G.resizeFrame(startFrame, handle, dx, dy, { lockAspect });
    if (S.snap && !alt && !lockAspect) {
      const r = snapResize(frame, handle, snapTargets(layout(), { kind, index }), SNAP_PX / S.view.scale);
      return { frame: r.frame, guides: r.guides };
    }
    return { frame, guides: null };
  },
  commit: ({ key, mode, frame }) => commitFrame(parseKey(key), frame, mode === "move" ? "Move" : "Resize"),
  key: onCanvasKey,
};

const inputHandlers = {
  select: () => {},
  drag: ({ handle, startFrame, dx, dy, shift, mode }) => ({
    frame: mode === "move" ? G.roundFrame(G.moveFrame(startFrame, dx, dy)) : G.resizeFrame(startFrame, handle, dx, dy, { lockAspect: S.lock || shift }),
    guides: null,
  }),
  commit: ({ key, frame, mode }) => commitFrame(parseKey(key), frame, mode === "move" ? "Move" : "Resize"),
  key: () => {},
};

const surface = new Surface($("ed-stage"), mainHandlers);
const inputSurface = new Surface($("ed-input-stage"), inputHandlers);

/** Set a frame from the canvas or a panel. kind: "item" | "screen" | "input". */
function commitFrame({ kind, index }, frame, verb, mergeKey = null) {
  if (S.readOnly) return;
  if (G.sameFrame(frameOf(kind, index), frame)) return;
  const ops = kind === "item" ? M.itemFrameOps(S.trait, index, frame) : M.screenFrameOps(S.trait, index, kind === "screen" ? "outputFrame" : "inputFrame", frame);
  const what = kind === "item" ? "button" : kind === "screen" ? "screen" : "screen input";
  commit(`${verb} ${what}`, ops, { mergeKey });
}

function commit(label, ops, extra = {}) {
  if (S.readOnly) return;
  S.history.run({ label, ops, ...extra });
  afterChange();
}

function afterChange() {
  renderAll();
  scheduleDraft();
}

function onCanvasKey(e) {
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); return e.shiftKey ? redo() : undo(); }
  if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); return redo(); }
  if (e.key === "Escape") return select(null);
  if (S.readOnly || !S.sel) return;
  const delta = G.nudgeDelta(e.key, e.shiftKey);
  if (delta) {
    e.preventDefault();
    const kind = S.sel.kind;
    commitFrame({ kind, index: S.sel.index }, G.moveFrame(frameOf(kind, S.sel.index), delta.dx, delta.dy), "Nudge", `nudge:${kind}:${S.sel.index}`);
  } else if ((e.key === "Delete" || e.key === "Backspace") && S.sel.kind === "item") {
    e.preventDefault();
    removeSelectedItem();
  }
}

function undo() { if (!S.readOnly && S.history.undo()) afterChange(); }
function redo() { if (!S.readOnly && S.history.redo()) afterChange(); }

function removeSelectedItem() {
  if (!S.sel || S.sel.kind !== "item") return;
  const index = S.sel.index;
  S.sel = null;
  commit("Remove button", M.removeItemOps(S.trait, index));
}

// ── Panels ───────────────────────────────────────────────────────────────

function control(input, fid) {
  if (fid) input.dataset.fid = fid;
  if (S.readOnly) input.disabled = true;
  return input;
}

/** Commit from a panel field after the browser has moved focus, so the rebuild can put it back on the right field. */
const later = fn => (...args) => setTimeout(() => fn(...args), 0);

function numField(label, value, fid, onChange) {
  const input = control(el("input", { type: "number", step: "1", value: String(value ?? 0), "aria-label": label }), fid);
  input.addEventListener("change", later(() => { const n = Number(input.value); if (Number.isFinite(n)) onChange(n); }));
  return el("label", { class: "ed-num" }, el("span", { text: label }), input);
}

function textField(label, value, fid, onChange, { list = null } = {}) {
  const input = control(el("input", { type: "text", value: value ?? "", list, autocomplete: "off", "aria-label": label }), fid);
  input.addEventListener("change", later(() => onChange(input.value)));
  return el("div", { class: "form-group ed-field" }, el("label", { text: label }), input);
}

function checkField(label, checked, fid, onChange) {
  const input = control(el("input", { type: "checkbox", checked: !!checked }), fid);
  input.checked = !!checked;
  input.addEventListener("change", later(() => onChange(input.checked)));
  return el("label", { class: "ed-check ed-field" }, input, " ", label);
}

function frameFields(prefix, frame, onChange) {
  const f = G.normFrame(frame);
  const set = key => v => onChange({ ...f, [key]: v });
  return el("div", { class: "ed-numgrid" },
    numField("x", f.x, `${prefix}.x`, set("x")), numField("y", f.y, `${prefix}.y`, set("y")),
    numField("width", f.width, `${prefix}.w`, set("width")), numField("height", f.height, `${prefix}.h`, set("height")));
}

function edgeFields(prefix, edges, onChange) {
  const e = M.pickEdges(edges);
  return el("div", { class: "ed-numgrid" }, ...M.EDGE_KEYS.map(k => numField(k, e[k], `${prefix}.${k}`, v => onChange({ ...e, [k]: v }))));
}

function renderPanels() {
  const focusId = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.fid : null;
  renderSkinPanel();
  renderLayoutPanel();
  renderSelectionPanel();
  renderVariantsPanel();
  renderCheck();
  if (focusId) {
    const next = document.querySelector(`[data-fid="${focusId}"]`);
    if (next) next.focus({ preventScroll: true });
  }
}

function renderSkinPanel() {
  const info = S.doc.info;
  const table = (S.inputsTable && S.inputsTable.gameTypes) || {};
  const types = Object.keys(table);
  const gt = info.gameTypeIdentifier || "";
  const select = control(el("select", { "aria-label": "Game type" }), "skin.gameType");
  const labels = types.map(id => `${table[id].name} (${id.startsWith("public.") ? "Manic" : "Delta"})`);
  types.forEach((id, i) => {
    // Two ids can share a name (GameCube's legacy .gc spelling); tell them apart by the id's last part.
    const dup = labels.indexOf(labels[i]) !== i || labels.lastIndexOf(labels[i]) !== i;
    select.append(el("option", { value: id, text: dup ? `${labels[i]} — ${id.split(".").pop()}` : labels[i] }));
  });
  if (gt && !types.includes(gt)) select.append(el("option", { value: gt, text: gt }));
  select.value = gt;
  select.addEventListener("change", later(() => commit("Change game type", M.skinFieldOps("gameTypeIdentifier", select.value))));
  const warn = M.identifierWarning(info, S.doc.originalIdentifier);
  $("ed-p-skin").replaceChildren(
    textField("Name", info.name, "skin.name", v => commit("Rename skin", M.skinFieldOps("name", v))),
    textField("Identifier", info.identifier, "skin.identifier", v => commit("Change identifier", M.skinFieldOps("identifier", v))),
    warn ? el("p", { class: "ed-warn", id: "ed-identifier-warning", text: warn }) : null,
    el("div", { class: "form-group ed-field" }, el("label", { text: "Game type" }), select),
    checkField("Debug (draws the hit areas in the app)", info.debug, "skin.debug", v => commit("Toggle debug", M.skinFieldOps("debug", v))),
  );
}

function renderLayoutPanel() {
  const l = layout();
  const box = $("ed-p-layout");
  if (!l) { box.textContent = "This skin has no layouts."; return; }
  const m = l.mappingSize || { width: 0, height: 0 };
  const files = S.doc.fileNames();
  const assets = l.assets && typeof l.assets === "object" ? l.assets : {};
  box.replaceChildren(
    el("p", { class: "hint", text: `${S.trait}` }),
    el("div", { class: "ed-numgrid" },
      numField("mapping width", m.width, "layout.mw", v => commit("Change mapping size", [{ op: "merge", path: [...M.layoutPathOf(S.trait), "mappingSize"], value: { width: v } }])),
      numField("mapping height", m.height, "layout.mh", v => commit("Change mapping size", [{ op: "merge", path: [...M.layoutPathOf(S.trait), "mappingSize"], value: { height: v } }]))),
    el("p", { class: "ed-sub", text: "Extended edges" }),
    edgeFields("layout.ext", l.extendedEdges, v => commit("Change layout extended edges", M.layoutFieldOps(S.trait, ["extendedEdges"], v))),
    checkField("Translucent", l.translucent, "layout.translucent", v => commit("Toggle translucent", M.layoutFieldOps(S.trait, ["translucent"], v))),
    el("p", { class: "ed-sub", text: "Artwork" }),
    ...M.SIZE_KEYS.map(k => assetRow(`layout.assets.${k}`, k, assets[k], files, [...M.layoutPathOf(S.trait), "assets", k])),
  );
}

/** One artwork reference: its file name, whether the file is in the archive, and Replace artwork. */
function assetRow(fid, label, ref, files, path) {
  const found = typeof ref === "string" && ref ? findAsset(files, ref) : null;
  const input = control(el("input", { type: "text", value: ref ?? "", autocomplete: "off", "aria-label": `${label} artwork` }), fid);
  input.addEventListener("change", later(() => {
    const v = input.value.trim();
    commit("Change artwork name", [v ? { op: "set", path, value: v } : { op: "remove", path }]);
  }));
  const picker = el("input", { type: "file", accept: ".png,.pdf,.jpg,.jpeg,.svg,image/png,application/pdf,image/jpeg", hidden: true, "data-replace": label });
  picker.addEventListener("change", () => { if (picker.files[0]) replaceArtwork(picker.files[0], ref, path); });
  const btn = control(el("button", { class: "btn btn-outline btn-sm", type: "button", text: "Replace artwork", onclick: () => picker.click() }));
  return el("div", { class: "ed-asset" },
    el("label", {}, el("span", { class: "ed-asset-key", text: label }), input),
    el("span", { class: found ? "ed-asset-ok" : "ed-asset-missing", text: found ? "in file" : ref ? "missing" : "not set" }),
    btn, picker);
}

async function replaceArtwork(file, ref, path) {
  if (S.readOnly) return;
  const problem = M.artworkFileProblem(file.name);
  const ext = file.name.split(".").pop().toLowerCase();
  if (problem && ext !== "svg") { fail(esc(problem)); return; }
  hide("ed-error");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const files = S.doc.fileNames();
  const entry = typeof ref === "string" && ref ? findAsset(files, ref) : null;
  let plan, ops;
  if (entry) {
    plan = planReplace(S.doc.info, files, entry, file.name);
    ops = plan.ops;
  } else {
    // Nothing there to replace: add the file under its own name and point the reference at it.
    const taken = new Set(files.map(n => n.toLowerCase()));
    let name = file.name;
    for (let n = 2; taken.has(name.toLowerCase()); n++) name = file.name.replace(/(\.[^.]*)?$/, `-${n}$1`);
    plan = { writeAs: name, remove: [] };
    ops = [{ op: "set", path, value: name }];
  }
  commit("Replace artwork", ops, { files: { set: { [plan.writeAs]: bytes }, remove: plan.remove } });
  if (problem) show("ed-status", esc(problem));
}

function renderSelectionPanel() {
  const l = layout();
  const box = $("ed-p-sel");
  const title = $("ed-p-sel-title");
  const item = selItem(), screen = selScreen();
  const list = el("div", { class: "ed-list", role: "list", "aria-label": "Buttons and screens" },
    ...(l && l.screens || []).map((s, i) => s && s.outputFrame ? listButton("screen", i, `Screen ${i + 1}`) : null),
    ...(l && l.items || []).map((it, i) => it && it.frame ? listButton("item", i, itemLabel(it, i)) : null));

  if (item) {
    title.textContent = `Button ${S.sel.index + 1}`;
    const i = S.sel.index;
    const desc = M.describeInputs(item.inputs);
    const table = S.inputsTable || { directions: [], gameTypes: {} };
    const groups = knownInputs(table, S.doc.info.gameTypeIdentifier);
    const adder = control(el("select", { "aria-label": "Add an input" }, el("option", { value: "", text: "Add input…" }),
      ...groups.map(g => el("optgroup", { label: g.group }, ...g.inputs.map(n => el("option", { value: n, text: n }))))), "item.addinput");
    adder.addEventListener("change", later(() => {
      if (!adder.value) return;
      const cur = Array.isArray(item.inputs) ? item.inputs : [];
      if (!cur.includes(adder.value)) commit("Add input", [{ op: "set", path: [...M.layoutPathOf(S.trait), "items", i, "inputs"], value: [...cur, adder.value] }]);
    }));
    box.replaceChildren(list,
      desc.editable
        ? textField("Inputs (comma separated)", desc.text, "item.inputs", v => commit("Change inputs", [{ op: "set", path: [...M.layoutPathOf(S.trait), "items", i, "inputs"], value: M.parseInputs(v) }]))
        : el("div", { class: "form-group ed-field" }, el("label", { text: "Inputs" }), el("p", { class: "hint", text: `${desc.text} (a directional pad; kept as it is)` })),
      desc.editable ? el("div", { class: "form-group ed-field" }, adder) : null,
      el("p", { class: "ed-sub", text: "Frame" }),
      frameFields("item.frame", item.frame, f => commitFrame({ kind: "item", index: i }, f, "Edit")),
      el("p", { class: "ed-sub", text: "Extended edges" }),
      edgeFields("item.ext", G.effectiveEdges(item, l), v => commit("Change extended edges", [{ op: "set", path: [...M.layoutPathOf(S.trait), "items", i, "extendedEdges"], value: v }])),
      item.thumbstick ? thumbstickFields(item.thumbstick, i) : null,
      item.assets && typeof item.assets === "object"
        ? el("div", {}, el("p", { class: "ed-sub", text: "This button's artwork" }),
            ...Object.keys(item.assets).map(k => assetRow(`item.assets.${k}`, k, item.assets[k], S.doc.fileNames(), [...M.layoutPathOf(S.trait), "items", i, "assets", k])))
        : null,
      el("div", { class: "ed-actions" }, control(el("button", { class: "btn btn-outline btn-sm", type: "button", id: "ed-remove-item", text: "Remove button", onclick: removeSelectedItem }))));
  } else if (screen) {
    title.textContent = `Screen ${S.sel.index + 1}`;
    const i = S.sel.index;
    box.replaceChildren(list,
      el("p", { class: "ed-sub", text: "Output frame (where it is drawn)" }),
      frameFields("screen.out", screen.outputFrame, f => commitFrame({ kind: "screen", index: i }, f, "Edit")),
      screen.inputFrame ? el("div", {}, el("p", { class: "ed-sub", text: "Input frame (the part of the picture it shows)" }),
        frameFields("screen.in", screen.inputFrame, f => commitFrame({ kind: "input", index: i }, f, "Edit"))) : null);
  } else {
    title.textContent = "Selection";
    box.replaceChildren(list, el("p", { class: "hint", text: "Select a button or a screen on the canvas, or from the list." }));
  }
}

function thumbstickFields(ts, i) {
  const base = [...M.layoutPathOf(S.trait), "items", i, "thumbstick"];
  return el("div", {},
    el("p", { class: "ed-sub", text: "Thumbstick" }),
    assetRow("item.thumbstick.name", "image", ts.name, S.doc.fileNames(), [...base, "name"]),
    el("div", { class: "ed-numgrid" },
      numField("width", ts.width ?? 0, "item.thumbstick.w", v => commit("Change thumbstick size", [{ op: "set", path: [...base, "width"], value: v }])),
      numField("height", ts.height ?? 0, "item.thumbstick.h", v => commit("Change thumbstick size", [{ op: "set", path: [...base, "height"], value: v }]))));
}

function listButton(kind, index, label) {
  const b = el("button", { class: `ed-listbtn${isSel(kind, index) ? " active" : ""}`, type: "button", role: "listitem", text: label, "data-list": `${kind}:${index}`,
    onclick: () => { select({ kind, index }); surface.focus(); } });
  return b;
}

function renderVariantsPanel() {
  const variants = computeVariants(S.doc.info);
  $("ed-p-variants").replaceChildren(
    variants.length
      ? el("ul", { class: "ed-vlist" }, ...variants.map(v => el("li", { text: `${v.kind}: ${v.label}` })))
      : el("p", { class: "hint", text: "This skin has no themes, alternate layout or per-game layouts." }),
    el("p", { class: "hint", text: "Listed only: they are written back as they were. The merge tool creates them." }));
}

// ── Check (validation) ───────────────────────────────────────────────────

function runValidation() {
  const names = ["info.json", ...S.doc.fileNames()];
  const verdict = classifyInfo(S.doc.info, names);
  const result = validate(verdict, { info: S.doc.info, names });
  const warn = M.identifierWarning(S.doc.info, S.doc.originalIdentifier);
  if (warn) result.findings.push({ severity: "warning", title: "Identifier unchanged", detail: warn, suggestion: null });
  return result;
}

function renderCheck() {
  const r = runValidation();
  const errors = r.errors.length, warnings = r.warnings.length + (M.identifierWarning(S.doc.info, S.doc.originalIdentifier) ? 1 : 0);
  $("ed-p-check-title").textContent = errors ? `Check — ${errors} error${errors === 1 ? "" : "s"}` : warnings ? `Check — ${warnings} warning${warnings === 1 ? "" : "s"}` : "Check — ok";
  $("ed-p-check").replaceChildren(el("ul", { class: "ed-findings", "data-errors": String(errors) },
    ...r.findings.map(f => el("li", { class: `ed-finding ed-${f.severity}` },
      el("strong", { text: f.title }), " ", el("span", { text: f.detail }), f.suggestion ? el("em", { text: ` ${f.suggestion}` }) : null))));
  $("ed-download-anyway").hidden = !(S.pendingForce && errors);
  if (!errors) S.pendingForce = false;
}

// ── Download ─────────────────────────────────────────────────────────────

async function download(force = false) {
  const r = runValidation();
  if (r.errors.length && !force) {
    S.pendingForce = true;
    renderCheck();
    $("ed-p-check").closest("details").open = true;
    $("ed-p-check").scrollIntoView({ block: "nearest" });
    return;
  }
  const blob = await writeSkin(await exportFiles(S.doc), S.doc.info, { type: "blob" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = M.exportFileName(S.doc.info);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  S.history.markSaved();
}

// ── Draft ────────────────────────────────────────────────────────────────

function scheduleDraft() {
  if (!S.archive || S.readOnly) return;
  clearTimeout(S.draftTimer);
  S.draftTimer = setTimeout(() => {
    saveDraft(makeDraft({ label: S.label, archive: S.archive, doc: S.doc })).then(ok => { document.body.dataset.draftSaved = ok ? String(Date.now()) : ""; });
  }, 600);
}

async function offerDraft() {
  const draft = await loadDraft();
  if (!draft || S.doc) return;
  $("ed-draft-text").textContent = `A draft of ${draft.label || "a skin"} from ${new Date(draft.savedAt).toLocaleString()} is saved in this browser.`;
  show("ed-draft");
  $("ed-draft-restore").onclick = async () => {
    try {
      const skin = await readSkin(draft.archive, { label: draft.label });
      const doc = new SkinDoc({ info: skin.info, names: skin.entries, read: n => readEntry(skin, n), label: draft.label });
      applyDraft(draft, doc);
      await openDoc(doc, draft.archive);
      S.history.dirty = true;
    } catch (e) {
      fail(`The saved draft could not be restored: ${esc(e.message)}`);
    }
  };
  $("ed-draft-discard").onclick = async () => { await clearDraft(); hide("ed-draft"); };
}

// ── Toolbar and source wiring ────────────────────────────────────────────

$("ed-trait").addEventListener("change", e => { S.trait = e.target.value; S.sel = null; renderAll(); });
$("ed-zoom").addEventListener("change", e => { S.zoom = e.target.value; renderCanvas(); });
$("ed-snap").addEventListener("change", e => { S.snap = e.target.checked; });
$("ed-lock").addEventListener("change", e => { S.lock = e.target.checked; });
$("ed-undo").addEventListener("click", undo);
$("ed-redo").addEventListener("click", redo);
$("ed-add-item").addEventListener("click", () => {
  const before = (layout().items || []).length;
  commit("Add button", M.addItemOps(S.doc.info, S.trait));
  select({ kind: "item", index: before });
});
$("ed-download").addEventListener("click", () => download(false));
$("ed-download-anyway").addEventListener("click", () => download(true));

$("ed-add-layout").addEventListener("click", () => {
  const missing = M.missingTraits(S.doc.info);
  const box = $("ed-addlayout-box");
  if (!missing.length) { show("ed-status", "This skin already has a layout for every device, display type and orientation."); return; }
  $("ed-addlayout-key").replaceChildren(...missing.map(k => el("option", { value: k, text: k })));
  box.hidden = !box.hidden;
});
$("ed-addlayout-cancel").addEventListener("click", () => { $("ed-addlayout-box").hidden = true; });
$("ed-addlayout-go").addEventListener("click", () => {
  const to = $("ed-addlayout-key").value;
  if (!to) return;
  commit("Add layout", M.addLayoutOps(S.doc.info, S.trait, to));
  S.trait = to;
  $("ed-addlayout-box").hidden = true;
  renderAll();
});

let resizeTimer = null;
window.addEventListener("resize", () => {
  if (!S.doc || S.zoom !== "fit") return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderCanvas, 120);
});

const drop = $("ed-drop");
const fileInput = $("ed-file");
drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
const openFile = f => { const s = fileSource(f); loadArchive(s.data, s.label); };
fileInput.addEventListener("change", () => { if (fileInput.files[0]) openFile(fileInput.files[0]); });
for (const ev of ["dragenter", "dragover"]) drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); });
for (const ev of ["dragleave", "drop"]) drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); });
drop.addEventListener("drop", e => {
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) openFile(f);
});

$("ed-fetch").addEventListener("click", () => {
  const url = $("ed-url").value.trim();
  if (url) fetchArchive(url);
});
$("ed-url").addEventListener("keydown", e => { if (e.key === "Enter") $("ed-fetch").click(); });

const params = sourceParams(location.search);
if (params.skin) loadFromCatalog(params.skin);
else if (params.url) { $("ed-url").value = params.url; fetchArchive(params.url); }
else offerDraft();
