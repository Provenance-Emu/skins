/* EmuSkins — undo/redo for the skin editor (docs/js/editor/).

   A plain command stack over a SkinDoc. A command is a list of patchInfo ops
   (the forward direction) and optionally file changes; running it records the
   ops that undo it, taken from the document at that moment, so the stack stays
   small however large info.json is.

   Edits that belong together count as one step: the page runs one command per
   drag (pointerup), and a command with a `mergeKey` joins the one on top of the
   stack when it has the same key and arrives within MERGE_MS (held arrow keys,
   typing in a field), so a burst of nudges undoes in one step.
*/

import { patchInfo, getIn, cloneInfo } from "../skin/info.js";

export const MERGE_MS = 700;
export const DEFAULT_LIMIT = 100;

/**
 * The ops that undo `ops` when applied to the result of applying them to `info`.
 * Each op is inverted against the state just before it, and the list comes back
 * in reverse order. Removing an array element restores the whole array.
 */
export function invertOps(info, ops) {
  const inverse = [];
  let cur = info;
  for (const op of ops) {
    const parentPath = op.path.slice(0, -1);
    const parent = parentPath.length ? getIn(cur, parentPath) : cur;
    if (op.op === "remove" && Array.isArray(parent)) {
      inverse.unshift({ op: "set", path: parentPath, value: cloneInfo(parent) });
    } else {
      const prev = getIn(cur, op.path);
      inverse.unshift(prev === undefined ? { op: "remove", path: op.path } : { op: "set", path: op.path, value: cloneInfo(prev) });
    }
    cur = patchInfo(cur, [op]);
  }
  return inverse;
}

export class History {
  constructor(doc, { limit = DEFAULT_LIMIT, now = () => Date.now() } = {}) {
    this.doc = doc;
    this.limit = limit;
    this.now = now;
    this.undoStack = [];
    this.redoStack = [];
    this.listeners = new Set();
    this.dirty = false;
  }

  get canUndo() { return this.undoStack.length > 0; }
  get canRedo() { return this.redoStack.length > 0; }
  get undoLabel() { return this.canUndo ? this.undoStack[this.undoStack.length - 1].label : ""; }
  get redoLabel() { return this.canRedo ? this.redoStack[this.redoStack.length - 1].label : ""; }

  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  notify() { for (const fn of this.listeners) fn(this); }

  markSaved() { this.dirty = false; this.notify(); }

  /**
   * Run a command.
   *   label     what the step is called ("Move button")
   *   ops       patchInfo ops
   *   files     { set: {name: bytes}, remove: [names] } file changes that go with the ops
   *   mergeKey  join the step on top when it has this key and is recent
   */
  run({ label, ops = [], files = null, mergeKey = null }) {
    const doc = this.doc;
    const undoOps = invertOps(doc.info, ops);
    const previousFiles = files ? doc.applyFiles(files) : new Map();
    doc.info = patchInfo(doc.info, ops);
    this.redoStack = [];
    this.dirty = true;

    const top = this.undoStack[this.undoStack.length - 1];
    if (mergeKey && top && top.mergeKey === mergeKey && this.now() - top.at < MERGE_MS && !files && !top.files) {
      top.ops = top.ops.concat(ops);
      top.at = this.now();
    } else {
      this.undoStack.push({ label, ops, files, mergeKey, undoOps, previousFiles, at: this.now() });
      if (this.undoStack.length > this.limit) this.undoStack.shift();
    }
    this.notify();
    return true;
  }

  undo() {
    const cmd = this.undoStack.pop();
    if (!cmd) return null;
    const doc = this.doc;
    // Merged steps: undoOps of the first step covers the whole burst, because later ops
    // only touched paths the first one already recorded.
    doc.info = patchInfo(doc.info, cmd.undoOps);
    if (cmd.files) {
      cmd.redoFiles = new Map([...cmd.previousFiles.keys()].map(n => [n, doc.overrides.has(n) ? doc.overrides.get(n) : undefined]));
      doc.restoreOverrides(cmd.previousFiles);
    }
    this.redoStack.push(cmd);
    this.dirty = true;
    this.notify();
    return cmd;
  }

  redo() {
    const cmd = this.redoStack.pop();
    if (!cmd) return null;
    const doc = this.doc;
    doc.info = patchInfo(doc.info, cmd.ops);
    if (cmd.files) doc.restoreOverrides(cmd.redoFiles);
    this.undoStack.push(cmd);
    this.dirty = true;
    this.notify();
    return cmd;
  }
}
