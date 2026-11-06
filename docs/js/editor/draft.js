/* EmuSkins — the editor's draft (docs/js/editor/).

   One draft is kept in IndexedDB so a reload or a closed tab does not lose
   work: the archive as it was opened, the current info.json, and the files the
   editor changed. The page offers to restore it; it never restores on its own.

   makeDraft() and applyDraft() are pure (Node tests use them); the IndexedDB
   functions are guarded, because storage is missing or throws in private
   windows and some embedded browsers, and the editor works without it.
*/

export const DRAFT_VERSION = 1;
const DB_NAME = "emuskins-editor";
const STORE = "drafts";
const KEY = "current";

/** What to store. `archive` is the bytes of the file as opened; `source` says where it came from
    ("skin:<id>" or "url:<url>" for a source link, null for a dropped file) so a visit through the same
    link is offered this draft. */
export function makeDraft({ label, source = null, archive, doc, now = Date.now() }) {
  return {
    version: DRAFT_VERSION,
    savedAt: now,
    label,
    source,
    archive,
    info: doc.info,
    originalIdentifier: doc.originalIdentifier,
    overrides: [...doc.overrides.entries()],
  };
}

/** Put a stored draft's edits on a document built from the draft's own archive. */
export function applyDraft(draft, doc) {
  doc.info = draft.info;
  doc.originalIdentifier = draft.originalIdentifier;
  for (const [name, value] of draft.overrides) doc.applyFiles(value === null ? { remove: [name] } : { set: { [name]: value } });
  return doc;
}

export const isUsableDraft = d => !!d && d.version === DRAFT_VERSION && d.archive && d.info && Array.isArray(d.overrides);

// ── IndexedDB ────────────────────────────────────────────────────────────

function open() {
  return new Promise((ok, err) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => ok(req.result);
    req.onerror = () => err(req.error);
  });
}

async function withStore(mode, fn) {
  const db = await open();
  try {
    return await new Promise((ok, err) => {
      const tx = db.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => ok(req ? req.result : undefined);
      tx.onerror = tx.onabort = () => err(tx.error);
    });
  } finally { db.close(); }
}

/** Store the draft. Resolves false when storage is unavailable. */
export async function saveDraft(draft) {
  try { await withStore("readwrite", s => s.put(draft, KEY)); return true; } catch (e) { return false; }
}

/** The stored draft, or null (none, unusable, or storage unavailable). */
export async function loadDraft() {
  try {
    const d = await withStore("readonly", s => s.get(KEY));
    return isUsableDraft(d) ? d : null;
  } catch (e) { return null; }
}

export async function clearDraft() {
  try { await withStore("readwrite", s => s.delete(KEY)); } catch (e) { /* nothing to clear */ }
}
