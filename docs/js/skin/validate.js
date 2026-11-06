/* EmuSkins — skin validation of the shared skin stack (docs/js/skin/).

   Two layers, both pure (no DOM, no network, no zip library):

   classifyArchive()  a port of scripts/link_health.py's classify_archive,
                      _has_artwork and find_asset, with the same verdicts
                      ("ok", "no_info_json", "missing_artwork", ...) and the
                      same extra fields, so the editor shows before export what
                      the catalog's health check would say afterwards.
                      tests/fixtures/skin-stack/validate-cases.json holds the
                      expected verdicts; tests/test_skin_stack_validate.py
                      checks link_health.py against it and
                      tests/js/skin-stack/validate.test.js checks this file.

   validate()         the same verdict as a list of findings (error / warning /
                      info, each with an actionable suggestion), in the shape
                      of SkinKitCore's DeltaSkinValidator, for display.

   Known difference from link_health.py: when info.json does not parse as plain
   JSON, link_health.py strips everything after `//` on a line (even inside a
   string) and retries; parseInfo() here keeps `//` inside strings. The two
   agree on every skin whose info.json parses either way.
*/

import { parseInfo, listLayouts } from "./info.js";

export const REQUIRED_INFO_KEYS = ["identifier", "name", "gameTypeIdentifier", "representations"];
export const SKIN_EXTS = [".deltaskin", ".manicskin"];
export const ASSET_SIZE_KEYS = ["resizable", "large", "medium", "small"];
export const ALT_KEY = "alt";
export const ALT_LABEL = "Alternate layout";

const isObject = v => v !== null && typeof v === "object" && !Array.isArray(v);
const nonEmptyString = v => typeof v === "string" && v !== "";

// ── Assets ───────────────────────────────────────────────────────────────

/** Find artwork the way the apps do (Archive.entry(matchingAssetNamed:) in
    DeltaSkin.swift): exact path, then the same file name anywhere in the
    archive ignoring case, then the same stem as .pdf, .png or .svg. Returns
    the archive's own spelling of the path, or null. */
export function findAsset(files, filename) {
  if (!filename) return null;
  if (files.includes(filename)) return filename;
  const baseName = f => f.slice(f.lastIndexOf("/") + 1).toLowerCase();
  const wanted = baseName(filename);
  if (!wanted) return null;
  const byName = new Map();
  for (const f of files) {
    const b = baseName(f);
    if (!byName.has(b)) byName.set(b, f);
  }
  if (byName.has(wanted)) return byName.get(wanted);
  const dot = wanted.lastIndexOf(".");
  const stem = dot >= 0 ? wanted.slice(0, dot) : wanted;
  for (const ext of ["pdf", "png", "svg"]) {
    const candidate = `${stem}.${ext}`;
    if (candidate !== wanted && byName.has(candidate)) return byName.get(candidate);
  }
  return null;
}

/** The app tries resizable, large, medium, small and uses the first it finds. */
export function hasArtwork(files, assets) {
  const names = ASSET_SIZE_KEYS.map(k => assets[k]).filter(nonEmptyString);
  return names.some(n => findAsset(files, n));
}

/** Skins packed inside an archive: files, or folders (`X.deltaskin/`). */
export function innerSkinPaths(names) {
  const out = [];
  for (const n of names) {
    if (SKIN_EXTS.some(ext => n.toLowerCase().endsWith(ext))) { out.push(n); continue; }
    const m = n.match(/^(.*?\.(?:deltaskin|manicskin)\/)/i);
    if (m && !out.includes(m[1])) out.push(m[1]);
  }
  return out;
}

export const isJunk = name => name.startsWith("__MACOSX/") || name.slice(name.lastIndexOf("/") + 1) === ".DS_Store";

// ── Layouts ──────────────────────────────────────────────────────────────

/** [label, assets] for every base layout; label is "iphone/edgeToEdge/portrait",
    assets {} when the layout omits it or it is not an object. */
export function baseLayouts(representations) {
  return listLayouts(representations).map(({ path, layout }) =>
    [path.join("/"), isObject(layout.assets) ? layout.assets : {}]);
}

/** [label, assets, strict] for every variant layout in an info.json. Labels
    carry the variant: "alt:iphone/standard/portrait", "theme:dark:iphone/standard/portrait",
    "game:Doom:iphone/standard/portrait". `alt` and `game` hold whole
    representations, checked like base layouts (strict: a layout naming no
    artwork is a gap). A theme holds artwork only and may override just some
    layouts, so one that names no files is not a gap. */
