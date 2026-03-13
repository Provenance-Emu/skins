"use strict";

const CATALOG_URL = "catalog.json";

// ---------------------------------------------------------------------------
// localStorage keys
// ---------------------------------------------------------------------------
const FAV_KEY       = "prov-favs";
const LAST_VISIT_KEY = "prov-last-visit";

// ---------------------------------------------------------------------------
// Favorites helpers
// ---------------------------------------------------------------------------
function getFavs() {
  try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY) || "[]")); }
  catch { return new Set(); }
}

function saveFavs(set) {
  localStorage.setItem(FAV_KEY, JSON.stringify([...set]));
}

function toggleFav(skinId) {
  const favs = getFavs();
  if (favs.has(skinId)) { favs.delete(skinId); } else { favs.add(skinId); }
  saveFavs(favs);
  return favs.has(skinId);
}

// ---------------------------------------------------------------------------
// "New since last visit" helpers
// ---------------------------------------------------------------------------
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;
const lastVisitRaw   = localStorage.getItem(LAST_VISIT_KEY);
const lastVisitDate  = lastVisitRaw ? new Date(lastVisitRaw) : null;

function isNewSkin(skin) {
  if (!skin.lastUpdated) return false;
  const updated = new Date(skin.lastUpdated);
  const now = Date.now();
  if (now - updated.getTime() > THIRTY_DAYS_MS) return false;
  if (!lastVisitDate) return false;
  return updated > lastVisitDate;
}

const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) && !window.MSStream;
const isIPad = /iPad/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isTV = /AppleTV/.test(navigator.userAgent);
const detectedDevice = isTV ? "tv" : isIPad ? "ipad" : isIOS ? "iphone" : null;

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
let featuredIds = new Set(); // populated after featured.json load
let activeSystem = "all";
let activeSource = "all";
let activeFavs    = false;   // true when "♥ Favorites" chip is selected
let activeDevice  = false;   // true when "My Device" chip is selected
let searchQuery = "";
let sortOrder = "az"; // az | za | newest

// ---------------------------------------------------------------------------
// URL state — ?system=gba&source=LitRitt&q=depths&sort=newest&skin=abc123
// ---------------------------------------------------------------------------

function getParams() {
  return new URLSearchParams(window.location.search);
}

function pushParams() {
  const p = new URLSearchParams();
  if (activeSystem !== "all") p.set("system", activeSystem);
  if (activeSource !== "all") p.set("source", activeSource);
  if (searchQuery)            p.set("q", searchQuery);
  if (sortOrder !== "az")     p.set("sort", sortOrder);
  if (activeDevice)           p.set("device", "1");
  const qs = p.toString();
  window.history.replaceState({}, "", qs ? `?${qs}` : window.location.pathname);
}

function skinPermalink(skinId) {
  const p = new URLSearchParams(window.location.search);
  p.set("skin", skinId);
  return `${window.location.origin}${window.location.pathname}?${p}`;
}

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------

