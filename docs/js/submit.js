import { createSubmissionBundle, readSkin } from "./skin/zip.js";
import { listLayouts } from "./skin/info.js";

// Maps gameTypeIdentifier (from skin info.json) → catalog system code.
// Covers both original Delta GTIs and Provenance/ManicEmu GTIs.
const SYSTEM_MAP = {
  // Delta (rileytestut)
  "com.rileytestut.delta.game.gba": "gba",
  "com.rileytestut.delta.game.gbc": "gbc",
  "com.rileytestut.delta.game.nes": "nes",
  "com.rileytestut.delta.game.snes": "snes",
  "com.rileytestut.delta.game.n64": "n64",
  "com.rileytestut.delta.game.ds": "nds",
  "com.rileytestut.delta.game.genesis": "genesis",
  "com.rileytestut.delta.game.psx": "psx",
  // Provenance/ManicEmu (public.aoshuang.game.*)
  "public.aoshuang.game.gbc": "gbc",
  "public.aoshuang.game.gba": "gba",
  "public.aoshuang.game.nes": "nes",
  "public.aoshuang.game.snes": "snes",
  "public.aoshuang.game.n64": "n64",
  "public.aoshuang.game.ds": "nds",
  "public.aoshuang.game.md": "genesis",
  "public.aoshuang.game.gg": "gamegear",
  "public.aoshuang.game.ms": "masterSystem",
  "public.aoshuang.game.ps1": "psx",
  "public.aoshuang.game.psp": "psp",
  "public.aoshuang.game.ss": "saturn",
  "public.aoshuang.game.dc": "dreamcast",
  "public.aoshuang.game.mcd": "segaCD",
  "public.aoshuang.game.32x": "sega32X",
  "public.aoshuang.game.sg1000": "sg1000",
  "public.aoshuang.game.vb": "virtualBoy",
  "public.aoshuang.game.3ds": "threeDS",
  "public.aoshuang.game.pm": "pokemonMini",
  "public.aoshuang.game.ngc": "gamecube",
  "public.aoshuang.game.gc": "gamecube",  // legacy alias; Manic's canonical GTI is .ngc
  "public.aoshuang.game.wii": "wii",
  "public.aoshuang.game.pce": "pce",
  "public.aoshuang.game.pcecd": "pcecd",
  "public.aoshuang.game.pcfx": "pcfx",
  "public.aoshuang.game.sgfx": "sgfx",
  "public.aoshuang.game.2600": "atari2600",
  "public.aoshuang.game.5200": "atari5200",
  "public.aoshuang.game.7800": "atari7800",
  "public.aoshuang.game.jaguar": "jaguar",
  "public.aoshuang.game.jaguarcd": "jaguarcd",
  "public.aoshuang.game.lynx": "lynx",
  "public.aoshuang.game.atari8bit": "atari8bit",
  "public.aoshuang.game.neogeo": "neogeo",
  "public.aoshuang.game.ngp": "ngp",
  "public.aoshuang.game.ngpc": "ngpc",
  "public.aoshuang.game.ws": "wonderswan",
  "public.aoshuang.game.wsc": "wonderswancolor",
  "public.aoshuang.game.vectrex": "vectrex",
  "public.aoshuang.game.colecovision": "colecovision",
  "public.aoshuang.game.intellivision": "intellivision",
  "public.aoshuang.game.3do": "_3do",
  "public.aoshuang.game.c64": "c64",
  "public.aoshuang.game.mame": "mame",
};

const SYSTEM_LABELS = {
  gb: "Game Boy", gbc: "Game Boy Color", gba: "Game Boy Advance",
  nes: "NES", snes: "Super Nintendo", n64: "Nintendo 64",
  nds: "Nintendo DS", threeDS: "Nintendo 3DS", virtualBoy: "Virtual Boy",
  gamecube: "GameCube", wii: "Wii", pokemonMini: "Pokémon Mini",
  genesis: "Sega Genesis", gamegear: "Game Gear", masterSystem: "Master System",
  sg1000: "SG-1000", segaCD: "Sega CD", sega32X: "Sega 32X",
  saturn: "Sega Saturn", dreamcast: "Dreamcast",
  psx: "PlayStation", psp: "PSP",
  pce: "PC Engine / TurboGrafx-16", pcecd: "PC Engine CD",
  sgfx: "SuperGrafx", pcfx: "PC-FX",
  atari2600: "Atari 2600", atari5200: "Atari 5200", atari7800: "Atari 7800",
  lynx: "Atari Lynx", jaguar: "Atari Jaguar", jaguarcd: "Atari Jaguar CD",
  atari8bit: "Atari 8-bit",
  neogeo: "Neo Geo", ngp: "Neo Geo Pocket", ngpc: "Neo Geo Pocket Color",
  wonderswan: "WonderSwan", wonderswancolor: "WonderSwan Color",
  vectrex: "Vectrex", colecovision: "ColecoVision", intellivision: "Intellivision",
  _3do: "3DO", c64: "Commodore 64", mame: "MAME",
  unofficial: "Unofficial / Other",
};