export function variantLayouts(info) {
  const out = [];
  for (const [name, assets] of baseLayouts(info.altRepresentations)) out.push([`alt:${name}`, assets, true]);

  if (Array.isArray(info.themes)) {
    for (const theme of info.themes) {
      if (!isObject(theme) || !isObject(theme.assets)) continue;
      for (const [device, displays] of Object.entries(theme.assets)) {
        if (!isObject(displays)) continue;
        for (const [display, orientations] of Object.entries(displays)) {
          if (!isObject(orientations)) continue;
          for (const [orientation, assets] of Object.entries(orientations)) {
            if (isObject(assets)) out.push([`theme:${pyStr(theme.id)}:${device}/${display}/${orientation}`, assets, false]);
          }
        }
      }
    }
  }

  if (isObject(info.gameOverrides)) {
    for (const [game, representations] of Object.entries(info.gameOverrides)) {
      for (const [name, assets] of baseLayouts(representations)) out.push([`game:${game}:${name}`, assets, true]);
    }
  }
  return out;
}

// link_health.py formats a missing theme id as Python's str(None).
const pyStr = v => (v === undefined || v === null ? "None" : String(v));

function variantHasArtwork(files, assets, strict) {
  if (!strict && !ASSET_SIZE_KEYS.some(k => nonEmptyString(assets[k]))) return true;
  return hasArtwork(files, assets);
}

/** The variants an info.json carries, in a stable order: the alt layout, then
    themes, then per-game overrides (variants_sidecar.py compute_variants). */
export function computeVariants(info) {
  if (!isObject(info)) return [];
  const out = [], seen = new Set();
  const add = (kind, key, label) => {
    key = typeof key === "string" ? key.trim() : "";
    if (!key || seen.has(`${kind}\0${key}`)) return;
    seen.add(`${kind}\0${key}`);
    label = typeof label === "string" ? label.trim() : "";
    out.push({ kind, key, label: label || key });
  };
  if (isObject(info.altRepresentations) && Object.keys(info.altRepresentations).length) add("alt", ALT_KEY, ALT_LABEL);
  if (Array.isArray(info.themes)) for (const t of info.themes) if (isObject(t)) add("theme", t.id, t.name);
  if (isObject(info.gameOverrides)) for (const g of Object.keys(info.gameOverrides)) add("game", g, g);
  return out;
}

// ── Classification (link_health.py classify_archive) ─────────────────────

/** Classify an archive from its entry names and a reader for its root info.json.
 *    names          every entry name in the archive, directories included (zip order)
 *    readInfoText   () => the root info.json as text; only called when it exists
 *  Returns { result, ... } exactly as link_health.classify_archive does:
 *    no_info_json (sample) · nested_folder (inner) · pack (inner) · bad_info_json (error)
 *    info_missing_keys (missing, variants) · missing_artwork (layouts, variants)
 *    ok (variants, and partialArtwork + layoutCount when some layout has none). */
export function classifyArchive(names, readInfoText) {
  const visible = names.filter(n => !isJunk(n));
  if (!visible.includes("info.json")) {
    const inner = innerSkinPaths(visible);
    if (inner.length) return { result: "pack", inner };
    const nested = visible.filter(n => n.endsWith("/info.json"));
    if (nested.length) return { result: "nested_folder", inner: nested.slice(0, 5) };
    return { result: "no_info_json", sample: visible.slice(0, 8) };
  }

  let info;
  try {
    info = parseInfo(readInfoText());
  } catch (e) {
    return { result: "bad_info_json", error: String(e.message || e).slice(0, 200) };
  }
  if (!isObject(info)) return { result: "bad_info_json", error: "info.json is not an object" };
  return classifyInfo(info, names);
}

/** The verdict for an info.json that parsed, given every entry name in the archive. */
export function classifyInfo(info, names) {
  const variants = computeVariants(info);
  const missing = REQUIRED_INFO_KEYS.filter(k => !Object.prototype.hasOwnProperty.call(info, k));
  if (missing.length) return { result: "info_missing_keys", missing, variants };

  const layouts = baseLayouts(info.representations);
  const files = names.filter(n => !n.endsWith("/"));
  let broken = layouts.filter(([, assets]) => !hasArtwork(files, assets)).map(([name]) => name);
  if (broken.length && broken.length === layouts.length) return { result: "missing_artwork", layouts: broken, variants };
  // Variant artwork never hides a skin; its gaps join the partial list.
  const variantList = variantLayouts(info);
  broken = broken.concat(variantList.filter(([, assets, strict]) => !variantHasArtwork(files, assets, strict)).map(([name]) => name));
  if (broken.length) {
    // Still installs and works in its other layouts, so it stays listed.
    return { result: "ok", partialArtwork: broken, layoutCount: layouts.length + variantList.length, variants };
  }
  return { result: "ok", variants };
}