async function loadCatalog() {
  try {
    const res = await fetch(CATALOG_URL + "?t=" + Date.now());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    catalog = data.skins || [];

    // Load featured picks
    try {
      const fRes = await fetch("featured.json?t=" + Date.now());
      if (fRes.ok) {
        const fData = await fRes.json();
        const picks = fData.picks || [];
        featuredIds = new Set(picks.map(p => p.id));
        // Store ordered list for sorting
        window._featuredOrder = picks.map(p => p.id);
        // Update featured chip count
        const fChip = document.getElementById("featured-chip");
        if (fChip) fChip.textContent = `✨ Featured (${featuredIds.size})`;
      }
    } catch (e) { /* featured.json optional */ }

    renderStats(data);
    renderSystemChips();
    addFavoritesChip();
    renderSourceChips();
    addMyDeviceChip();

    // Restore state from URL params
    const p = getParams();
    if (p.get("system")) activeSystem = p.get("system");
    if (p.get("source")) activeSource = p.get("source");
    if (p.get("sort"))   { sortOrder = p.get("sort"); const sel = document.getElementById("sort-select"); if (sel) sel.value = sortOrder; }
    if (p.get("q")) {
      searchQuery = p.get("q");
      const el = document.getElementById("search");
      if (el) el.value = searchQuery;
      updateSearchClear();
    }
    if (p.get("device") === "1" && detectedDevice) activeDevice = true;

    // Update last-visit timestamp AFTER we've captured the old value for badges
    localStorage.setItem(LAST_VISIT_KEY, new Date().toISOString());

    syncChipActiveState();
    updateChipCounts();
    renderGrid();

    // If ?skin= param present, open that skin's modal
    const skinId = p.get("skin");
    if (skinId) {
      const idx = filterSkins().findIndex(s => s.id === skinId);
      if (idx >= 0) openModal(idx);
    }
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
// Search helper
// ---------------------------------------------------------------------------

function applySearch(skins) {
  if (!searchQuery) return skins;
  const q = searchQuery.toLowerCase();
  return skins.filter(s =>
    (s.name || "").toLowerCase().includes(q) ||
    (s.author || "").toLowerCase().includes(q) ||
    (s.tags || []).some(t => t.toLowerCase().includes(q)) ||
    (s.systems || []).some(sys => (SYSTEM_LABELS[sys] || sys).toLowerCase().includes(q))
  );
}

// ---------------------------------------------------------------------------
// Cross-filter count helpers
// Counts for system chips respect the active source (and search).
// Counts for source chips respect the active system (and search).
// ---------------------------------------------------------------------------

function countForSystem(sys) {
  let skins = catalog;
  if (activeSource !== "all") skins = skins.filter(s => s.source === activeSource);
  skins = applySearch(skins);
  if (sys === "all") return skins.length;
  return skins.filter(s => (s.systems || []).includes(sys)).length;
}

function countForSource(src) {
  let skins = catalog;
  if (activeSystem !== "all") skins = skins.filter(s => (s.systems || []).includes(activeSystem));
  skins = applySearch(skins);
  if (src === "all") return skins.length;
  return skins.filter(s => s.source === src).length;
}

function updateChipCounts() {
  document.querySelectorAll("#system-chips .chip").forEach(chip => {
    const sys = chip.dataset.system;
    if (sys === "featured") {
      // Featured chip count is static — set once after featured.json load
      return;
    }
    if (sys === "favs") {
      // Favorites chip count is managed by updateFavoritesChip
      return;
    }
    const n = countForSystem(sys);
    const label = sys === "all" ? "All" : (SYSTEM_LABELS[sys] || sys);
    chip.textContent = `${label} (${n})`;
    // Dim chips with zero results (unless it's the active one — keep it visible)
    chip.classList.toggle("chip-empty", n === 0 && sys !== activeSystem);
  });

  document.querySelectorAll("#source-chips .chip").forEach(chip => {
    const src = chip.dataset.source;
    if (src === "mydevice") {
      // My Device chip label is static
      return;
    }
    const n = countForSource(src);
    const label = src === "all" ? "All Sources" : (SOURCE_LABELS[src] || src);
    chip.textContent = `${label} (${n})`;
    chip.classList.toggle("chip-empty", n === 0 && src !== activeSource);
  });

  renderActiveFilters();
}

function syncChipActiveState() {
  document.querySelectorAll("#system-chips .chip").forEach(c => {
    if (c.dataset.system === "favs") {
      c.classList.toggle("active", activeFavs);
    } else {
      c.classList.toggle("active", !activeFavs && c.dataset.system === activeSystem);
    }
  });
  document.querySelectorAll("#source-chips .chip").forEach(c => {
    if (c.dataset.source === "mydevice") {
      c.classList.toggle("active", activeDevice);
    } else {
      c.classList.toggle("active", !activeDevice && c.dataset.source === activeSource);
    }
  });
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
    const sys = chip.dataset.system;
    if (sys === "favs") {
      // Toggle favorites filter
      activeFavs = !activeFavs;
      if (activeFavs) activeSystem = "all"; // clear system filter when entering favs
      updateFavoritesChip();
      syncChipActiveState();
      updateChipCounts();
      renderGrid();
      return;
    }
    // Leaving favs mode when picking a system chip
    activeFavs = false;
    // Toggle: re-tapping the active chip (other than "all") resets to "all"
    activeSystem = (activeSystem === sys && sys !== "all") ? "all" : sys;
    updateFavoritesChip();
    syncChipActiveState();
    updateChipCounts();
    renderGrid();
  });

  // Update featured chip count if featuredIds already loaded
  const fChip = document.getElementById("featured-chip");
  if (fChip && featuredIds.size > 0) fChip.textContent = `✨ Featured (${featuredIds.size})`;
}

