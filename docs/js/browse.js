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
// Detect WKWebView: on iOS, Safari includes "Safari/" in UA; a bare WKWebView does not.
const isInApp = isIOS && !/Safari\//.test(navigator.userAgent);

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

// Systems whose dual-screen layout support is not yet active in Provenance
const DUAL_SCREEN_SYSTEMS = new Set(["nds", "threeDS"]);
const DUAL_SCREEN_ISSUE_URL = "https://github.com/Provenance-Emu/Provenance/issues/2540";

function hasDualScreen(skin) {
  return (skin.systems || []).some(s => DUAL_SCREEN_SYSTEMS.has(s));
}

// Feature tag definitions — chips are shown only when skins with these tags exist
const FEATURE_TAGS = {
  animated:     { label: "🌊 Animated",   tag: "animated" },
  keyboard:     { label: "⌨️ Keyboard",    tag: "keyboard" },
  multiTheme:   { label: "🎨 Multi-Theme", tag: "multi-theme" },
  haptics:      { label: "📳 Haptics",     tag: "haptics" },
};

let catalog = [];
let featuredIds = new Set(); // populated after featured.json load
let activeSystem = "all";
let activeSource = "all";
let activeFavs    = false;   // true when "♥ Favorites" chip is selected
let activeDevice  = false;   // true when "My Device" chip is selected
let activeFeature = null;    // tag string or null
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
  if (activeFeature)          p.set("feature", activeFeature);
  const qs = p.toString();
  window.history.replaceState({}, "", qs ? `?${qs}` : window.location.pathname);
}

function skinPermalink(skinId) {
  const p = new URLSearchParams(window.location.search);
  p.set("skin", skinId);
  return `${window.location.origin}${window.location.pathname}?${p}`;
}

// ---------------------------------------------------------------------------
// Quick-filter helpers (called by clickable badges/labels)
// ---------------------------------------------------------------------------

