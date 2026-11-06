/* EmuSkins — RetroArch converter page (docs/retroarch.html).

   Browser glue around docs/js/skin/retroarch-convert.js: loads the skin archive
   (dropped file, ?url=, or ?skin=<catalog id>) through the shared skin stack
   (skin/zip.js, skin/source.js), renders the artwork to PNG with skin/art.js
   (pdf.js / canvas), and zips the result with JSZip. The conversion itself
   (info.json → .cfg text + image jobs) lives in the pure module so tests can
   run it in Node. */

import * as RA from "./skin/retroarch-convert.js";
import { readSkin, readEntry, SkinReadError } from "./skin/zip.js";
import { urlSource, catalogSource, fileSource, corsFallbackText, sourceParams } from "./skin/source.js";
import { drawArtwork } from "./skin/art.js";

const $ = id => document.getElementById(id);
// Longest side of a rendered image, so RetroArch iOS never has to load a huge texture.
const MAX_IMAGE_PX = 2048;

// The Delta → RetroArch mapping table is data, shared with SkinKit's Swift port.
const inputMap = fetch("js/skin/retroarch-input-map.json").then(r => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}).catch(e => { fail(`Could not load the input mapping table: ${esc(e.message)}`); return null; });

const state = {
  skin: null,       // readSkin() result: the zip, where info.json sits, its entries
  entries: [],      // file names in the archive, relative to info.json
  info: null,       // parsed info.json
  skinLabel: "",    // what to call it in the UI
  result: null,     // RA.convert output
  rendered: [],     // [{file, blob}] for the download
  rendering: 0,     // bumps so a stale render doesn't win
};

// ── UI helpers ─────────────────────────────────────────────────────────

function show(id, text) {
  const el = $(id);
  if (text != null) el.innerHTML = text;
  el.classList.add("visible");
}
function hide(id) { $(id).classList.remove("visible"); }
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fail(msg) { hide("ra-status"); show("ra-error", msg); }

// ── Loading the archive ────────────────────────────────────────────────

async function loadArchive(data, label) {
  hide("ra-error");
  show("ra-status", `Reading ${esc(label)}…`);
  let skin;
  try {
    skin = await readSkin(data, { label });
  } catch (e) {
    if (!(e instanceof SkinReadError)) throw e;
    if (e.code === "too_large") return fail(`${esc(label)} is ${Math.round(e.size / 1048576)} MB. One skin should be well under 80 MB; this is probably a pack of skins.`);
    if (e.code === "not_zip") return fail(`${esc(label)} is not a zip archive. Skins are zip files with an info.json inside.`);
    if (e.code === "no_info_json") return fail("No info.json in the archive, so this is not a Delta or Manic skin.");
    return fail(`info.json could not be parsed: ${esc(e.message.replace(/^info\.json could not be (?:parsed|read): /, ""))}`);
  }
  state.skin = skin;
  state.entries = skin.entries;
  state.info = skin.info;
  state.skinLabel = skin.info.name || label;
  hide("ra-status");
  state.inputMap = await inputMap;
  setupOptions();
  await runConversion();
}

function downloadThenDrop(url, label) {
  const t = corsFallbackText(label);
  hide("ra-error");
  show("ra-status", `<strong>${esc(t.heading)}</strong> ${esc(t.body)} ` +
    `<a href="${esc(url)}" download>${esc(t.link)}</a> ${esc(t.after)}`);
}

/** Show what a source.js result means: load it, or say how to get the file. */
async function openSource(result) {
  if (result.ok) return loadArchive(result.data, result.label);
  if (result.reason === "not_in_catalog") return fail(`No skin with id <code>${esc(result.id)}</code> in the catalog. Drop the file above instead.`);
  if (result.reason === "http") return fail(`Download failed: HTTP ${result.status}. <a href="${esc(result.url)}" download>Try it directly</a>, then drop the file above.`);
  return downloadThenDrop(result.url, result.label);
}

async function fetchArchive(url, label) {
  hide("ra-error");
  show("ra-status", `Downloading ${esc(label || url)}…`);
  return openSource(await urlSource(url, label));
}

async function loadFromCatalog(id) {
  show("ra-status", "Looking the skin up in the catalog…");
  const result = await catalogSource(id);
  if (result.skin) $("ra-url").value = result.skin.downloadURL || "";
  return openSource(result);
}

// ── Options ────────────────────────────────────────────────────────────

