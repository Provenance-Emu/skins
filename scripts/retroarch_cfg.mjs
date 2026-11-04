#!/usr/bin/env node
// Runs the site's RetroArch converter (docs/js/skin/retroarch-convert.js) with the site's input map over a
// SkinKit fixture set and prints {"<case id>": {"cfg": ..., "readme": ...}} as JSON on stdout.
//
//   node scripts/retroarch_cfg.mjs tests/fixtures/retroarch/skinkit
//
// The fixture set is SkinKit's Tests/SkinKitRetroArchTests/Fixtures (cases.json, info/, expected/), vendored
// with the SkinKit commit in SOURCE. tests/test_retroarch_cfg.py compares this output with expected/, so the
// website and SkinKitRetroArch stay byte-for-byte aligned (Provenance-Emu/SkinKit#81).
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const dir = process.argv[2];
if (!dir) { console.error("usage: retroarch_cfg.mjs <fixture dir>"); process.exit(2); }
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RA = await import(pathToFileURL(join(root, "docs", "js", "skin", "retroarch-convert.js")).href);
const inputMap = JSON.parse(readFileSync(join(root, "docs", "js", "skin", "retroarch-input-map.json"), "utf8"));

const out = {};
for (const c of JSON.parse(readFileSync(join(dir, "cases.json"), "utf8"))) {
  const info = RA.parseInfo(readFileSync(join(dir, "info", `${c.info}.info.json`), "utf8"));
  // Same synthetic TV layout SkinKit's generator adds for this case.
  if (c.tvFromIPadStandardLandscape) info.representations.tv = { standard: { landscape: info.representations.ipad.standard.landscape } };
  const opts = { inputMap };
  for (const k of ["device", "displayType", "screenAspect", "name", "entries"]) if (c[k] !== undefined) opts[k] = c[k];
  const r = RA.convert(info, opts);
  out[c.id] = { cfg: r.cfg, readme: r.readme };
}
process.stdout.write(JSON.stringify(out));
