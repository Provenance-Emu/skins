import { bakeClassic } from "../../docs/js/skin2/bake.js";
import { nativeSize } from "./native-size.mjs";

// Link health passes only bounded metadata and the archive's entry names. The baker's PDF
// and PNG writers do not participate in metadata generation.
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const info = Buffer.from(request.info, "base64");
const source = Buffer.from(request.source, "base64");
const empty = async () => new Uint8Array();
let verdict;
try {
  const bundles = await bakeClassic(source, new Map(), { nativeSize, pdf: empty, preview: empty });
  const match = bundles.find((bundle) => info.equals(bundle.files.get("info.json")));
  if (!match) {
    verdict = { ok: false, error: "info.json differs from the canonical classic bake" };
  } else {
    const files = new Set(request.files);
    const missing = [...match.files.keys()].filter((name) =>
      name !== "info.json" && name !== "skin.json" && !files.has(name));
    verdict = missing.length ? { ok: false, error: `Missing baked file: ${missing[0]}` } : { ok: true };
  }
} catch (error) {
  verdict = { ok: false, error: error.message };
}
process.stdout.write(JSON.stringify(verdict));
