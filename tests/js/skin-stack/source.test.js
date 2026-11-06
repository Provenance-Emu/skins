// source.js: which hosts the page can read, the catalog lookup, and every way a fetch can fail.

import { test } from "node:test";
import assert from "node:assert/strict";

import { corsFriendly, blocksCrossSite, corsFallbackText, urlSource, findCatalogSkin, catalogSource, fileSource, sourceParams } from "../../../docs/js/skin/source.js";
import { art } from "./art-import.js";

const bytes = new Uint8Array([80, 75, 3, 4]);
const okFetch = calls => async (url, opts) => { calls.push([url, opts]); return { ok: true, status: 200, arrayBuffer: async () => bytes.buffer }; };
const catalog = { skins: [{ id: "open", name: "Open host", downloadURL: "https://skins.test.invalid/flow.deltaskin" }, { id: "blocked", name: "Blocked", downloadURL: "https://deltastyles.com/files/skins/1/flow.deltaskin" }] };
const catalogFetch = async url => { assert.equal(url, "catalog.min.json"); return { ok: true, json: async () => catalog }; };

test("github blob and raw links go through raw.githubusercontent.com, which sends CORS headers", () => {
  assert.equal(corsFriendly("https://github.com/o/r/raw/main/x/y.deltaskin"), "https://raw.githubusercontent.com/o/r/main/x/y.deltaskin");
  assert.equal(corsFriendly("https://github.com/o/r/blob/main/y.deltaskin"), "https://raw.githubusercontent.com/o/r/main/y.deltaskin");
  assert.equal(corsFriendly("https://example.com/y.deltaskin"), "https://example.com/y.deltaskin");
});

test("hosts that never send CORS headers are recognised", () => {
  for (const url of ["https://github.com/o/r/releases/download/v1/a.deltaskin", "https://deltastyles.com/x", "https://www.deltastyles.com/x",
    "https://drive.google.com/uc?id=1", "https://docs.google.com/x"]) assert.equal(blocksCrossSite(url), true, url);
  for (const url of ["https://raw.githubusercontent.com/o/r/main/a.deltaskin", "https://example.com/a.deltaskin", "https://github.com/o/r"]) assert.equal(blocksCrossSite(url), false, url);
});

test("a blocked host is not fetched; the result names the download URL", async () => {
  const calls = [];
  const r = await urlSource("https://deltastyles.com/files/a.deltaskin", "Blocked one", { fetch: okFetch(calls) });
  assert.deepEqual(r, { ok: false, reason: "blocked", url: "https://deltastyles.com/files/a.deltaskin", label: "Blocked one" });
  assert.equal(calls.length, 0);
  assert.equal(corsFallbackText("Blocked one").heading, "Two steps for Blocked one:");
  assert.equal(corsFallbackText().heading, "Two steps for this skin:");
});

test("an open host is fetched with CORS and returns the bytes and a label", async () => {
  const calls = [];
  const r = await urlSource("https://github.com/o/r/blob/main/dir/Skin.deltaskin", undefined, { fetch: okFetch(calls) });
  assert.equal(r.ok, true);
  assert.equal(r.label, "Skin.deltaskin");
  assert.deepEqual([...new Uint8Array(r.data)], [...bytes]);
  assert.deepEqual(calls, [["https://raw.githubusercontent.com/o/r/main/dir/Skin.deltaskin", { mode: "cors" }]]);
});

test("a network failure and an HTTP error are different results", async () => {
  const net = await urlSource("https://example.com/a.deltaskin", "A", { fetch: async () => { throw new TypeError("Failed to fetch"); } });
  assert.deepEqual(net, { ok: false, reason: "network", url: "https://example.com/a.deltaskin", label: "A" });
  const http = await urlSource("https://example.com/a.deltaskin", "A", { fetch: async () => ({ ok: false, status: 404 }) });
  assert.deepEqual(http, { ok: false, reason: "http", status: 404, url: "https://example.com/a.deltaskin", label: "A" });
});

test("the catalog lookup finds a skin by id, and a catalog id on an open host fetches it", async () => {
  assert.equal((await findCatalogSkin("open", { fetch: catalogFetch })).name, "Open host");
  assert.equal(await findCatalogSkin("nope", { fetch: catalogFetch }), null);
  assert.equal(await findCatalogSkin("open", { fetch: async () => { throw new Error("offline"); } }), null);
  const calls = [];
  const fetch = async (url, opts) => (url === "catalog.min.json" ? catalogFetch(url) : okFetch(calls)(url, opts));
  const r = await catalogSource("open", { fetch });
  assert.equal(r.ok, true);
  assert.equal(r.skin.id, "open");
  assert.equal(r.label, "Open host");
  assert.equal(calls[0][0], "https://skins.test.invalid/flow.deltaskin");
  assert.equal((await catalogSource("blocked", { fetch })).reason, "blocked");
  assert.deepEqual(await catalogSource("nope", { fetch }), { ok: false, reason: "not_in_catalog", id: "nope" });
});

test("files and query strings", () => {
  const file = { name: "Mine.deltaskin", size: 4 };
  assert.deepEqual(fileSource(file), { ok: true, data: file, label: "Mine.deltaskin" });
  assert.deepEqual(sourceParams("?skin=abc&url=x"), { skin: "abc", url: "x" });
  assert.deepEqual(sourceParams(""), { skin: null, url: null });
});

test("art.js imports in Node and classifies artwork by extension", () => {
  assert.equal(art.artKind("a.PDF"), "pdf");
  assert.equal(art.artKind("dir/a.svg"), "svg");
  assert.equal(art.artKind("a.png"), "raster");
  assert.equal(art.artKind("noext"), "raster");
  assert.match(art.SVG_NOTE, /SVG/);
});