// ── Findings (DeltaSkinValidator's shape) ────────────────────────────────

const finding = (severity, title, detail, suggestion = null) => ({ severity, title, detail, suggestion });

/** Turn a classifyArchive() verdict into findings for display.
 *    verdict  the classifyArchive() result
 *    info     the parsed info.json when there is one (adds checks the verdict skips)
 *    names    the archive's entry names (adds per-size artwork checks)
 *  Returns { result, findings, errors, warnings, isValid }. Like the Swift
 *  validator, isValid means no error-level finding. An "ok" verdict with
 *  partialArtwork is valid but warns: the skin installs, and some layouts draw nothing. */
export function validate(verdict, { info = null, names = null } = {}) {
  const findings = [];
  switch (verdict.result) {
    case "not_zip":
    case "bad_zip":
      findings.push(finding("error", "Invalid archive", "The file is not a valid ZIP archive or is corrupted.",
        "Re-download or re-create the skin file."));
      break;
    case "no_info_json":
      findings.push(finding("error", "Missing info.json", "The skin archive must contain an info.json file at the root level.",
        "Add info.json with required fields: identifier, name, gameTypeIdentifier, representations."));
      break;
    case "nested_folder":
      findings.push(finding("error", "info.json is inside a folder",
        `Found ${verdict.inner.join(", ")}. The apps look for info.json at the root of the archive.`,
        "Zip the skin's files themselves, not the folder that holds them."));
      break;
    case "pack":
      findings.push(finding("error", "Archive holds other skins",
        `Found ${verdict.inner.join(", ")} inside, but no info.json at the root.`,
        "Extract each skin and use it on its own."));
      break;
    case "bad_info_json":
      findings.push(finding("error", "Invalid JSON in info.json", `info.json could not be parsed: ${verdict.error}`,
        "Validate your JSON using a linter such as jsonlint.com."));
      break;
    case "info_missing_keys":
      for (const k of verdict.missing) {
        findings.push(finding("error", `Missing required field: ${k}`, `info.json must contain '${k}'.`,
          `Add the '${k}' field to info.json.`));
      }
      break;
    case "missing_artwork":
      findings.push(finding("error", "No artwork in any layout",
        `None of the layouts (${verdict.layouts.join(", ")}) names a file that is in the archive, so the catalog's health check would hide this skin.`,
        "Add the artwork files and check the names in each layout's assets."));
      break;
    case "ok":
      for (const label of verdict.partialArtwork || []) {
        findings.push(finding("warning", `No artwork for ${label}`,
          `The ${label} layout names no artwork that is in the archive, so it draws nothing.`,
          "Add the file, or remove the layout."));
      }
      break;
    default:
      findings.push(finding("error", "Could not check the skin", `Unexpected result "${verdict.result}".`));
  }

  if (isObject(info) && (verdict.result === "ok" || verdict.result === "info_missing_keys" || verdict.result === "missing_artwork")) {
    if (info.debug === undefined) {
      findings.push(finding("warning", "Missing 'debug' field",
        "info.json does not include a debug flag. The skin will import with debug disabled.",
        'Add "debug": false to info.json to be explicit.'));
    }
    // A layout whose first-found size resolves still lists other sizes the app may pick on other devices.
    if (names && verdict.result === "ok") {
      const files = names.filter(n => !n.endsWith("/"));
      for (const [label, assets] of baseLayouts(info.representations)) {
        for (const key of ASSET_SIZE_KEYS) {
          if (nonEmptyString(assets[key]) && !findAsset(files, assets[key]) && hasArtwork(files, assets)) {
            findings.push(finding("warning", `Missing asset: ${assets[key]}`,
              `Asset '${assets[key]}' (${key}) referenced in ${label} does not exist in the archive.`,
              `Add the file '${assets[key]}' to the skin archive, or remove the reference.`));
          }
        }
      }
    }
  }

  if (!findings.length) findings.push(finding("info", "Skin is valid", "No issues found."));
  const errors = findings.filter(f => f.severity === "error");
  const warnings = findings.filter(f => f.severity === "warning");
  return { result: verdict.result, findings, errors, warnings, isValid: errors.length === 0 };
}
