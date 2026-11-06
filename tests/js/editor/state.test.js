// history.js, doc.js, model.js, artwork.js, draft.js, and the open → edit → export round trip.

import { test } from "node:test";
import assert from "node:assert/strict";
import { join } from "node:path";
import { readFileSync } from "node:fs";

import { JSZip, ROOT, zipFiles } from "../skin-stack/helpers.js";
import { readSkin, readEntry, writeSkin } from "../../../docs/js/skin/zip.js";
import { patchInfo, getIn } from "../../../docs/js/skin/info.js";
import { classifyInfo, validate } from "../../../docs/js/skin/validate.js";
import { SkinDoc, exportFiles } from "../../../docs/js/editor/doc.js";
import { History, invertOps, MERGE_MS } from "../../../docs/js/editor/history.js";
import * as M from "../../../docs/js/editor/model.js";
import { assetRefs, planReplace } from "../../../docs/js/editor/artwork.js";
import { makeDraft, applyDraft, isUsableDraft } from "../../../docs/js/editor/draft.js";

const NES = join(ROOT, "fixtures", "variants", "sample-nes.deltaskin");
const TRAIT = "iphone/edgeToEdge/portrait";

async function openFixture(path = NES, mutate = null) {
  const bytes = readFileSync(path);
  const skin = await readSkin(bytes, { JSZip });
  if (mutate) mutate(skin.info);
  const doc = new SkinDoc({ info: skin.info, names: skin.entries, read: n => readEntry(skin, n), label: "fixture" });
  return { skin, doc };
}

const tiny = () => ({
  identifier: "com.example.t", name: "T", gameTypeIdentifier: "com.rileytestut.delta.game.gba",
  representations: { iphone: { standard: { portrait: {
    assets: { resizable: "art.pdf", small: "sub/Art.PDF" },
    mappingSize: { width: 100, height: 200 },
    items: [{ inputs: ["a"], frame: { x: 1, y: 2, width: 10, height: 10 } }, { inputs: { up: "up" }, frame: { x: 30, y: 30, width: 20, height: 20 }, thumbstick: { name: "stick.pdf", width: 5, height: 5 } }],
    screens: [{ inputFrame: { x: 0, y: 0, width: 240, height: 160 }, outputFrame: { x: 0, y: 0, width: 100, height: 70 } }],
  } } } },
  themes: [{ id: "dark", name: "Dark", assets: { iphone: { standard: { portrait: { resizable: "art.pdf" } } } } }],
});
const tinyDoc = (info = tiny()) => new SkinDoc({ info, names: ["info.json", "art.pdf", "sub/Art.PDF", "stick.pdf", "other.png"], read: async n => new Uint8Array([n.length]) });

// ── history ──────────────────────────────────────────────────────────────

test("invertOps restores sets, merges, removes and array removals", () => {
  const info = tiny();
  const ops = [
    { op: "set", path: ["name"], value: "New" },
    { op: "set", path: ["added"], value: 1 },
    { op: "merge", path: ["representations", "iphone", "standard", "portrait", "items", 0, "frame"], value: { x: 99 } },
    { op: "remove", path: ["representations", "iphone", "standard", "portrait", "items", 0] },
    { op: "remove", path: ["gameTypeIdentifier"] },
  ];
  const after = patchInfo(info, ops);
  assert.notDeepEqual(after, info);
  assert.deepEqual(patchInfo(after, invertOps(info, ops)), info);
});

test("undo and redo walk the steps; a new step clears redo", () => {
  const doc = tinyDoc(), h = new History(doc);
  h.run({ label: "Rename", ops: M.skinFieldOps("name", "A") });
  h.run({ label: "Move", ops: M.itemFrameOps(TRAIT.replace("edgeToEdge", "standard"), 0, { x: 5, y: 6, width: 10, height: 10 }) });
  assert.equal(h.undoLabel, "Move");
  h.undo();
  assert.deepEqual(getIn(doc.info, ["representations", "iphone", "standard", "portrait", "items", 0, "frame"]), { x: 1, y: 2, width: 10, height: 10 });
  assert.equal(doc.info.name, "A");
  h.undo();
  assert.equal(doc.info.name, "T");
  assert.equal(h.canUndo, false);
  h.redo();
  assert.equal(doc.info.name, "A");
  assert.ok(h.canRedo);
  h.run({ label: "Other", ops: M.skinFieldOps("name", "B") });
  assert.equal(h.canRedo, false);
  assert.equal(h.undo().label, "Other");
});