// ---------------------------------------------------------------------------
// Favorites chip
// ---------------------------------------------------------------------------

function addFavoritesChip() {
  const chips = document.getElementById("system-chips");
  if (chips.querySelector('[data-system="favs"]')) return; // already added
  const chip = document.createElement("div");
  chip.className = "chip chip-favs" + (activeFavs ? " active" : "");
  chip.dataset.system = "favs";
  const count = getFavs().size;
  chip.textContent = `♥ Favorites${count > 0 ? ` (${count})` : ""}`;
  // Insert right after the "All" chip
  const allChip = chips.querySelector('[data-system="all"]');
  allChip.insertAdjacentElement("afterend", chip);
}

function updateFavoritesChip() {
  const chip = document.querySelector('[data-system="favs"]');
  if (!chip) return;
  const count = getFavs().size;
  chip.textContent = `♥ Favorites${count > 0 ? ` (${count})` : ""}`;
  chip.classList.toggle("active", activeFavs);
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
    const src = chip.dataset.source;
    if (src === "mydevice") {
      activeDevice = !activeDevice;
      if (activeDevice) activeSource = "all"; // clear source filter when entering device mode
      syncChipActiveState();
      updateChipCounts();
      renderGrid();
      return;
    }
    // Leaving device mode when picking a source chip
    activeDevice = false;
    // Toggle: re-tapping the active chip (other than "all") resets to "all"
    activeSource = (activeSource === src && src !== "all") ? "all" : src;
    syncChipActiveState();
    updateChipCounts();
    renderGrid();
  });
}

// ---------------------------------------------------------------------------
// My Device chip
// ---------------------------------------------------------------------------

function addMyDeviceChip() {
  if (!detectedDevice) return; // only on iOS/tvOS
  const container = document.getElementById("source-chips");
  if (!container) return;
  if (container.querySelector('[data-source="mydevice"]')) return; // already added

  const deviceLabel = detectedDevice === "tv" ? "Apple TV" : detectedDevice === "ipad" ? "iPad" : "iPhone";
  const chip = document.createElement("div");
  chip.className = "chip" + (activeDevice ? " active" : "");
  chip.dataset.source = "mydevice";
  chip.textContent = `📱 ${deviceLabel}`;
  // Insert right after the "All Sources" chip
  const allChip = container.querySelector('[data-source="all"]');
  allChip.insertAdjacentElement("afterend", chip);
}

// ---------------------------------------------------------------------------
// Active filter summary pill + clear-all
// ---------------------------------------------------------------------------

function renderActiveFilters() {
  const container = document.getElementById("active-filters");
  if (!container) return;

  const parts = [];
  if (activeSystem !== "all" && activeSystem !== "featured") parts.push(SYSTEM_LABELS[activeSystem] || activeSystem);
  if (activeSystem === "featured") parts.push("Featured");
  if (activeSource !== "all") parts.push(SOURCE_LABELS[activeSource] || activeSource);
  if (activeDevice && detectedDevice) {
    const deviceLabel = detectedDevice === "tv" ? "Apple TV" : detectedDevice === "ipad" ? "iPad" : "iPhone";
    parts.push(`My ${deviceLabel}`);
  }
  if (searchQuery)            parts.push(`"${searchQuery}"`);

  if (parts.length === 0) {
    container.hidden = true;
    return;
  }
  container.hidden = false;
  container.innerHTML =
    `<span class="active-filter-label">Showing: ${parts.join(" · ")}</span>` +
    `<button class="clear-filters-btn" onclick="clearAllFilters()">✕ Clear all</button>`;
}

function clearAllFilters() {
  activeSystem = "all";
  activeSource = "all";
  activeFavs   = false;
  activeDevice  = false;
  searchQuery = "";
  sortOrder = "az";
  const search = document.getElementById("search");
  if (search) search.value = "";
  const sort = document.getElementById("sort-select");
  if (sort) sort.value = "az";
  updateSearchClear();
  updateFavoritesChip();
  syncChipActiveState();
  updateChipCounts();
  renderGrid();
}