function setSystemFilter(sys) {
  activeFavs = false;
  activeSystem = sys === activeSystem ? "all" : sys;
  syncChipActiveState();
  updateChipCounts();
  renderGrid();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setSourceFilter(src) {
  activeDevice = false;
  activeSource = src === activeSource ? "all" : src;
  syncChipActiveState();
  updateChipCounts();
  renderGrid();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setQuickSearch(query) {
  searchQuery = query;
  const el = document.getElementById("search");
  if (el) el.value = query;
  updateSearchClear();
  updateChipCounts();
  renderGrid();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------

async function loadCatalog() {
  // Author/system pages can inject skins directly to avoid a fetch.
  if (window.CATALOG_OVERRIDE) {
    catalog = window.CATALOG_OVERRIDE;
    return;
  }
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
    renderFeatureChips();

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
    if (p.get("feature")) activeFeature = p.get("feature");

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

  updateFeatureChipCounts();
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
// Feature chips (animated, keyboard, multi-theme, haptics)
// ---------------------------------------------------------------------------

function renderFeatureChips() {
  const container = document.getElementById("feature-chips");
  if (!container) return;

  // Count skins with each feature tag
  const counts = {};
  catalog.forEach(s => {
    const tags = s.tags || [];
    Object.values(FEATURE_TAGS).forEach(({ tag }) => {
      if (tags.includes(tag)) counts[tag] = (counts[tag] || 0) + 1;
    });
  });

  // Only show row if at least one feature tag has skins
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const row = container.closest(".chips-row") || container;
  if (total === 0) { row.style.display = "none"; return; }
  row.style.display = "";

  container.innerHTML = "";
  Object.entries(FEATURE_TAGS).forEach(([key, { label, tag }]) => {
    const count = counts[tag] || 0;
    if (count === 0) return;
    const chip = document.createElement("div");
    chip.className = "chip chip-feature" + (activeFeature === tag ? " active" : "");
    chip.dataset.featureTag = tag;
    chip.textContent = `${label} (${count})`;
    container.appendChild(chip);
  });

  container.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip || !chip.dataset.featureTag) return;
    const tag = chip.dataset.featureTag;
    activeFeature = (activeFeature === tag) ? null : tag;
    container.querySelectorAll(".chip").forEach(c =>
      c.classList.toggle("active", c.dataset.featureTag === activeFeature)
    );
    updateChipCounts();
    renderGrid();
  });
}

function updateFeatureChipCounts() {
  const container = document.getElementById("feature-chips");
  if (!container) return;
  let visible = catalog;
  if (activeSystem !== "all") visible = visible.filter(s => (s.systems || []).includes(activeSystem));
  if (activeSource !== "all") visible = visible.filter(s => (s.source || "") === activeSource);
  visible = applySearch(visible);

  container.querySelectorAll(".chip[data-feature-tag]").forEach(chip => {
    const tag = chip.dataset.featureTag;
    const n = visible.filter(s => (s.tags || []).includes(tag)).length;
    const def = Object.values(FEATURE_TAGS).find(f => f.tag === tag);
    chip.textContent = `${def ? def.label : tag} (${n})`;
    chip.classList.toggle("chip-empty", n === 0 && activeFeature !== tag);
  });
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
  if (activeFeature) {
    const def = Object.values(FEATURE_TAGS).find(f => f.tag === activeFeature);
    parts.push(def ? def.label : activeFeature);
  }
  if (searchQuery)            parts.push(`"${searchQuery}"`);

  // Use inline style (not hidden attribute) — avoids CSS specificity fights with display:flex
  if (parts.length === 0) {
    container.style.display = "none";
    container.innerHTML = "";
    return;
  }
  container.style.display = "";
  container.innerHTML =
    `<span class="active-filter-label">Showing: ${parts.join(" · ")}</span>` +
    `<button class="clear-filters-btn" onclick="clearAllFilters()">✕ Clear all</button>`;
}

function clearAllFilters() {
  activeSystem = "all";
  activeSource = "all";
  activeFavs   = false;
  activeDevice  = false;
  activeFeature = null;
  searchQuery = "";
  sortOrder = "az";
  const search = document.getElementById("search");
  if (search) search.value = "";
  const sort = document.getElementById("sort-select");
  if (sort) sort.value = "az";
  updateSearchClear();
  updateFavoritesChip();
  syncChipActiveState();
  // Deactivate all feature chips
  document.querySelectorAll("#feature-chips .chip").forEach(c => c.classList.remove("active"));
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
  if (activeSystem === "featured") {
    // Filter to featured IDs and preserve their defined order
    const order = window._featuredOrder || [];
    skins = order.map(id => skins.find(s => s.id === id)).filter(Boolean);
    skins = applySearch(skins);
    if (activeDevice && detectedDevice) {
      skins = skins.filter(s => (s.deviceSupport || []).length === 0 || (s.deviceSupport || []).includes(detectedDevice));
    }
    return skins; // skip normal sort — featured order is intentional
  }
  if (activeSystem !== "all") {
    skins = skins.filter(s => (s.systems || []).includes(activeSystem));
  }
  if (activeSource !== "all") {
    skins = skins.filter(s => (s.source || "unknown") === activeSource);
  }
  if (activeDevice && detectedDevice) {
    skins = skins.filter(s => (s.deviceSupport || []).length === 0 || (s.deviceSupport || []).includes(detectedDevice));
  }
  if (activeFeature) {
    skins = skins.filter(s => (s.tags || []).includes(activeFeature));
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
  const authorName = skin.author ? escHtml(skin.author) : "";
  const avatarHtml = authorName
    ? authorAvatarHtml(authorName, skin.source, 20)
    : "";
  const author = authorName
    ? `${avatarHtml}<button class="inline-filter-btn" onclick="event.stopPropagation();setQuickSearch('${authorName}')" title="Browse skins by ${authorName}">${authorName}</button>`
    : "";
  const systems = (skin.systems || []).map(s =>
    `<span class="system-badge clickable-badge" onclick="event.stopPropagation();setSystemFilter('${escHtml(s)}')" title="Filter by ${SYSTEM_LABELS[s] || s}">${SYSTEM_LABELS[s] || s}</span>`
  ).join("");
  const tags = (skin.tags || []).slice(0, 3).map(t =>
    `<span class="tag clickable-badge" onclick="event.stopPropagation();setQuickSearch('${escHtml(t)}')" title="Search: ${escHtml(t)}">${escHtml(t)}</span>`
  ).join("");

  const thumb = skin.thumbnailURL
    ? `<img src="${escHtml(skin.thumbnailURL)}" alt="${name}" loading="lazy" onerror="this.parentElement.innerHTML='<span class=\\'no-thumb\\'>🎮</span>'">`
    : `<span class="no-thumb">🎮</span>`;

  const isFav  = getFavs().has(skin.id);
  const isNew  = isNewSkin(skin);
  const isDual = hasDualScreen(skin);
  const skinId = escHtml(skin.id || "");

  const installBtn = isInApp
    ? `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm" onclick="event.stopPropagation()">📲 Install Skin</a>`
    : isIOS
      ? `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm ios-install" onclick="event.stopPropagation()">📲 Open in Provenance</a>`
      : `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm" download onclick="event.stopPropagation()">⬇ Download</a>`;

  return `
  <div class="skin-card" data-idx="${idx}" data-skin-id="${skinId}" tabindex="0" role="button" aria-label="View details for ${name}">
    <div class="card-thumb">
      ${thumb}
      ${isNew ? `<span class="new-badge">NEW</span>` : ""}
      ${isDual ? `<span class="dual-screen-badge" title="Dual-screen layout not yet active in Provenance">COMING SOON</span>` : ""}
      <button class="fav-btn${isFav ? " active" : ""}" data-skin-id="${skinId}" aria-label="${isFav ? "Remove from favorites" : "Add to favorites"}" title="Toggle favorite">${isFav ? "♥" : "♡"}</button>
    </div>
    <div class="card-body">
      <div class="card-name">${name}</div>
      ${author ? `<div class="card-author">${author}</div>` : ""}
      <div class="card-tags">${systems}${tags}</div>
    </div>
    <div class="card-footer">
      ${installBtn}
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

// ---------------------------------------------------------------------------
// Image gallery (multiple screenshots per skin)
// ---------------------------------------------------------------------------
let currentGalleryIdx = 0;
let currentGalleryImages = [];

function buildGallery(skin, name) {
  const images = [];
  if (skin.thumbnailURL) images.push(skin.thumbnailURL);
  (skin.screenshotURLs || []).forEach(u => { if (u && u !== skin.thumbnailURL) images.push(u); });
  if (!images.length) return `<div class="modal-no-thumb">🎮</div>`;
  currentGalleryIdx = 0;
  currentGalleryImages = images;
  if (images.length === 1) {
    return `<img id="gallery-img" src="${escHtml(images[0])}" alt="${name}" onerror="this.remove()">`;
  }
  const dots = images.map((_, i) =>
    `<button class="img-dot${i === 0 ? " active" : ""}" onclick="setGalleryImg(${i})" aria-label="Image ${i + 1}"></button>`
  ).join("");
  return `<div class="img-gallery-main">
    <img id="gallery-img" src="${escHtml(images[0])}" alt="${name}" onerror="this.remove()">
    <button class="img-arrow img-arrow-prev" onclick="stepGallery(-1)" aria-label="Previous image">‹</button>
    <button class="img-arrow img-arrow-next" onclick="stepGallery(1)" aria-label="Next image">›</button>
    <div class="img-dots">${dots}</div>
  </div>`;
}

function setGalleryImg(i) {
  if (i < 0 || i >= currentGalleryImages.length) return;
  currentGalleryIdx = i;
  const el = document.getElementById("gallery-img");
  if (el) el.src = currentGalleryImages[i];
  document.querySelectorAll(".img-dot").forEach((d, j) => d.classList.toggle("active", j === i));
}

function stepGallery(dir) {
  setGalleryImg((currentGalleryIdx + dir + currentGalleryImages.length) % currentGalleryImages.length);
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
  const authorName = skin.author ? escHtml(skin.author) : null;
  const systems = (skin.systems || []).map(s =>
    `<span class="system-badge clickable-badge" onclick="closeModal();setSystemFilter('${escHtml(s)}')" title="Filter by ${SYSTEM_LABELS[s] || s}">${SYSTEM_LABELS[s] || s}</span>`
  ).join(" ");
  const tags = (skin.tags || []).map(t =>
    `<span class="tag clickable-badge" onclick="closeModal();setQuickSearch('${escHtml(t)}')" title="Search: ${escHtml(t)}">${escHtml(t)}</span>`
  ).join(" ");
  const url = skin.downloadURL || "";
  const ext = url.split(".").pop().toLowerCase();
  const isDual = hasDualScreen(skin);

  const thumb = buildGallery(skin, name);

  const modalAvatar = authorName
    ? authorAvatarHtml(authorName, skin.source, 32)
    : "";

  let meta = "";
  if (authorName) meta += `<div class="modal-meta-row"><span>Author</span><strong class="modal-author-inner">${modalAvatar}<button class="inline-filter-btn" onclick="closeModal();setQuickSearch('${authorName}')" title="Browse skins by ${authorName}">${authorName}</button></strong></div>`;
  if (skin.version) meta += `<div class="modal-meta-row"><span>Version</span><strong>${escHtml(skin.version)}</strong></div>`;
  if (skin.lastUpdated) {
    const d = new Date(skin.lastUpdated).toLocaleDateString("en-US", {year:"numeric",month:"short",day:"numeric"});
    meta += `<div class="modal-meta-row"><span>Updated</span><strong>${d}</strong></div>`;
  }
  if (skin.fileSize) {
    const kb = Math.round(skin.fileSize / 1024);
    meta += `<div class="modal-meta-row"><span>Size</span><strong>${kb > 1024 ? (kb/1024).toFixed(1)+"MB" : kb+"KB"}</strong></div>`;
  }
  if (skin.source) {
    const srcLabel = escHtml(SOURCE_LABELS[skin.source] || skin.source);
    meta += `<div class="modal-meta-row"><span>Source</span><strong><button class="inline-filter-btn" onclick="closeModal();setSourceFilter('${escHtml(skin.source)}')" title="Browse ${srcLabel} skins">${srcLabel}</button></strong></div>`;
  }
  if (skin.downloadCount) meta += `<div class="modal-meta-row"><span>Downloads</span><strong>${skin.downloadCount.toLocaleString()}</strong></div>`;

  const installBtn = isInApp
    ? `<a href="${escHtml(url)}" class="btn btn-primary">📲 Install Skin</a>`
    : isIOS
      ? `<a href="${escHtml(url)}" class="btn btn-primary ios-install">📲 Open in Provenance</a>`
      : `<a href="${escHtml(url)}" class="btn btn-primary" download>⬇ Download .${escHtml(ext)}</a>`;

  const hintText = isInApp
    ? `Tap <strong>Install Skin</strong> to add it to your Provenance library.`
    : isIOS
      ? `Tap <strong>Open in Provenance</strong> — iOS will open the skin directly in the app.`
      : `On iPhone/iPad: open this page in Safari, then tap the download link to install in Provenance.`;

  const dualScreenWarning = isDual ? `
    <div class="dual-screen-warning">
      ⚠️ <strong>Dual-screen layout not yet active.</strong> DS and 3DS dual-screen skin support is in development.
      <a href="${DUAL_SCREEN_ISSUE_URL}" target="_blank" rel="noopener">Track progress →</a>
    </div>` : "";

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
        ${authorName ? `<div class="modal-author">by <button class="inline-filter-btn" onclick="closeModal();setQuickSearch('${authorName}')" title="Browse skins by ${authorName}">${authorName}</button></div>` : ""}
        <div class="modal-systems">${systems}</div>
        ${tags ? `<div class="modal-tags">${tags}</div>` : ""}
        ${meta ? `<div class="modal-meta">${meta}</div>` : ""}
        ${dualScreenWarning}
        <div class="modal-actions">
          ${installBtn}
          <button class="btn btn-outline" onclick="copyUrl('${escHtml(url)}')" id="copy-btn">
            📋 Copy File URL
          </button>
          <button class="btn btn-outline" onclick="shareLink('${escHtml(skin.id || "")}')" id="share-btn">
            🔗 Share
          </button>
        </div>
        <p class="modal-hint">${hintText}</p>
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
// Author avatars
// ---------------------------------------------------------------------------

/** Derive GitHub username from a skin's source field (e.g. "LitRitt/emuskins" → "LitRitt"). */
function githubUsernameFromSource(source) {
  if (!source) return null;
  const m = source.match(/^([A-Za-z0-9_-]+)\/[A-Za-z0-9_.-]+$/);
  return m ? m[1] : null;
}

/** Build a data: URI SVG with a colored initial for fallback avatars. */
function makeInitialAvatarUrl(name, size) {
  const initial = (name || "?").charAt(0).toUpperCase();
  let h = 0;
  for (let i = 0; i < name.length; i++) h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  const hue = Math.abs(h) % 360;
  const r = size / 2;
  const fs = Math.floor(size * 0.44);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">` +
    `<circle cx="${r}" cy="${r}" r="${r}" fill="hsl(${hue},62%,40%)"/>` +
    `<text x="${r}" y="${r}" dy=".36em" text-anchor="middle" ` +
    `font-family="system-ui,sans-serif" font-size="${fs}" font-weight="700" fill="white">${initial}</text>` +
    `</svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

/**
 * Build an <img> tag for an author avatar.
 * Tries GitHub avatar first; falls back to colored initial circle on error.
 */
function authorAvatarHtml(authorName, source, size) {
  if (!authorName) return "";
  const sz = size || 28;
  const fallback = makeInitialAvatarUrl(authorName, sz);
  const ghUser = githubUsernameFromSource(source);
  const ghUrl = ghUser
    ? `https://github.com/${ghUser}.png?size=${sz * 2}`
    : null;
  const src = escHtml(ghUrl || fallback);
  const fb = escHtml(fallback);
  return `<img class="author-avatar" src="${src}" alt="${escHtml(authorName)}" ` +
    `width="${sz}" height="${sz}" onerror="this.onerror=null;this.src='${fb}'">`;
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

document.getElementById("search")?.addEventListener("input", e => {
  searchQuery = e.target.value.trim();
  updateSearchClear();
  updateChipCounts();
  renderGrid();
});

document.getElementById("search-clear")?.addEventListener("click", () => {
  searchQuery = "";
  document.getElementById("search").value = "";
  updateSearchClear();
  updateChipCounts();
  renderGrid();
  document.getElementById("search").focus();
});

document.getElementById("sort-select")?.addEventListener("change", e => {
  sortOrder = e.target.value;
  renderGrid();
});

// Modal backdrop click
document.getElementById("skin-modal")?.addEventListener("click", e => {
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
document.getElementById("skin-grid")?.addEventListener("keydown", e => {
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
