"use strict";

const CATALOG_URL = "catalog.json";

const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) && !window.MSStream;

const SYSTEM_LABELS = {
  // Nintendo handhelds
  gb: "Game Boy", gbc: "Game Boy Color", gba: "GBA",
  // Nintendo consoles
  nes: "NES", snes: "SNES", n64: "N64", nds: "NDS",
  virtualBoy: "Virtual Boy", threeDS: "3DS",
  gamecube: "GameCube", wii: "Wii", pokemonMini: "Pokémon Mini",
  // Sega
  genesis: "Genesis/MD", gamegear: "Game Gear", masterSystem: "Master System",
  sg1000: "SG-1000", segaCD: "Sega CD", sega32X: "32X",
  saturn: "Saturn", dreamcast: "Dreamcast",
  // Sony
  psx: "PlayStation", psp: "PSP",
  // NEC
  pce: "PC Engine", pcecd: "PC Engine CD", pcfx: "PC-FX", sgfx: "SuperGrafx",
  // Atari
  atari2600: "Atari 2600", atari5200: "Atari 5200", atari7800: "Atari 7800",
  jaguar: "Jaguar", jaguarcd: "Jaguar CD", lynx: "Lynx",
  atari8bit: "Atari 8-bit", atarist: "Atari ST",
  // SNK
  neogeo: "Neo Geo", ngp: "Neo Geo Pocket", ngpc: "NGP Color",
  // Bandai
  wonderswan: "WonderSwan", wonderswancolor: "WonderSwan Color",
  // Vectrex
  vectrex: "Vectrex",
  // Other
  _3do: "3DO", appleII: "Apple II", c64: "C64", cdi: "CD-i",
  colecovision: "ColecoVision", cps1: "CPS1", cps2: "CPS2", cps3: "CPS3",
  doom: "DOOM", dos: "DOS", ep128: "Enterprise 128",
  intellivision: "Intellivision", macintosh: "Mac Classic",
  mame: "MAME", megaduck: "Mega Duck", msx: "MSX", msx2: "MSX2",
  odyssey2: "Odyssey 2", supervision: "Supervision", tic80: "TIC-80",
  wolf3d: "Wolfenstein 3D", zxspectrum: "ZX Spectrum",
  retroarch: "RetroArch",
  unofficial: "Other",
};

const SOURCE_LABELS = {
  "deltastyles.com":          "DeltaStyles",
  "delta-skins.github.io":    "delta-skins",
  "LitRitt/emuskins":         "LitRitt",
  "Polyphian/deltaEmu":       "Polyphian",
};

let catalog = [];
let activeSystem = "all";
let activeSource = "all";
let searchQuery = "";
let sortOrder = "az"; // az | za | newest

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------

async function loadCatalog() {
  try {
    const res = await fetch(CATALOG_URL + "?t=" + Date.now());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    catalog = data.skins || [];
    renderStats(data);
    renderSystemChips();
    renderSourceChips();
    renderGrid();
  } catch (err) {
    document.getElementById("skin-grid").innerHTML = `
      <div class="empty-state">
        <div class="icon">⚠️</div>
        <h3>Failed to load catalog</h3>
        <p>${err.message}</p>
      </div>`;
  }
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

function renderStats(data) {
  document.getElementById("stat-total").textContent = data.totalSkins || catalog.length;
  const systems = new Set(catalog.flatMap(s => s.systems || []));
  document.getElementById("stat-systems").textContent = systems.size;
  const authors = new Set(catalog.map(s => s.author).filter(Boolean));
  document.getElementById("stat-authors").textContent = authors.size || "—";
  if (data.lastUpdated) {
    const d = new Date(data.lastUpdated);
    document.getElementById("stat-updated").textContent =
      d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
}

// ---------------------------------------------------------------------------
// System chips
// ---------------------------------------------------------------------------

function renderSystemChips() {
  const counts = {};
  catalog.forEach(s => (s.systems || []).forEach(sys => {
    counts[sys] = (counts[sys] || 0) + 1;
  }));

  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const chips = document.getElementById("system-chips");

  chips.querySelector('[data-system="all"]').textContent = `All (${catalog.length})`;

  sorted.forEach(([sys, count]) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.dataset.system = sys;
    chip.textContent = `${SYSTEM_LABELS[sys] || sys} (${count})`;
    chips.appendChild(chip);
  });

  chips.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    chips.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    activeSystem = chip.dataset.system;
    renderGrid();
  });
}

// ---------------------------------------------------------------------------
// Source chips
// ---------------------------------------------------------------------------

