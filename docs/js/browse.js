"use strict";

const CATALOG_URL = "catalog.json";

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

let catalog = [];
let activeSystem = "all";
let searchQuery = "";

async function loadCatalog() {
  try {
    const res = await fetch(CATALOG_URL + "?t=" + Date.now());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    catalog = data.skins || [];
    renderStats(data);
    renderSystemChips();
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

function renderSystemChips() {
  const counts = {};
  catalog.forEach(s => (s.systems || []).forEach(sys => {
    counts[sys] = (counts[sys] || 0) + 1;
  }));

  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const chips = document.getElementById("system-chips");

  // Update "All" chip count
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

function filterSkins() {
  let skins = catalog;
  if (activeSystem !== "all") {
    skins = skins.filter(s => (s.systems || []).includes(activeSystem));
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
  return skins;
}

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

  grid.innerHTML = skins.map(skin => cardHTML(skin)).join("");
}

function cardHTML(skin) {
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
  <div class="skin-card">
    <div class="card-thumb">${thumb}</div>
    <div class="card-body">
      <div class="card-name">${name}</div>
      ${author ? `<div class="card-author">${author}</div>` : ""}
      <div class="card-tags">${systems}${tags}</div>
    </div>
    <div class="card-footer">
      <a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm" download>
        ⬇ Download
      </a>
    </div>
  </div>`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Search
document.getElementById("search").addEventListener("input", e => {
  searchQuery = e.target.value.trim();
  renderGrid();
});

loadCatalog();