test("steps with one merge key inside the window undo together; later ones do not", () => {
  let t = 1000;
  const doc = tinyDoc(), h = new History(doc, { now: () => t });
  const p = "standard/portrait";
  const nudge = x => h.run({ label: "Nudge", mergeKey: "nudge:0", ops: M.itemFrameOps(`iphone/${p}`, 0, { x, y: 2, width: 10, height: 10 }) });
  nudge(2); t += 100; nudge(3); t += 100; nudge(4);
  assert.equal(h.undoStack.length, 1);
  t += MERGE_MS + 1; nudge(5);
  assert.equal(h.undoStack.length, 2);
  h.undo();
  assert.equal(getIn(doc.info, ["representations", "iphone", "standard", "portrait", "items", 0, "frame", "x"]), 4);
  h.undo();
  assert.equal(getIn(doc.info, ["representations", "iphone", "standard", "portrait", "items", 0, "frame", "x"]), 1);
  h.redo();
  assert.equal(getIn(doc.info, ["representations", "iphone", "standard", "portrait", "items", 0, "frame", "x"]), 4, "redo replays the whole burst");
});

test("the stack is bounded and tracks unsaved changes", () => {
  const doc = tinyDoc(), h = new History(doc, { limit: 3 });
  for (let i = 0; i < 6; i++) h.run({ label: `n${i}`, ops: M.skinFieldOps("name", `n${i}`) });
  assert.equal(h.undoStack.length, 3);
  assert.ok(h.dirty);
  h.markSaved();
  assert.equal(h.dirty, false);
  h.undo();
  assert.ok(h.dirty);
});

test("file changes undo and redo with their step", async () => {
  const doc = tinyDoc(), h = new History(doc);
  const bytes = new Uint8Array([1, 2, 3]);
  h.run({ label: "Replace", ops: [{ op: "set", path: ["x"], value: 1 }], files: { set: { "new.png": bytes }, remove: ["art.pdf"] } });
  assert.ok(doc.hasFile("new.png"));
  assert.ok(!doc.hasFile("art.pdf"));
  assert.deepEqual(doc.fileNames(), ["sub/Art.PDF", "stick.pdf", "other.png", "new.png"]);
  assert.deepEqual([...await doc.readFile("new.png")], [1, 2, 3]);
  h.undo();
  assert.ok(!doc.hasFile("new.png"));
  assert.ok(doc.hasFile("art.pdf"));
  assert.equal(doc.info.x, undefined);
  h.redo();
  assert.ok(doc.hasFile("new.png"));
  assert.ok(!doc.hasFile("art.pdf"));
  assert.equal(doc.info.x, 1);
});

// ── model ────────────────────────────────────────────────────────────────

test("traits come from the layouts the skin has; missing ones can be added as copies", async () => {
  const { doc } = await openFixture();
  const keys = M.listTraits(doc.info).map(t => t.key);
  assert.ok(keys.includes(TRAIT) && keys.includes("ipad/standard/landscape"));
  const missing = M.missingTraits(doc.info);
  assert.ok(missing.includes("iphone/splitView/portrait") && !missing.includes(TRAIT));
  const h = new History(doc);
  h.run({ label: "Add layout", ops: M.addLayoutOps(doc.info, TRAIT, "iphone/splitView/portrait") });
  const added = M.getLayout(doc.info, "iphone/splitView/portrait");
  assert.deepEqual(added, M.getLayout(doc.info, TRAIT));
  assert.notEqual(added, M.getLayout(doc.info, TRAIT), "a copy, not shared");
  assert.throws(() => M.addLayoutOps(doc.info, TRAIT, TRAIT), /already exists/);
});

test("adding and removing buttons", () => {
  const doc = tinyDoc(), h = new History(doc), t = "iphone/standard/portrait";
  h.run({ label: "Add", ops: M.addItemOps(doc.info, t) });
  const items = M.getLayout(doc.info, t).items;
  assert.equal(items.length, 3);
  assert.deepEqual(items[2].frame, { x: 20, y: 70, width: 60, height: 60 });
  h.run({ label: "Remove", ops: M.removeItemOps(t, 0) });
  assert.equal(M.getLayout(doc.info, t).items.length, 2);
  h.undo();
  assert.equal(M.getLayout(doc.info, t).items[0].inputs[0], "a");
});