// ---------------------------------------------------------------------------
// Search clear button
// ---------------------------------------------------------------------------

function updateSearchClear() {
  const btn = document.getElementById("search-clear");
  if (btn) btn.hidden = !searchQuery;
}

// ---------------------------------------------------------------------------
// Filter + sort
// ---------------------------------------------------------------------------

function filterSkins() {
  let skins = catalog;
  if (activeFavs) {
    const favs = getFavs();
    skins = skins.filter(s => favs.has(s.id));
  }
  if (activeSystem !== "all") {
    skins = skins.filter(s => (s.systems || []).includes(activeSystem));
  }
  if (activeSource !== "all") {
    skins = skins.filter(s => (s.source || "unknown") === activeSource);
  }
  skins = applySearch(skins);
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
  } else if (sortOrder === "popular") {
    skins.sort((a, b) => (b.downloadCount || 0) - (a.downloadCount || 0));
  }
  return skins;
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

function renderGrid() {
  pushParams();
  const skins = filterSkins();
  const grid = document.getElementById("skin-grid");
  const count = document.getElementById("results-count");
  count.textContent = `${skins.length} skin${skins.length !== 1 ? "s" : ""}`;

  if (!skins.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="icon">🔍</div>
        <h3>No skins found</h3>
        <p>Try a different search or filter, or <button class="link-btn" onclick="clearAllFilters()">clear all filters</button>.</p>
      </div>`;
    return;
  }

  grid.innerHTML = skins.map((skin, i) => cardHTML(skin, i)).join("");

  // Attach click handlers for modal
  grid.querySelectorAll(".skin-card[data-idx]").forEach(card => {
    card.addEventListener("click", e => {
      if (e.target.closest("a")) return; // let download link work normally
      if (e.target.closest(".fav-btn")) return; // handled separately
      openModal(parseInt(card.dataset.idx, 10));
    });
  });

  // Attach fav-btn handlers
  grid.querySelectorAll(".fav-btn").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const skinId = btn.dataset.skinId;
      const isFav = toggleFav(skinId);
      btn.classList.toggle("active", isFav);
      btn.textContent = isFav ? "♥" : "♡";
      btn.setAttribute("aria-label", isFav ? "Remove from favorites" : "Add to favorites");
      updateFavoritesChip();
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

  const isFav  = getFavs().has(skin.id);
  const isNew  = isNewSkin(skin);
  const skinId = escHtml(skin.id || "");

  return `
  <div class="skin-card" data-idx="${idx}" data-skin-id="${skinId}" tabindex="0" role="button" aria-label="View details for ${name}">
    <div class="card-thumb">
      ${thumb}
      ${isNew ? `<span class="new-badge">NEW</span>` : ""}
      <button class="fav-btn${isFav ? " active" : ""}" data-skin-id="${skinId}" aria-label="${isFav ? "Remove from favorites" : "Add to favorites"}" title="Toggle favorite">${isFav ? "♥" : "♡"}</button>
    </div>
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
      ${skin.downloadCount > 0 ? `<span class="dl-count">⬇ ${skin.downloadCount.toLocaleString()}</span>` : ""}
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
  // Push ?skin= to URL
  const skin = filteredCache[idx];
  if (skin?.id) {
    const p = new URLSearchParams(window.location.search);
    p.set("skin", skin.id);
    window.history.replaceState({}, "", `?${p}`);
  }
}

function closeModal() {
  document.getElementById("skin-modal").classList.remove("open");
  document.body.style.overflow = "";
  currentSkinIdx = -1;
  // Remove ?skin= from URL, keep other params
  const p = new URLSearchParams(window.location.search);
  p.delete("skin");
  const qs = p.toString();
  window.history.replaceState({}, "", qs ? `?${qs}` : window.location.pathname);
}

function navigateModal(dir) {
  const next = currentSkinIdx + dir;
  if (next < 0 || next >= filteredCache.length) return;
  currentSkinIdx = next;
  renderModal(filteredCache[currentSkinIdx]);
  // Update ?skin= in URL
  const skin = filteredCache[currentSkinIdx];
  if (skin?.id) {
    const p = new URLSearchParams(window.location.search);
    p.set("skin", skin.id);
    window.history.replaceState({}, "", `?${p}`);
  }
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
  if (skin.downloadCount) meta += `<div class="modal-meta-row"><span>Downloads</span><strong>${skin.downloadCount.toLocaleString()}</strong></div>`;

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
            📋 Copy File URL
          </button>
          <button class="btn btn-outline" onclick="shareLink('${escHtml(skin.id || "")}')" id="share-btn">
            🔗 Share
          </button>
        </div>
        <p class="modal-hint">
          ${isIOS
            ? `Tap <strong>Install in Provenance</strong> — iOS will open the skin directly in the app.`
            : `On iPhone/iPad: tap the download link — iOS will offer to open the skin in Provenance.`
          }
        </p>
        ${renderRelatedSkins(skin)}
      </div>
    </div>
    <div class="modal-counter">${currentSkinIdx + 1} / ${filteredCache.length}</div>`;
}

function renderRelatedSkins(skin) {
  const related = [];
  const seen = new Set([skin.id]);

  // Up to 2 by same author
  if (skin.author) {
    for (const s of filteredCache) {
      if (seen.has(s.id)) continue;
      if (s.author === skin.author) {
        related.push(s);
        seen.add(s.id);
        if (related.length >= 2) break;
      }
    }
  }

  // Up to 2 from same system, different author
  const skinSystems = skin.systems || [];
  for (const s of filteredCache) {
    if (seen.has(s.id)) continue;
    if (s.author === skin.author) continue;
    const sSystems = s.systems || [];
    if (skinSystems.some(sys => sSystems.includes(sys))) {
      related.push(s);
      seen.add(s.id);
      if (related.length >= 4) break;
    }
  }

  if (related.length === 0) return "";

  const cards = related.map(s => {
    const idx = filteredCache.indexOf(s);
    const thumb = s.thumbnailURL
      ? `<img src="${escHtml(s.thumbnailURL)}" class="related-thumb" loading="lazy" onerror="this.style.display='none'">`
      : `<div class="related-thumb" style="display:flex;align-items:center;justify-content:center;font-size:20px;opacity:0.2;">&#127918;</div>`;
    return `<div class="related-card" onclick="openModal(${idx})" role="button" tabindex="0" aria-label="View ${escHtml(s.name || 'skin')}">
      ${thumb}
      <div class="related-name">${escHtml(s.name || "Unnamed")}</div>
    </div>`;
  }).join("");

  return `<div class="related-skins">
  <div class="related-title">Related</div>
  <div class="related-grid">${cards}</div>
</div>`;
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

