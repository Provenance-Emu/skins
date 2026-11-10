import { readFile } from "node:fs/promises";
import { normalizeGameType } from "../../docs/js/skin2/features.js";

const registry = JSON.parse(await readFile(new URL("./system-native-resolutions.json", import.meta.url), "utf8"));
const keys = new Map(Object.keys(registry).map((key) => [key.toLowerCase(), key]));
const aliases = new Map(Object.entries({
  gb: "gbc", ds: "nds", ps1: "psx", md: "genesis", megadrive: "genesis",
  gc: "gameCube", ngc: "gameCube", gcn: "gameCube", dc: "dreamcast", sfc: "snes",
}));

export function nativeSize(gameType) {
  const key = normalizeGameType(gameType);
  return registry[aliases.get(key) ?? keys.get(key)];
}