function setOptions(select, values, preferred) {
  select.innerHTML = values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  select.value = values.includes(preferred) ? preferred : values[0];
}

function setupOptions() {
  const reps = RA.listRepresentations(state.info);
  if (!reps.length) {
    $("ra-options").style.display = "none";
    $("ra-result").style.display = "none";
    return fail("This skin has no layout with artwork and a mapping size, so there is nothing to convert.");
  }
  const devices = [...new Set(reps.map(r => r.device))];
  setOptions($("ra-device"), devices, "iphone");
  $("ra-device-hint").textContent = devices.some(d => d === "tv" || d === "appletv")
    ? "Which of the skin's layouts to use. TV layouts are artwork only; Apple TV plays with a controller."
    : "Which of the skin's layouts to use.";
  refreshDisplayTypes();
  const sys = RA.systemOf(state.info, state.inputMap || {});
  $("ra-skin-title").textContent = `${state.skinLabel} — ${sys}${state.info.identifier ? ` (${state.info.identifier})` : ""}`;
  $("ra-options").style.display = "";
}

function refreshDisplayTypes() {
  const reps = RA.listRepresentations(state.info).filter(r => r.device === $("ra-device").value);
  const types = [...new Set(reps.map(r => r.displayType))]
    .sort((a, b) => RA.DISPLAY_PREFERENCE.indexOf(a) - RA.DISPLAY_PREFERENCE.indexOf(b));
  setOptions($("ra-display"), types, "edgeToEdge");
  refreshAspect();
}

function refreshAspect() {
  const a = RA.screenAspectFor($("ra-device").value, $("ra-display").value);
  const sel = $("ra-aspect");
  let best = sel.options[0];
  for (const o of sel.options) if (Math.abs(parseFloat(o.value) - a) < Math.abs(parseFloat(best.value) - a)) best = o;
  sel.value = best.value;
}

$("ra-device").addEventListener("change", () => { refreshDisplayTypes(); runConversion(); });
$("ra-display").addEventListener("change", () => { refreshAspect(); runConversion(); });
$("ra-aspect").addEventListener("change", runConversion);
$("ra-scale").addEventListener("change", runConversion);

// ── Conversion + rendering ─────────────────────────────────────────────

async function runConversion() {
  if (!state.info) return;
  const map = await inputMap;
  if (!map) return;
  let result;
  try {
    result = RA.convert(state.info, {
      inputMap: map,
      device: $("ra-device").value,
      displayType: $("ra-display").value,
      screenAspect: parseFloat($("ra-aspect").value),
      entries: state.entries,
    });
  } catch (e) {
    return fail(`Conversion failed: ${esc(e.message)}`);
  }
  if (!result.cfg) {
    $("ra-result").style.display = "none";
    return fail(result.notes.map(esc).join("<br>") || "Nothing to convert.");
  }
  state.result = result;
  $("ra-result").style.display = "";
  $("ra-cfg").textContent = result.cfg;

  $("ra-layouts").innerHTML = result.layouts.map(l =>
    `${esc(l.overlayName)}: ${esc(l.displayType)} layout, ${l.mapping.width}×${l.mapping.height} points, ` +
    `${l.items} items → ${l.descs} descriptors${l.rect ? `, placed in the bottom ${(l.rect.h * 100).toFixed(0)}% of the screen` : ""}` +
    `${l.screens && !l.translucent ? ", game area made transparent" : ""}` +
    `${l.translucent ? ", translucent" : ""}`
  ).join("<br>") || "No portrait or landscape layout for this device.";

  // Mapping table
  const rows = result.descs.map(d => {
    const from = Array.isArray(d.inputs) ? d.inputs.join(" + ")
      : Object.entries(d.inputs).map(([k, v]) => `${k}: ${v}`).join(", ");
    return `<tr><td>${esc(d.overlayName)}</td><td>${esc(from)}</td><td><code>${esc(d.bind)}</code></td></tr>`;
  });
  $("ra-mapping").innerHTML = `<tr><th>Layout</th><th>Skin input</th><th>RetroArch</th></tr>${rows.join("")}`;

  if (result.unconvertible.length || result.skipped.length) {
    const seen = new Set();
    const items = result.unconvertible.filter(u => {
      const k = u.input + "|" + u.reason; if (seen.has(k)) return false; seen.add(k); return true;
    });
    const rows = result.skipped.map(s => `<li>Layout <code>${esc(s.overlayName)}</code> left out: ${esc(s.reason)}</li>`)
      .concat(items.map(u => `<li><code>${esc(u.input)}</code> (${esc(u.where)}): ${esc(u.reason)}</li>`));
    show("ra-unconvertible", `<strong>Not converted:</strong><ul>${rows.join("")}</ul>`);
  } else hide("ra-unconvertible");

  if (result.notes.length) show("ra-notes", result.notes.map(esc).join("<br>"));
  else hide("ra-notes");

  renderImages();
}