function renderSourceChips() {
  const counts = {};
  catalog.forEach(s => {
    const src = s.source || "unknown";
    counts[src] = (counts[src] || 0) + 1;
  });

  const container = document.getElementById("source-chips");
  if (!container) return;

  container.querySelector('[data-source="all"]').textContent = `All Sources (${catalog.length})`;

  Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([src, count]) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.dataset.source = src;
    chip.textContent = `${SOURCE_LABELS[src] || src} (${count})`;
    container.appendChild(chip);
  });

  container.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    container.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
    chip.classList.add("active");
    activeSource = chip.dataset.source;
    renderGrid();
  });
}

// ---------------------------------------------------------------------------
// Filter + sort
// ---------------------------------------------------------------------------

function filterSkins() {
  let skins = catalog;
  if (activeSystem !== "all") {
    skins = skins.filter(s => (s.systems || []).includes(activeSystem));
  }
  if (activeSource !== "all") {
    skins = skins.filter(s => (s.source || "unknown") === activeSource);
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    skins = skins.filter(s =>
      (s.name || "").toLowerCase().includes(q) ||
      (s.author || "").toLowerCase().includes(q) ||
      (s.tags || []).some(t => t.toLowerCase().includes(q)) ||
      (s.systems || []).some(sys => (SYSTEM_LABELS[sys] || sys).toLowerCase().includes(q))
    );
  }
  // Sort
  skins = [...skins];
  if (sortOrder === "az") {
    skins.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  } else if (sortOrder === "za") {
    skins.sort((a, b) => (b.name || "").localeCompare(a.name || ""));
  } else if (sortOrder === "newest") {
    skins.sort((a, b) => {
      const da = a.lastUpdated ? new Date(a.lastUpdated) : new Date(0);
      const db = b.lastUpdated ? new Date(b.lastUpdated) : new Date(0);
      return db - da;
    });
  }
  return skins;
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

function renderGrid() {
  const skins = filterSkins();
  const grid = document.getElementById("skin-grid");
  const count = document.getElementById("results-count");
  count.textContent = `${skins.length} skin${skins.length !== 1 ? "s" : ""}`;

  if (!skins.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="icon">🔍</div>
        <h3>No skins found</h3>
        <p>Try a different search or system filter.</p>
      </div>`;
    return;
  }

  grid.innerHTML = skins.map((skin, i) => cardHTML(skin, i)).join("");

  // Attach click handlers for modal
  grid.querySelectorAll(".skin-card[data-idx]").forEach(card => {
    card.addEventListener("click", e => {
      if (e.target.closest("a")) return; // let download link work normally
      openModal(parseInt(card.dataset.idx, 10));
    });
  });
}

function cardHTML(skin, idx) {
  const name = escHtml(skin.name || "Unnamed Skin");
  const author = skin.author ? `by ${escHtml(skin.author)}` : "";
  const systems = (skin.systems || []).map(s =>
    `<span class="system-badge">${SYSTEM_LABELS[s] || s}</span>`
  ).join("");
  const tags = (skin.tags || []).slice(0, 3).map(t =>
    `<span class="tag">${escHtml(t)}</span>`
  ).join("");

  const thumb = skin.thumbnailURL
    ? `<img src="${escHtml(skin.thumbnailURL)}" alt="${name}" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'no-thumb\\'>🎮</span>'">`
    : `<span class="no-thumb">🎮</span>`;

  return `
  <div class="skin-card" data-idx="${idx}" tabindex="0" role="button" aria-label="View details for ${name}">
    <div class="card-thumb">${thumb}</div>
    <div class="card-body">
      <div class="card-name">${name}</div>
      ${author ? `<div class="card-author">${author}</div>` : ""}
      <div class="card-tags">${systems}${tags}</div>
    </div>
    <div class="card-footer">
      ${isIOS
        ? `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm ios-install"
             onclick="event.stopPropagation()">📲 Install in Provenance</a>`
        : `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm" download
             onclick="event.stopPropagation()">⬇ Download</a>`
      }
    </div>
  </div>`;
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

let currentSkinIdx = -1;
let filteredCache = [];

function openModal(idx) {
  filteredCache = filterSkins();
  currentSkinIdx = idx;
  renderModal(filteredCache[idx]);
  document.getElementById("skin-modal").classList.add("open");
  document.body.style.overflow = "hidden";
}

function closeModal() {
  document.getElementById("skin-modal").classList.remove("open");
  document.body.style.overflow = "";
  currentSkinIdx = -1;
}

function navigateModal(dir) {
  const next = currentSkinIdx + dir;
  if (next < 0 || next >= filteredCache.length) return;
  currentSkinIdx = next;
  renderModal(filteredCache[currentSkinIdx]);
}

function renderModal(skin) {
  if (!skin) return;
  const name = escHtml(skin.name || "Unnamed Skin");
  const author = skin.author ? escHtml(skin.author) : null;
  const systems = (skin.systems || []).map(s =>
    `<span class="system-badge">${SYSTEM_LABELS[s] || s}</span>`
  ).join(" ");
  const tags = (skin.tags || []).map(t => `<span class="tag">${escHtml(t)}</span>`).join(" ");
  const url = skin.downloadURL || "";
  const ext = url.split(".").pop().toLowerCase();

  const thumb = skin.thumbnailURL
    ? `<img src="${escHtml(skin.thumbnailURL)}" alt="${name}"
          onerror="this.outerHTML='<div class=\\'modal-no-thumb\\'>🎮</div>'">`
    : `<div class="modal-no-thumb">🎮</div>`;

  let meta = "";
  if (author) meta += `<div class="modal-meta-row"><span>Author</span><strong>${author}</strong></div>`;
  if (skin.version) meta += `<div class="modal-meta-row"><span>Version</span><strong>${escHtml(skin.version)}</strong></div>`;
  if (skin.lastUpdated) {
    const d = new Date(skin.lastUpdated).toLocaleDateString("en-US", {year:"numeric",month:"short",day:"numeric"});
    meta += `<div class="modal-meta-row"><span>Updated</span><strong>${d}</strong></div>`;
  }
  if (skin.fileSize) {
    const kb = Math.round(skin.fileSize / 1024);
    meta += `<div class="modal-meta-row"><span>Size</span><strong>${kb > 1024 ? (kb/1024).toFixed(1)+"MB" : kb+"KB"}</strong></div>`;
  }
  if (skin.source) meta += `<div class="modal-meta-row"><span>Source</span><strong>${escHtml(skin.source)}</strong></div>`;

  const nav = `
    <button class="modal-nav modal-prev" onclick="navigateModal(-1)" aria-label="Previous skin">‹</button>
    <button class="modal-nav modal-next" onclick="navigateModal(1)" aria-label="Next skin">›</button>`;

  document.getElementById("modal-content").innerHTML = `
    ${nav}
    <button class="modal-close" onclick="closeModal()" aria-label="Close">✕</button>
    <div class="modal-body">
      <div class="modal-thumb">${thumb}</div>
      <div class="modal-info">
        <h2 class="modal-title">${name}</h2>
        ${author ? `<div class="modal-author">by ${author}</div>` : ""}
        <div class="modal-systems">${systems}</div>
        ${tags ? `<div class="modal-tags">${tags}</div>` : ""}
        ${meta ? `<div class="modal-meta">${meta}</div>` : ""}
        <div class="modal-actions">
          ${isIOS
            ? `<a href="${escHtml(url)}" class="btn btn-primary ios-install">
                 📲 Install in Provenance
               </a>`
            : `<a href="${escHtml(url)}" class="btn btn-primary" download>
                 ⬇ Download .${escHtml(ext)}
               </a>`
          }
          <button class="btn btn-outline" onclick="copyUrl('${escHtml(url)}')" id="copy-btn">
            📋 Copy URL
          </button>
        </div>
        <p class="modal-hint">
          ${isIOS
            ? `Tap <strong>Install in Provenance</strong> — iOS will open the skin directly in the app.`
            : `On iPhone/iPad: tap the download link — iOS will offer to open the skin in Provenance.`
          }
        </p>
      </div>
    </div>
    <div class="modal-counter">${currentSkinIdx + 1} / ${filteredCache.length}</div>`;
}

function copyUrl(url) {
  navigator.clipboard.writeText(url).then(() => {
    const btn = document.getElementById("copy-btn");
    if (!btn) return;
    const orig = btn.textContent;
    btn.textContent = "✓ Copied!";
    setTimeout(() => { btn.textContent = orig; }, 2000);
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Event wiring
// ---------------------------------------------------------------------------

document.getElementById("search").addEventListener("input", e => {
  searchQuery = e.target.value.trim();
  renderGrid();
});

document.getElementById("sort-select").addEventListener("change", e => {
  sortOrder = e.target.value;
  renderGrid();
});

// Modal backdrop click
document.getElementById("skin-modal").addEventListener("click", e => {
  if (e.target === e.currentTarget) closeModal();
});

// Keyboard nav
document.addEventListener("keydown", e => {
  if (!document.getElementById("skin-modal").classList.contains("open")) return;
  if (e.key === "Escape") closeModal();
  if (e.key === "ArrowLeft")  navigateModal(-1);
  if (e.key === "ArrowRight") navigateModal(1);
});

// Keyboard activate card
document.getElementById("skin-grid").addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " ") {
    const card = e.target.closest(".skin-card[data-idx]");
    if (card) {
      e.preventDefault();
      openModal(parseInt(card.dataset.idx, 10));
    }
  }
});

loadCatalog();