function shareLink(skinId) {
  const permalink = skinPermalink(skinId);
  // Use native Share sheet on mobile if available
  if (navigator.share) {
    const skin = catalog.find(s => s.id === skinId);
    navigator.share({
      title: skin?.name || "Provenance Skin",
      text: `Check out this skin for Provenance: ${skin?.name || ""}`,
      url: permalink,
    }).catch(() => {});
    return;
  }
  // Fallback: copy permalink to clipboard
  navigator.clipboard.writeText(permalink).then(() => {
    const btn = document.getElementById("share-btn");
    if (!btn) return;
    const orig = btn.textContent;
    btn.textContent = "✓ Link copied!";
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
  updateSearchClear();
  updateChipCounts();
  renderGrid();
});

document.getElementById("search-clear").addEventListener("click", () => {
  searchQuery = "";
  document.getElementById("search").value = "";
  updateSearchClear();
  updateChipCounts();
  renderGrid();
  document.getElementById("search").focus();
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
  const modalOpen = document.getElementById("skin-modal").classList.contains("open");
  if (modalOpen) {
    if (e.key === "Escape")      closeModal();
    if (e.key === "ArrowLeft")   navigateModal(-1);
    if (e.key === "ArrowRight")  navigateModal(1);
    return;
  }
  // "/" focuses search (like GitHub, YouTube, etc.)
  if (e.key === "/" && e.target.tagName !== "INPUT" && e.target.tagName !== "TEXTAREA") {
    e.preventDefault();
    document.getElementById("search").focus();
    document.getElementById("search").select();
  }
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

// ---------------------------------------------------------------------------
// Service worker registration
// ---------------------------------------------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(err => {
      console.warn("Service worker registration failed:", err);
    });
  });
}