async function entryBytes(name) {
  const resolved = RA.resolveAsset(state.entries, name);
  if (!resolved) return null;
  const data = await readEntry(state.skin, resolved, "arraybuffer");
  return data ? { name: resolved, data } : null;
}

async function renderJob(job, scale) {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(job.width * scale));
  canvas.height = Math.max(1, Math.round(job.height * scale));
  const ctx = canvas.getContext("2d");
  const bytes = await entryBytes(job.asset);
  if (!bytes) throw new Error(`Artwork "${job.asset}" is not in the archive.`);
  if (job.kind === "thumbstick") {
    // The cap is drawn centred at its own size inside the hitbox, as Delta does.
    const iw = job.innerWidth * scale, ih = job.innerHeight * scale;
    await drawArtwork(ctx, bytes.data, bytes.name, (canvas.width - iw) / 2, (canvas.height - ih) / 2, iw, ih);
  } else {
    await drawArtwork(ctx, bytes.data, bytes.name, 0, 0, canvas.width, canvas.height);
    for (const r of job.clearRects) ctx.clearRect(r.x * scale, r.y * scale, r.width * scale, r.height * scale);
  }
  const blob = await new Promise(ok => canvas.toBlob(ok, "image/png"));
  return { canvas, blob };
}

async function renderImages() {
  const token = ++state.rendering;
  const result = state.result;
  let scale = parseInt($("ra-scale").value, 10) || 2;
  const longest = Math.max(...result.images.map(i => Math.max(i.width, i.height)));
  if (longest * scale > MAX_IMAGE_PX) scale = MAX_IMAGE_PX / longest;
  const wrap = $("ra-previews");
  wrap.innerHTML = "";
  hide("ra-render-error");
  $("ra-download").disabled = true;
  state.rendered = [];
  const errors = [];
  for (const job of result.images) {
    try {
      const { canvas, blob } = await renderJob(job, scale);
      if (token !== state.rendering) return;
      state.rendered.push({ file: job.file, blob });
      const fig = document.createElement("figure");
      fig.className = `ra-preview ra-preview-${job.kind}`;
      canvas.title = job.file;
      fig.appendChild(canvas);
      const cap = document.createElement("figcaption");
      cap.textContent = `${job.file} — ${canvas.width}×${canvas.height}`;
      fig.appendChild(cap);
      wrap.appendChild(fig);
    } catch (e) {
      if (token !== state.rendering) return;
      errors.push(`${job.file}: ${e.message}`);
    }
  }
  if (errors.length) show("ra-render-error", `Some artwork did not render:<br>${errors.map(esc).join("<br>")}`);
  $("ra-download").disabled = !state.rendered.length;
}

// ── Download / copy ────────────────────────────────────────────────────

$("ra-download").addEventListener("click", async () => {
  const r = state.result;
  if (!r || !state.rendered.length) return;
  const zip = new JSZip();
  const folder = zip.folder(r.name);
  folder.file(`${r.name}.cfg`, r.cfg + "\n");
  folder.file("README.txt", r.readme);
  for (const img of state.rendered) folder.file(img.file, img.blob);
  const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${r.name}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
});

$("ra-copy-cfg").addEventListener("click", async () => {
  if (!state.result) return;
  try {
    await navigator.clipboard.writeText(state.result.cfg + "\n");
    show("ra-copied");
    setTimeout(() => hide("ra-copied"), 2500);
  } catch (e) { /* clipboard blocked; the text is in the details below */ }
});

// ── Inputs: drop zone, file picker, URL, query string ──────────────────

const drop = $("ra-drop");
const fileInput = $("ra-file");
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

$("ra-fetch").addEventListener("click", () => {
  const url = $("ra-url").value.trim();
  if (url) fetchArchive(url);
});
$("ra-url").addEventListener("keydown", e => { if (e.key === "Enter") $("ra-fetch").click(); });

const params = sourceParams(location.search);
if (params.skin) loadFromCatalog(params.skin);
else if (params.url) { $("ra-url").value = params.url; fetchArchive(params.url); }