test("inputs: array form is editable text, object form is read-only", () => {
  assert.deepEqual(M.parseInputs("a, b  c,,"), ["a", "b", "c"]);
  assert.deepEqual(M.describeInputs(["a", "b"]), { editable: true, text: "a, b" });
  assert.deepEqual(M.describeInputs({ up: "up", down: "down" }), { editable: false, text: "up: up, down: down" });
});

test("export name follows the game type; the identifier is made filename-safe", () => {
  assert.equal(M.exportFileName({ identifier: "com.x.y", gameTypeIdentifier: "com.rileytestut.delta.game.gba" }), "com.x.y.deltaskin");
  assert.equal(M.exportFileName({ identifier: "a/b c", gameTypeIdentifier: "public.aoshuang.game.jaguar" }), "a_b_c.manicskin");
  assert.equal(M.exportFileName({}), "skin.deltaskin");
});

test("a copy with the loaded identifier is flagged", () => {
  assert.match(M.identifierWarning({ identifier: "a" }, "a"), /Manic/);
  assert.equal(M.identifierWarning({ identifier: "b" }, "a"), null);
  assert.equal(M.identifierWarning({ identifier: "" }, ""), null);
});

test("iPhones are read-only; iPads, Macs and desktop WebKit are not", () => {
  assert.ok(M.isPhone("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"));
  assert.ok(!M.isPhone("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"));
  assert.ok(!M.isPhone("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15"));
  assert.ok(!M.isPhone(undefined));
});

test("artwork files: PNG and PDF pass, SVG warns, others are refused", () => {
  assert.equal(M.artworkFileProblem("a.PNG"), null);
  assert.equal(M.artworkFileProblem("a.pdf"), null);
  assert.match(M.artworkFileProblem("a.svg"), /SVG/);
  assert.match(M.artworkFileProblem("a.gif"), /PDF or PNG/);
});

// ── artwork ──────────────────────────────────────────────────────────────

test("asset references: layout assets, per-item art, thumbstick names and variant trees", () => {
  const refs = assetRefs(tiny());
  assert.deepEqual(refs.map(r => r.value), ["art.pdf", "sub/Art.PDF", "stick.pdf", "art.pdf"]);
  assert.deepEqual(refs[3].path, ["themes", 0, "assets", "iphone", "standard", "portrait", "resizable"]);
});

test("replacing artwork with the same extension keeps the name and touches no reference", () => {
  const plan = planReplace(tiny(), tinyDoc().fileNames(), "art.pdf", "my new art.PDF");
  assert.deepEqual(plan, { writeAs: "art.pdf", ops: [], remove: [] });
});

test("replacing with a different extension renames the file and every reference to it, leaving others", () => {
  const info = tiny();
  const doc = tinyDoc(info);
  const plan = planReplace(info, doc.fileNames(), "art.pdf", "art.png");
  assert.equal(plan.writeAs, "art.png");
  assert.deepEqual(plan.remove, ["art.pdf"]);
  const after = patchInfo(info, plan.ops);
  const portrait = after.representations.iphone.standard.portrait;
  assert.equal(portrait.assets.resizable, "art.png");
  assert.equal(portrait.assets.small, "sub/Art.PDF", "a different file");
  assert.equal(after.themes[0].assets.iphone.standard.portrait.resizable, "art.png", "the theme's reference moved too");
  assert.equal(portrait.items[1].thumbstick.name, "stick.pdf");
});

test("a lenient reference (case, folder, no extension) moves with the file it resolves to", () => {
  const info = tiny();
  const doc = tinyDoc(info);
  const plan = planReplace(info, doc.fileNames(), "sub/Art.PDF", "x.png");
  assert.equal(plan.writeAs, "sub/Art.png");
  assert.equal(patchInfo(info, plan.ops).representations.iphone.standard.portrait.assets.small, "sub/Art.png");
});

test("a name already taken gets a numeric suffix", () => {
  const info = tiny();
  const doc = new SkinDoc({ info, names: ["art.pdf", "art.png", "art-2.png", "sub/Art.PDF"], read: async () => null });
  const plan = planReplace(info, doc.fileNames(), "art.pdf", "x.png");
  assert.equal(plan.writeAs, "art-3.png");
  assert.equal(patchInfo(info, plan.ops).representations.iphone.standard.portrait.assets.resizable, "art-3.png");
});

