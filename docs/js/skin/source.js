/* EmuSkins — where a skin comes from, for the shared skin stack (docs/js/skin/).

   Three ways in, shared by the editor, the converter and the merge tool:
     - a file the visitor drops or picks            fileSource(file)
     - ?skin=<catalog id>, resolved through catalog.min.json    catalogSource(id)
     - ?url=<download URL>, or a URL typed in       urlSource(url)

   Fetching by URL only works for hosts that send CORS headers: raw.githubusercontent.com
   does, GitHub release downloads, deltastyles.com and Google Drive do not.
   When a fetch cannot work or fails, the result is { ok: false, ... } with the
   download URL, and the page shows corsFallbackText(): "download it, then drop
   it here". No DOM here: pages render the results.
*/

/** github.com/<o>/<r>/raw|blob/<ref>/<path> redirects through a hop with no CORS
    header; raw.githubusercontent.com serves the same file with one. */
export function corsFriendly(url) {
  const m = url.match(/^https:\/\/github\.com\/([^/]+)\/([^/]+)\/(?:raw|blob)\/(.+)$/);
  return m ? `https://raw.githubusercontent.com/${m[1]}/${m[2]}/${m[3]}` : url;
}

/** Hosts that never send a CORS header, so a browser page can't read their
    files: GitHub release downloads (github.com and release-assets both),
    deltastyles.com and Google Drive. Checked 2026-11-04. Most catalog skins
    live on one of these, so they take the download-then-drop path. */
export function blocksCrossSite(url) {
  return /^https:\/\/github\.com\/[^/]+\/[^/]+\/releases\/download\//.test(url)
    || /^https:\/\/(www\.)?deltastyles\.com\//.test(url)
    || /^https:\/\/(drive|docs)\.google\.com\//.test(url);
}

/** What to tell the visitor when the page can't read the file itself. */
export function corsFallbackText(label) {
  return {
    heading: `Two steps for ${label || "this skin"}:`,
    body: "its host doesn't let other sites read the file, so",
    link: "download the skin",
    after: "first, then drop it above (or tap the box and pick it from Files).",
  };
}

/** A file from a drop or a picker. Returns { ok: true, data, label }. */
export function fileSource(file) {
  return { ok: true, data: file, label: file.name };
}

/**
 * Fetch a skin by URL.
 *   opts.fetch  fetch implementation (default globalThis.fetch)
 * Returns
 *   { ok: true, data: ArrayBuffer, label, url }
 *   { ok: false, reason: "blocked" | "network", url, label }   use corsFallbackText()
 *   { ok: false, reason: "http", status, url, label }          the host answered with an error
 */
export async function urlSource(url, label, opts = {}) {
  url = corsFriendly(url);
  const name = label || undefined;
  if (blocksCrossSite(url)) return { ok: false, reason: "blocked", url, label: name };
  const doFetch = opts.fetch || globalThis.fetch;
  let res;
  try {
    res = await doFetch(url, { mode: "cors" });
  } catch (e) {
    return { ok: false, reason: "network", url, label: name };
  }
  if (!res.ok) return { ok: false, reason: "http", status: res.status, url, label: name };
  return { ok: true, data: await res.arrayBuffer(), label: label || url.split("/").pop(), url };
}

/** The catalog entry with this id from catalog.min.json, or null.
    opts.fetch and opts.catalogUrl (default "catalog.min.json", relative to the page). */
export async function findCatalogSkin(id, opts = {}) {
  try {
    const res = await (opts.fetch || globalThis.fetch)(opts.catalogUrl || "catalog.min.json");
    const data = await res.json();
    return (data.skins || []).find(s => s.id === id) || null;
  } catch (e) {
    return null;
  }
}

/** Resolve ?skin=<id> and fetch it. Returns the urlSource() result, or
    { ok: false, reason: "not_in_catalog", id } when the id is unknown. */
export async function catalogSource(id, opts = {}) {
  const skin = await findCatalogSkin(id, opts);
  if (!skin) return { ok: false, reason: "not_in_catalog", id };
  const result = await urlSource(skin.downloadURL, skin.name || id, opts);
  return Object.assign(result, { skin });
}

/** The skin ?skin= / ?url= ask for in a query string: { skin, url } (strings or null). */
export function sourceParams(search) {
  const p = new URLSearchParams(search);
  return { skin: p.get("skin") || null, url: p.get("url") || null };
}