let currentEntry = null;

function showAlert(id, msg) {
  ["alert-fetching", "alert-error", "alert-copied"].forEach(i => {
    const el = document.getElementById(i);
    el.classList.remove("visible");
    el.textContent = "";
  });
  if (id && msg !== null) {
    const el = document.getElementById(id);
    if (msg) el.textContent = msg;
    el.classList.add("visible");
  }
}

function makeId(source, url) {
  // We can't run sha256 in vanilla JS easily without a library,
  // so we generate a deterministic-ish ID client-side for preview purposes.
  // The real canonical ID is generated server-side by process_submission.py.
  let hash = 0;
  const str = `${source}:${url}`;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash).toString(16).padStart(8, "0") + Math.abs(hash ^ 0xdeadbeef).toString(16).padStart(8, "0");
}

function slugify(name) {
  return name.toLowerCase().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

async function tryFetchZip(url) {
  // Attempt to fetch and parse the ZIP in-browser (works for CORS-enabled sources like GitHub raw).
  // readSkin (docs/js/skin/zip.js) finds info.json at the root or one folder down and
  // ignores the comments and trailing commas the apps ignore.
  try {
    const res = await fetch(url, { mode: "cors" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const skin = await readSkin(await res.arrayBuffer());
    return skin.info;
  } catch (e) {
    return null;
  }
}

function isGitHubUrl(url) {
  return /github\.com/.test(url);
}

function isDirectSkinUrl(url) {
  return /\.(deltaskin|manicskin)(\?.*)?$/i.test(url);
}

function isGitHubRepo(url) {
  return /^https?:\/\/github\.com\/[^/]+\/[^/]+\/?$/.test(url);
}

function getRawUrl(url) {
  // Convert github.com blob URLs to raw.githubusercontent.com
  return url
    .replace("github.com", "raw.githubusercontent.com")
    .replace("/blob/", "/");
}

async function fetchMetadata(url) {
  if (isDirectSkinUrl(url)) {
    const rawUrl = isGitHubUrl(url) ? getRawUrl(url) : url;
    const info = await tryFetchZip(rawUrl);
    return { type: "skin_file", url: rawUrl, info };
  }
  if (isGitHubRepo(url)) {
    return { type: "github_repo", url };
  }
  if (/github\.com.*\/releases/.test(url)) {
    return { type: "github_release", url };
  }
  if (/\.json(\?.*)?$/i.test(url)) {
    // Try to fetch JSON directly
    try {
      const res = await fetch(url);
      const data = await res.json();
      return { type: "json_metadata", url, data };
    } catch {
      return { type: "json_metadata", url };
    }
  }
  // Unknown — try as skin file anyway
  const info = await tryFetchZip(url);
  return { type: "skin_file", url, info };
}

function buildEntry(meta, url) {
  const { type, info } = meta;
  const source = isGitHubUrl(url)
    ? url.match(/github\.com\/([^/]+\/[^/]+)/)?.[1] || "github"
    : "manual";

  const entry = {
    id: makeId(source, url),
    name: info?.name || url.split("/").pop().replace(/\.(deltaskin|manicskin)$/i, ""),
    author: null,
    systems: [],
    gameTypeIdentifier: info?.gameTypeIdentifier || null,
    version: info?.version || null,
    downloadURL: url,
    thumbnailURL: null,
    screenshotURLs: [],
    tags: [],
    deviceSupport: [],
    downloadCount: null,
    rating: null,
    lastUpdated: null,
    fileSize: null,
    source,
  };

  if (info?.gameTypeIdentifier && SYSTEM_MAP[info.gameTypeIdentifier]) {
    entry.systems = [SYSTEM_MAP[info.gameTypeIdentifier]];
  } else {
    entry.systems = ["unofficial"];
  }

  return entry;
}

function renderPreview(meta, entry) {
  const preview = document.getElementById("preview-box");
  const metaEl = document.getElementById("preview-meta");
  const jsonEl = document.getElementById("preview-json");

  const system = entry.systems[0];
  const systemLabel = SYSTEM_LABELS[system] || system;

  const rows = [
    ["Name", entry.name],
    ["System", systemLabel],
    ["Author", entry.author || "—"],
    ["Source type", meta.type.replace(/_/g, " ")],
    ["ID (preview)", entry.id],
  ];

  metaEl.innerHTML = rows.map(([k, v]) =>
    `<dt>${k}</dt><dd>${v}</dd>`
  ).join("");

  jsonEl.textContent = JSON.stringify(entry, null, 2);
  preview.classList.add("visible");
}

function buildIssueUrl(entry, rawUrl) {
  const params = new URLSearchParams({
    template: "submit-skin.yml",
    "skin_url": rawUrl,
  });
  return `https://github.com/Provenance-Emu/skins/issues/new?${params}`;
}

document.getElementById("fetch-btn").addEventListener("click", async () => {
  const url = document.getElementById("skin-url").value.trim();
  if (!url) return;

  showAlert("alert-fetching", "⏳ Fetching skin metadata…");
  document.getElementById("preview-box").classList.remove("visible");
  document.getElementById("submit-section").style.display = "none";
  currentEntry = null;

  try {
    const meta = await fetchMetadata(url);

    if (meta.type === "github_repo") {
      showAlert("alert-info", null);
      document.getElementById("alert-fetching").textContent =
        "ℹ️ GitHub repo detected. Metadata will be extracted automatically when you submit.";
      document.getElementById("alert-fetching").classList.add("visible");
    } else if (meta.type === "github_release") {
      document.getElementById("alert-fetching").textContent =
        "ℹ️ GitHub release detected. All skin assets will be imported automatically when you submit.";
    } else if (meta.info) {
      showAlert(null, null);
      currentEntry = buildEntry(meta, meta.url);
      renderPreview(meta, currentEntry);
    } else {
      showAlert("alert-error",
        "⚠️ Could not auto-extract metadata (CORS or non-GitHub host). " +
        "You can still submit — the bot will extract it server-side.");
      // Build a minimal entry anyway
      currentEntry = buildEntry(meta, url);
    }

    // Always show submit section
    document.getElementById("submit-section").style.display = "block";

    // Wire up issue URL
    document.getElementById("issue-btn").href = buildIssueUrl(currentEntry || {}, url);

  } catch (err) {
    showAlert("alert-error", `❌ Error: ${err.message}`);
  }
});

// Enter key triggers fetch
document.getElementById("skin-url").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("fetch-btn").click();
});

// Copy JSON button
document.getElementById("copy-json-btn").addEventListener("click", () => {
  const json = currentEntry
    ? JSON.stringify(currentEntry, null, 2)
    : document.getElementById("preview-json").textContent;
  if (!json) return;
  navigator.clipboard.writeText(json).then(() => {
    showAlert("alert-copied",
      "✅ Copied! Add this file to skins/{system}/ in a PR at github.com/Provenance-Emu/skins");
    document.getElementById("alert-copied").classList.add("visible");
  });
});

const RECEIPT_STORAGE_KEY = "emuskins-upload-receipts";
const RECEIPT_MAX_AGE = 14 * 24 * 60 * 60 * 1000;

function setupUploadReceipts() {
  const panel = document.getElementById("upload-receipts");
  const list = document.getElementById("upload-receipt-list");
  const copyStatus = document.getElementById("upload-copy-status");
  const heading = document.getElementById("upload-receipts-title");
  let receipts = [];
  try {
    const saved = JSON.parse(localStorage.getItem(RECEIPT_STORAGE_KEY));
    const cutoff = Date.now() - RECEIPT_MAX_AGE;
    if (Array.isArray(saved)) {
      receipts = saved.filter(entry =>
        typeof entry?.id === "string" &&
        /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(entry.id) &&
        Number.isFinite(entry.savedAt) && entry.savedAt > cutoff
      ).slice(0, 20);
    }
  } catch { /* The current receipt can still be displayed. */ }

  function save() {
    try {
      if (receipts.length) localStorage.setItem(RECEIPT_STORAGE_KEY, JSON.stringify(receipts));
      else localStorage.removeItem(RECEIPT_STORAGE_KEY);
    } catch { /* Storage can be disabled or full. */ }
  }

  function render() {
    list.replaceChildren();
    panel.hidden = !receipts.length;
    for (const { id } of receipts) {
      const row = document.createElement("li");
      const code = document.createElement("code");
      code.textContent = id;
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "btn btn-outline btn-sm";
      copy.textContent = "Copy receipt";
      copy.setAttribute("aria-label", `Copy receipt ${id}`);
      copy.addEventListener("click", async () => {
        copyStatus.textContent = "";
        try {
          await navigator.clipboard.writeText(id);
          copyStatus.textContent = "Receipt copied.";
        } catch {
          const range = document.createRange();
          range.selectNodeContents(code);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          copyStatus.textContent = "Clipboard unavailable. Copy the selected receipt manually.";
        }
      });
      row.append(code, copy);
      list.append(row);
    }
  }

  save();
  render();
  return id => {
    receipts = [{ id, savedAt: Date.now() }, ...receipts.filter(entry => entry.id !== id)].slice(0, 20);
    save();
    render();
    copyStatus.textContent = "";
    heading.textContent = "Submitted for review";
    heading.focus();
  };
}

function setupUploadPilot(form) {
  const showReceipt = setupUploadReceipts();
  const invite = document.getElementById("upload-invite");
  const picker = document.getElementById("upload-files");
  const author = document.getElementById("upload-author");
  const source = document.getElementById("upload-source");
  const preview = document.getElementById("upload-preview");
  const status = document.getElementById("upload-status");
  const send = document.getElementById("upload-send");
  const controls = [...form.querySelectorAll("input")];
  let files = [];
  let selection = 0;
  let requestId;

  picker.addEventListener("change", async () => {
    const current = ++selection;
    const chosen = [...picker.files];
    files = [];
    send.disabled = true;
    preview.replaceChildren();
    preview.hidden = true;
    status.textContent = "";
    if (!chosen.length) return;
    if (chosen.length > 5 || chosen.reduce((sum, file) => sum + file.size, 0) > 15 * 1024 * 1024) {
      status.textContent = "Choose up to 5 skins with a combined size of 15 MiB or less.";
      return;
    }
    status.textContent = "Reading your skins…";
    const items = [];
    try {
      for (const file of chosen) {
        if (!/\.(deltaskin|manicskin)$/i.test(file.name)) {
          throw new Error(`${file.name}: choose a .deltaskin or .manicskin file.`);
        }
        try {
          const { info } = await readSkin(file);
          const layouts = listLayouts(info.representations);
          if (!layouts.length) throw new Error("No controller layouts in info.json.");
          const item = document.createElement("li");
          const system = SYSTEM_MAP[info.gameTypeIdentifier] || info.gameTypeIdentifier || "Unknown system";
          item.textContent = `${info.name || file.name} · ${system} · ${layouts.length} layout${layouts.length === 1 ? "" : "s"}`;
          items.push(item);
        } catch (error) {
          throw new Error(`${file.name}: ${error.message}`);
        }
      }
      if (current !== selection) return;
      preview.replaceChildren(...items);
      preview.hidden = false;
      files = chosen;
      send.disabled = false;
      status.textContent = "Check the skin details above, then submit for review.";
    } catch (error) {
      if (current === selection) status.textContent = error.message;
    }
  });

  form.addEventListener("input", () => { requestId = undefined; });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (send.disabled || !files.length) return;
    let sourceURL = "";
    if (source.value) {
      try {
        const url = new URL(source.value);
        if (url.protocol !== "https:" || url.username || url.password) throw new Error();
        sourceURL = url.href;
      } catch {
        status.textContent = "Enter an HTTPS link for the original listing or leave it blank.";
        source.focus();
        return;
      }
    }
    if (!author.value.trim()) {
      status.textContent = "Enter the author name you want shown in the catalog.";
      author.focus();
      return;
    }
    send.disabled = true;
    for (const control of controls) control.disabled = true;
    status.textContent = "Uploading your skins…";
    let submitted = false;
    try {
      requestId ??= crypto.randomUUID();
      const body = await createSubmissionBundle(files, { author: author.value.trim(), sourceURL });
      const response = await fetch(form.dataset.endpoint, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${invite.value}`,
          "Content-Type": "application/zip",
          "X-Submission-ID": requestId,
        },
        credentials: "omit",
        body,
      });
      const result = await response.json();
      if (!response.ok || result.receipt !== requestId) {
        status.textContent = result.error || "The upload was not confirmed. Please retry.";
        return;
      }
      submitted = true;
      form.reset();
      files = [];
      preview.replaceChildren();
      preview.hidden = true;
      status.textContent = "";
      showReceipt(result.receipt);
    } catch {
      status.textContent = "The upload could not be confirmed. Keep this page open and try again.";
    } finally {
      for (const control of controls) control.disabled = false;
      send.disabled = submitted;
    }
  });
}

const uploadForm = document.getElementById("skin-upload-form");
if (uploadForm) setupUploadPilot(uploadForm);