// ── draft ────────────────────────────────────────────────────────────────

test("a draft carries the edited info and the changed files, and applies to a fresh document", async () => {
  const doc = tinyDoc(), h = new History(doc);
  h.run({ label: "x", ops: M.skinFieldOps("name", "Edited"), files: { set: { "n.png": new Uint8Array([9]) }, remove: ["other.png"] } });
  const draft = makeDraft({ label: "t.deltaskin", archive: new Uint8Array([1]), doc, now: 5 });
  assert.ok(isUsableDraft(draft));
  assert.equal(draft.savedAt, 5);
  const fresh = applyDraft(draft, tinyDoc());
  assert.equal(fresh.info.name, "Edited");
  assert.deepEqual(fresh.fileNames(), ["art.pdf", "sub/Art.PDF", "stick.pdf", "n.png"]);
  assert.ok(!isUsableDraft({ version: 99 }));
  assert.ok(!isUsableDraft(null));
});

// ── round trip ───────────────────────────────────────────────────────────

test("open, move one button, rename, export: only those change and unknown keys survive", async () => {
  const unknown = { keyboardOverlay: { rows: [["q", "w"]] }, haptic: { strength: 0.5 }, futureKey: [1, 2, { deep: true }] };
  const { skin, doc } = await openFixture(NES, info => {
    Object.assign(info, unknown);
    info.representations.iphone.edgeToEdge.portrait.items[0].futureItemKey = "keep";
    info.representations.iphone.edgeToEdge.portrait.items[0].frame.futureFrameKey = 7;
  });
  const before = JSON.parse(JSON.stringify(doc.info));
  const h = new History(doc);
  const frame = M.getLayout(doc.info, TRAIT).items[0].frame;
  h.run({ label: "Move", ops: M.itemFrameOps(TRAIT, 0, { ...frame, x: frame.x + 13, y: frame.y - 5 }) });
  h.run({ label: "Rename", ops: M.skinFieldOps("name", "Renamed") });

  const bytes = await writeSkin(await exportFiles(doc), doc.info, { JSZip });
  const back = await readSkin(bytes, { JSZip });

  // Exactly the move and the rename differ.
  const expected = JSON.parse(JSON.stringify(before));
  expected.name = "Renamed";
  const f0 = expected.representations.iphone.edgeToEdge.portrait.items[0].frame;
  f0.x += 13; f0.y -= 5;
  assert.deepEqual(back.info, expected);
  for (const k of Object.keys(unknown)) assert.deepEqual(back.info[k], unknown[k]);
  assert.equal(back.info.representations.iphone.edgeToEdge.portrait.items[0].futureItemKey, "keep");
  assert.equal(back.info.representations.iphone.edgeToEdge.portrait.items[0].frame.futureFrameKey, 7);

  // Every artwork file came along, and the archive validates.
  assert.deepEqual(back.entries.slice().sort(), skin.entries.slice().sort());
  const verdict = classifyInfo(back.info, back.entries);
  assert.equal(verdict.result, "ok");
  assert.ok(validate(verdict, { info: back.info, names: back.entries }).isValid);
});

test("replacing artwork in a skin exports the new bytes under the new name with the reference updated", async () => {
  const { doc } = await openFixture();
  const entry = M.getLayout(doc.info, TRAIT).assets.large;
  const plan = planReplace(doc.info, doc.fileNames(), entry, "replacement.pdf");
  assert.equal(plan.writeAs.endsWith(".pdf"), true);
  const h = new History(doc);
  h.run({ label: "Replace artwork", ops: plan.ops, files: { set: { [plan.writeAs]: new Uint8Array([37, 80, 68, 70]) }, remove: plan.remove } });
  const back = await readSkin(await writeSkin(await exportFiles(doc), doc.info, { JSZip }), { JSZip });
  const refs = assetRefs(back.info).filter(r => r.path.includes("edgeToEdge") && r.path.includes("portrait") && !r.path.includes("themes"));
  assert.ok(refs.length && refs.every(r => r.value === plan.writeAs), "every size of the layout points at the new file");
  assert.ok(back.entries.includes(plan.writeAs));
  assert.ok(!back.entries.includes(entry));
  assert.equal(classifyInfo(back.info, back.entries).result, "ok");
});
