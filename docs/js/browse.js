"use strict";

// First paint reads the slim browse index (scripts/build_catalog.py writes it);
// the full catalog.json is fetched only when a detail view needs the fields the
// index leaves out (version, file size, screenshots).
const BROWSE_INDEX_URL = "catalog.min.json";
const CATALOG_URL = "catalog.json";
// Cards drawn per batch. The rest are appended as the grid scrolls into view,
// so the first paint builds 24 cards instead of the whole catalog.
const GRID_PAGE_SIZE = 24;
// Cards this close to the top get eager, high-priority thumbnails (LCP).
const EAGER_THUMB_COUNT = 4;

// Mature skins (tag set by scripts/content_policy.py or by hand in the skin's
// JSON) are hidden unless the viewer opts in. The choice lives in localStorage
// under the same key as docs/js/mature.js, which handles the static pages.
const MATURE_TAG = "mature";
const MATURE_PREF_KEY = "prov-show-mature";
const REPORT_ISSUE_URL = "https://github.com/Provenance-Emu/skins/issues/new";

function isMatureSkin(skin) {
  return (skin.tags || []).includes(MATURE_TAG);
}

function readMaturePref() {
  try { return localStorage.getItem(MATURE_PREF_KEY) === "1"; } catch { return false; }
}

function saveMaturePref(on) {
  try {
    if (on) localStorage.setItem(MATURE_PREF_KEY, "1"); else localStorage.removeItem(MATURE_PREF_KEY);
  } catch { /* private mode: lasts until reload */ }
}

// Prefilled GitHub issue form (.github/ISSUE_TEMPLATE/report-skin.yml).
function reportUrl(skin) {
  const name = skin.name || "Unnamed skin";
  const q = new URLSearchParams({
    template: "report-skin.yml",
    title: `Report: ${name}`,
    skin_id: skin.id || "",
    skin_name: name,
    skin_page: skin.id ? `https://emuskins.com/s/${skin.id}.html` : "",
  });
  return `${REPORT_ISSUE_URL}?${q}`;
}
// Site root, from this script's own URL (js/browse.js), so author pages in a
// subfolder build the same links as the home page.
const SITE_ROOT = new URL("../", document.currentScript ? document.currentScript.src : window.location.href);

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

// The date "newest" and the NEW badge use: lastUpdated, else addedAt (when the
// skin entered the catalog; see scripts/added_dates.py). Both are YYYY-MM-DD.
function effectiveDate(skin) {
  return skin.lastUpdated || skin.addedAt || null;
}

function isNewSkin(skin) {
  const stamp = effectiveDate(skin);
  if (!stamp) return false;
  const updated = new Date(stamp);
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
  "deltastyles.com":              "DeltaStyles",
  "delta-skins.github.io":       "delta-skins",
  "LitRitt/emuskins":            "LitRitt",
  "Polyphian/deltaEmu":          "Polyphian",
  "masonkoleh/deltaskins":       "masonkoleh",
  "jesseazizi/delta-skins":      "jesseazizi",
  "bradenhirschi/deltaskins":    "bradenhirschi",
  "belle000/Custom-Delta-Skins": "belle000",
  "rajsodhinyu/deltaskins":      "rajsodhinyu",
  "simonevisciano/SV-DeltaSkins":"simonevisciano",
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

let catalog = [];      // what the page shows: allSkins minus mature ones unless the viewer opted in
let allSkins = [];     // everything the index lists
let showMature = false;
let featuredIds = new Set(); // populated after featured.json load
let activeSystem = "all";
let activeSource = "all";
let activeFavs    = false;   // true when "♥ Favorites" chip is selected
let activeDevice  = false;   // true when "My Device" chip is selected
let activeFeature = null;    // tag string or null
let activeHasVariants = false; // true when "Has variants" chip is selected
let searchQuery = "";
let sortOrder = "az"; // az | za | newest

// ---------------------------------------------------------------------------
// URL state — ?system=gba&source=LitRitt&q=depths&sort=newest&skin=abc123
// ---------------------------------------------------------------------------

// `sample` skins are test fixtures: they keep their direct docs/s/ pages but
// stay out of every listing.
function hideSamples(skins) {
  return skins.filter(s => !(s.tags || []).includes("sample"));
}

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
  if (activeHasVariants)      p.set("variants", "1");
  const qs = p.toString();
  window.history.replaceState({}, "", qs ? `?${qs}` : window.location.pathname);
}

// Shared links go to the skin's static page (docs/s/), which carries its own
// title and thumbnail for link previews; crawlers don't run this script.
function skinPermalink(skinId) {
  return new URL(`s/${encodeURIComponent(skinId)}.html`, SITE_ROOT).href;
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
    catalog = hideSamples(window.CATALOG_OVERRIDE);
    return;
  }
  try {
    // Start featured.json alongside the index instead of after it.
    const featuredReq = fetch("featured.json").catch(() => null);
    const data = await fetchBrowseIndex();
    allSkins = hideSamples(data.skins || []);
    showMature = readMaturePref();
    catalog = visibleSkins();

    // Load featured picks
    try {
      const fRes = await featuredReq;
      if (fRes && fRes.ok) {
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
    renderMatureToggle();
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
    if (p.get("variants") === "1") activeHasVariants = true;

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

// Browse index first, full catalog if the index is missing (older deploy,
// offline cache from before the index existed).
async function fetchBrowseIndex() {
  try {
    const res = await fetch(BROWSE_INDEX_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("Browse index unavailable, loading full catalog:", err);
    detailsLoaded = true; // the full catalog already carries every field
    const res = await fetch(CATALOG_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  }
}

// Detail-only fields, merged into catalog entries by id on first use.
let detailsLoaded = false;
let detailsPromise = null;

function ensureDetails() {
  if (detailsLoaded || window.CATALOG_OVERRIDE) return Promise.resolve();
  if (!detailsPromise) {
    detailsPromise = fetch(CATALOG_URL)
      .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
      .then(full => {
        const byId = new Map((full.skins || []).map(s => [s.id, s]));
        // allSkins, not catalog: mature skins stay out of `catalog` until the viewer
        // opts in, and a later opt-in must not show them without these fields.
        for (const skin of allSkins) {
          const f = byId.get(skin.id);
          if (!f) continue;
          for (const k of ["version", "fileSize", "screenshotURLs", "description"]) {
            if (f[k] != null && skin[k] == null) skin[k] = f[k];
          }
        }
        detailsLoaded = true;
      })
      .catch(err => { detailsPromise = null; console.warn("Skin details unavailable:", err); });
  }
  return detailsPromise;
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

function visibleSkins() {
  return showMature ? allSkins : allSkins.filter(s => !isMatureSkin(s));
}

// "Show mature skins (N hidden)". Only drawn when the catalog has any.
function renderMatureToggle() {
  const wrap = document.getElementById("mature-toggle-wrap");
  if (!wrap) return;
  const n = allSkins.filter(isMatureSkin).length;
  wrap.hidden = n === 0;
  const box = document.getElementById("mature-toggle");
  box.checked = showMature;
  document.getElementById("mature-toggle-label").textContent =
    `Show mature skins (${n} ${showMature ? "shown" : "hidden"})`;
  if (!wrap.dataset.wired) {
    wrap.dataset.wired = "1";
    box.addEventListener("change", () => setShowMature(box.checked));
  }
}

function setShowMature(on) {
  if (on && !window.confirm(
      "Mature skins may contain adult content and are hidden by default. Show them on this device?")) {
    document.getElementById("mature-toggle").checked = false;
    return;
  }
  showMature = on;
  saveMaturePref(on);
  catalog = visibleSkins();
  // Rebuild the chips: their counts and lists come from `catalog`.
  document.querySelectorAll("#system-chips .chip").forEach(c => {
    if (c.dataset.system !== "all" && c.dataset.system !== "featured") c.remove();
  });
  document.querySelectorAll("#source-chips .chip").forEach(c => {
    if (c.dataset.source !== "all") c.remove();
  });
  renderStats({});
  renderMatureToggle();
  renderSystemChips();
  addFavoritesChip();
  renderSourceChips();
  addMyDeviceChip();
  renderFeatureChips();
  const fChip = document.getElementById("featured-chip");
  if (fChip && window._featuredOrder) {
    fChip.textContent = `✨ Featured (${window._featuredOrder.filter(id => catalog.some(s => s.id === id)).length})`;
  }
  syncChipActiveState();
  updateChipCounts();
  renderGrid();
}

function renderStats(data) {
  document.getElementById("stat-total").textContent = catalog.length;
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

  if (chips.dataset.wired) return;  // listener survives a chip rebuild
  chips.dataset.wired = "1";
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

  if (container.dataset.wired) return;
  container.dataset.wired = "1";
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
  const variantCards = countVariantCards(catalog);
  catalog.forEach(s => {
    const tags = s.tags || [];
    Object.values(FEATURE_TAGS).forEach(({ tag }) => {
      if (tags.includes(tag)) counts[tag] = (counts[tag] || 0) + 1;
    });
  });

  // Only show row if at least one feature tag has skins
  const total = Object.values(counts).reduce((a, b) => a + b, 0) + variantCards;
  const row = container.closest(".chips-row") || container;
  if (total === 0) { row.style.display = "none"; return; }
  row.style.display = "";

  container.innerHTML = "";
  if (variantCards > 0) {
    const chip = document.createElement("div");
    chip.className = "chip chip-feature" + (activeHasVariants ? " active" : "");
    chip.dataset.hasVariants = "1";
    chip.textContent = `🧩 Has variants (${variantCards})`;
    container.appendChild(chip);
  }
  Object.entries(FEATURE_TAGS).forEach(([key, { label, tag }]) => {
    const count = counts[tag] || 0;
    if (count === 0) return;
    const chip = document.createElement("div");
    chip.className = "chip chip-feature" + (activeFeature === tag ? " active" : "");
    chip.dataset.featureTag = tag;
    chip.textContent = `${label} (${count})`;
    container.appendChild(chip);
  });

  if (container.dataset.wired) return;
  container.dataset.wired = "1";
  container.addEventListener("click", e => {
    const chip = e.target.closest(".chip");
    if (!chip) return;
    if (chip.dataset.hasVariants) {
      activeHasVariants = !activeHasVariants;
    } else if (chip.dataset.featureTag) {
      const tag = chip.dataset.featureTag;
      activeFeature = (activeFeature === tag) ? null : tag;
    } else {
      return;
    }
    container.querySelectorAll(".chip").forEach(c =>
      c.classList.toggle("active", c.dataset.hasVariants ? activeHasVariants : c.dataset.featureTag === activeFeature)
    );
    updateChipCounts();
    renderGrid();
  });
}

// Cards that would show under "Has variants" in `skins`: families of more than
// one file (counted from the whole list) and files with inner variants.
function countVariantCards(skins) {
  const familySize = new Map();
  for (const s of skins) if (s.groupId) familySize.set(s.groupId, (familySize.get(s.groupId) || 0) + 1);
  const seen = new Set();
  let n = 0;
  for (const s of skins) {
    if (s.groupId && familySize.get(s.groupId) > 1) {
      if (!seen.has(s.groupId)) { seen.add(s.groupId); n++; }
    } else if ((s.variants || []).length) {
      n++;
    }
  }
  return n;
}

function updateFeatureChipCounts() {
  const container = document.getElementById("feature-chips");
  if (!container) return;
  let visible = catalog;
  if (activeSystem !== "all") visible = visible.filter(s => (s.systems || []).includes(activeSystem));
  if (activeSource !== "all") visible = visible.filter(s => (s.source || "") === activeSource);
  visible = applySearch(visible);

  const variantChip = container.querySelector(".chip[data-has-variants]");
  if (variantChip) {
    const n = countVariantCards(visible);
    variantChip.textContent = `🧩 Has variants (${n})`;
    variantChip.classList.toggle("chip-empty", n === 0 && !activeHasVariants);
  }

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
  if (activeHasVariants)      parts.push("Has variants");
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
  activeHasVariants = false;
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

// ---------------------------------------------------------------------------
// Variant clustering
// ---------------------------------------------------------------------------

// A variant's own name in its family: `variantLabel`, else the full name.
function variantLabelOf(skin) {
  return skin.variantLabel || skin.name || "";
}

// Card title for a family: the primary's name without its own label.
function familyName(primary) {
  const name = primary.name || "";
  const label = primary.variantLabel || "";
  if (label && name.length > label.length && name.toLowerCase().endsWith(label.toLowerCase())) {
    return name.slice(0, name.length - label.length).replace(/[\s\-\u2014:]+$/, "") || name;
  }
  return name;
}

// Labels of the variants one file brings with it (`variants` from the sidecar).
function innerVariantLabels(skin) {
  return (skin.variants || [])
    .map(v => v && (v.kind === "alt" ? "Alternate layout" : v.label))
    .filter(Boolean);
}

// Collapse entries sharing a `groupId` into a primary card with a `family`
// array attached (one item per downloadable member). Primary is the
// lowest-`groupOrder` member; the array preserves the source's own variant
// ordering. Ungrouped skins pass through unchanged. (The catalog's own
// `variants` field, a single file's inner variants, is left alone.)
function clusterByGroup(skins) {
  const groups = new Map();          // groupId → [members]
  const sequence = [];               // insertion order of primary cards

  for (const s of skins) {
    const gid = s.groupId || "";
    if (!gid) {
      sequence.push(s);
      continue;
    }
    if (!groups.has(gid)) {
      groups.set(gid, []);
      sequence.push({ _groupPlaceholder: gid });
    }
    groups.get(gid).push(s);
  }

  const out = [];
  for (const item of sequence) {
    const gid = item && item._groupPlaceholder;
    if (!gid) { out.push(item); continue; }
    const members = groups.get(gid).slice().sort((a, b) => {
      const ao = a.groupOrder == null ? Infinity : a.groupOrder;
      const bo = b.groupOrder == null ? Infinity : b.groupOrder;
      return ao - bo;
    });
    const primary = members[0];
    const family = members.map((m, i) => ({
      label: variantLabelOf(m),
      downloadURL: m.downloadURL || "",
      thumbnailURL: m.thumbnailURL || "",
      primary: i === 0,
      id: m.id || "",
    }));
    out.push({
      ...primary,
      _clusterCount: members.length,
      _groupName: familyName(primary),
      family,
    });
  }
  return out;
}

// "Has variants": a family of more than one file, or one file with inner variants.
function hasVariants(card) {
  return (card.family && card.family.length > 1) || (card.variants && card.variants.length > 0);
}

// Download several files from one click. Browsers allow a burst of downloads
// only after a prompt, so the clicks are staggered; `btn` shows progress.
function downloadAll(urls, btn) {
  if (!urls.length || (btn && btn.disabled)) return;
  const label = btn ? btn.textContent : "";
  if (btn) btn.disabled = true;
  let i = 0;
  const next = () => {
    if (i >= urls.length) {
      if (btn) {
        btn.textContent = `✓ Started ${urls.length} downloads`;
        setTimeout(() => { btn.textContent = label; btn.disabled = false; }, 3000);
      }
      return;
    }
    if (btn) btn.textContent = `Downloading ${i + 1} of ${urls.length}…`;
    const a = document.createElement("a");
    a.href = urls[i++];
    a.download = "";
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(next, 700);
  };
  next();
}

// Buttons carry their URLs as JSON; capture phase so a click never reaches the
// card's open-the-modal handler. iOS opens each file in an app, so a burst
// can't work there: those pages list per-variant buttons only.
document.addEventListener("click", e => {
  const btn = e.target.closest && e.target.closest("[data-download-all]");
  if (!btn) return;
  e.stopPropagation();
  e.preventDefault();
  try { downloadAll(JSON.parse(btn.dataset.downloadAll), btn); } catch (err) { console.warn(err); }
}, true);

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
    return keepVariantCards(clusterByGroup(skins)); // skip normal sort — featured order is intentional
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
      const da = effectiveDate(a) ? new Date(effectiveDate(a)) : new Date(0);
      const db = effectiveDate(b) ? new Date(effectiveDate(b)) : new Date(0);
      // A bulk import gives hundreds of skins one date; name order keeps ties stable.
      return (db - da) || (a.name || "").localeCompare(b.name || "");
    });
  } else if (sortOrder === "popular") {
    skins.sort((a, b) => (b.downloadCount || 0) - (a.downloadCount || 0));
  }
  return keepVariantCards(clusterByGroup(skins));
}

function keepVariantCards(cards) {
  return activeHasVariants ? cards.filter(hasVariants) : cards;
}

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

function renderGrid() {
  pushParams();
  const skins = filterSkins();
  const grid = document.getElementById("skin-grid");
  const count = document.getElementById("results-count");
  const bundleCount = skins.reduce((n, s) => n + ((s.family && s.family.length > 1) ? 1 : 0), 0);
  const totalVariants = skins.reduce((n, s) => n + (s.family ? s.family.length : 1), 0);
  if (bundleCount > 0) {
    count.textContent = `${skins.length} card${skins.length !== 1 ? "s" : ""} · ${totalVariants} skin${totalVariants !== 1 ? "s" : ""}`;
  } else {
    count.textContent = `${skins.length} skin${skins.length !== 1 ? "s" : ""}`;
  }

  if (!skins.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="icon">🔍</div>
        <h3>No skins found</h3>
        <p>Try a different search or filter, or <button class="link-btn" onclick="clearAllFilters()">clear all filters</button>.</p>
      </div>`;
    gridSkins = [];
    gridRendered = 0;
    updateGridMore();
    return;
  }

  gridSkins = skins;
  gridRendered = 0;
  gridFavs = getFavs();
  grid.innerHTML = "";
  appendGridPage();
}

function downloadAllBtn(family, cls) {
  const urls = family.map(v => v.downloadURL).filter(Boolean);
  if (urls.length < 2) return "";
  return `<button type="button" class="${cls}" data-download-all="${escHtml(JSON.stringify(urls))}">⬇ Download all (${urls.length})</button>`;
}

// Cards drawn so far for the current filter, and the list they come from.
let gridSkins = [];
let gridRendered = 0;
let gridFavs = new Set();
let gridMoreObserver = null;

function appendGridPage() {
  const grid = document.getElementById("skin-grid");
  const from = gridRendered;
  const to = Math.min(from + GRID_PAGE_SIZE, gridSkins.length);
  let html = "";
  for (let i = from; i < to; i++) html += cardHTML(gridSkins[i], i);
  grid.insertAdjacentHTML("beforeend", html);
  gridRendered = to;
  updateGridMore();
}

// "Show more" button under the grid; also fires on its own when scrolled near.
function updateGridMore() {
  const wrap = document.querySelector(".grid-wrap");
  if (!wrap) return;
  let more = document.getElementById("grid-more");
  if (gridRendered >= gridSkins.length) {
    if (more) more.remove();
    if (gridMoreObserver) gridMoreObserver.disconnect();
    return;
  }
  if (!more) {
    more = document.createElement("div");
    more.id = "grid-more";
    more.className = "grid-more";
    more.innerHTML = `<button class="btn btn-outline" type="button"></button>`;
    more.querySelector("button").addEventListener("click", appendGridPage);
    wrap.appendChild(more);
  }
  more.querySelector("button").textContent =
    `Show more (${gridSkins.length - gridRendered} left)`;
  if ("IntersectionObserver" in window) {
    if (!gridMoreObserver) {
      gridMoreObserver = new IntersectionObserver(entries => {
        if (entries.some(e => e.isIntersecting) && gridRendered < gridSkins.length) appendGridPage();
      }, { rootMargin: "800px 0px" });
    }
    gridMoreObserver.disconnect();
    gridMoreObserver.observe(more);
  }
}

// One delegated listener covers cards from every batch.
document.getElementById("skin-grid")?.addEventListener("click", e => {
  const fav = e.target.closest(".fav-btn");
  if (fav) {
    e.stopPropagation();
    const isFav = toggleFav(fav.dataset.skinId);
    gridFavs = getFavs();
    fav.classList.toggle("active", isFav);
    fav.textContent = isFav ? "♥" : "♡";
    fav.setAttribute("aria-label", isFav ? "Remove from favorites" : "Add to favorites");
    updateFavoritesChip();
    return;
  }
  if (e.target.closest("a")) return; // let download link work normally
  const card = e.target.closest(".skin-card[data-idx]");
  if (card) openModal(parseInt(card.dataset.idx, 10));
});

function cardHTML(skin, idx) {
  const isBundle = (skin.family && skin.family.length > 1);
  const inner = isBundle ? [] : innerVariantLabels(skin);
  const displayName = isBundle ? (skin._groupName || familyName(skin)) : (skin.name || "Unnamed Skin");
  const name = escHtml(displayName || "Unnamed Skin");
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

  // Thumbnails are 350x350 PNGs shown in a 16:10 box (object-fit: cover).
  // The first few load eagerly (one is the LCP); the rest wait until near the viewport.
  const eager = idx < EAGER_THUMB_COUNT;
  const thumb = skin.thumbnailURL
    ? `<img src="${escHtml(skin.thumbnailURL)}" alt="${name}" width="350" height="219" decoding="async" ${idx === 0 ? 'fetchpriority="high"' : eager ? "" : 'loading="lazy"'} onerror="this.parentElement.innerHTML='<span class=\\'no-thumb\\'>🎮</span>'">`
    : `<span class="no-thumb">🎮</span>`;

  const isFav  = gridFavs.has(skin.id);
  const isNew  = isNewSkin(skin);
  const isDual = hasDualScreen(skin);
  const skinId = escHtml(skin.id || "");

  const installBtn = isInApp
    ? `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm" onclick="event.stopPropagation()">📲 Install Skin</a>`
    : isIOS
      ? `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm ios-install" onclick="event.stopPropagation()">📲 Install</a>`
      : `<a href="${escHtml(skin.downloadURL)}" class="btn btn-primary btn-sm" download onclick="event.stopPropagation()">⬇ Download</a>`;

  return `
  <div class="skin-card" data-idx="${idx}" data-skin-id="${skinId}" tabindex="0" role="button" aria-label="View details for ${name}">
    <div class="card-thumb">
      ${thumb}
      ${isNew ? `<span class="new-badge">NEW</span>` : ""}
      ${isDual ? `<span class="dual-screen-badge" title="Dual-screen layouts are not active in Provenance yet">DUAL SCREEN</span>` : ""}
      ${isBundle ? `<span class="variant-badge" title="${skin.family.length} variants in this family">${skin.family.length} variants</span>` : ""}
      ${inner.length ? `<span class="variant-badge variant-badge-includes" title="${escHtml(inner.join(", "))}">Includes ${inner.length} variant${inner.length !== 1 ? "s" : ""}</span>` : ""}
      <button class="fav-btn${isFav ? " active" : ""}" data-skin-id="${skinId}" aria-label="${isFav ? "Remove from favorites" : "Add to favorites"}" title="Toggle favorite">${isFav ? "♥" : "♡"}</button>
    </div>
    <div class="card-body">
      <div class="card-name">${name}</div>
      ${author ? `<div class="card-author">${author}</div>` : ""}
      <div class="card-tags">${systems}${tags}</div>
      ${isBundle ? `<div class="card-variant-labels" title="${escHtml(skin.family.map(v => v.label).join(", "))}">${skin.family.map(v => escHtml(v.label)).join(" · ")}</div>` : ""}
      ${inner.length ? `<div class="card-variant-labels" title="${escHtml(inner.join(", "))}">${escHtml(inner.join(" · "))}</div>` : ""}
    </div>
    <div class="card-footer">
      ${isBundle && !isIOS && !isInApp ? downloadAllBtn(skin.family, "btn btn-primary btn-sm") : installBtn}
      ${skin.downloadCount > 0 ? `<span class="dl-count">⬇ ${skin.downloadCount.toLocaleString()}</span>` : ""}
      <a class="report-link" href="${escHtml(reportUrl(skin))}" target="_blank" rel="noopener" title="Report this skin" onclick="event.stopPropagation()">Report</a>
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
  loadModalDetails();
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

// The grid runs on the slim index; version, size and screenshots come from the
// full catalog. Fetch it on first modal open and redraw once it lands.
function loadModalDetails() {
  if (detailsLoaded || window.CATALOG_OVERRIDE) return;
  const idx = currentSkinIdx;
  const id = filteredCache[idx]?.id;
  ensureDetails().then(() => {
    if (!detailsLoaded || currentSkinIdx !== idx) return;
    filteredCache = filterSkins(); // clustered copies predate the merge
    if (filteredCache[idx]?.id === id) renderModal(filteredCache[idx]);
  });
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
  loadModalDetails();
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
  const isBundle = (skin.family && skin.family.length > 1);
  const inner = isBundle ? [] : innerVariantLabels(skin);
  const displayName = isBundle ? (skin._groupName || familyName(skin)) : (skin.name || "Unnamed Skin");
  const name = escHtml(displayName || "Unnamed Skin");
  const authorName = skin.author ? escHtml(skin.author) : null;
  const systems = (skin.systems || []).map(s =>
    `<span class="system-badge clickable-badge" onclick="closeModal();setSystemFilter('${escHtml(s)}')" title="Filter by ${SYSTEM_LABELS[s] || s}">${SYSTEM_LABELS[s] || s}</span>`
  ).join(" ");
  const tags = (skin.tags || []).map(t =>
    `<span class="tag clickable-badge" onclick="closeModal();setQuickSearch('${escHtml(t)}')" title="Search: ${escHtml(t)}">${escHtml(t)}</span>`
  ).join(" ");
  const url = skin.downloadURL || "";
  const ext = url.split(".").pop().toLowerCase();
  // Delta reads .deltaskin only.
  const installApps = ext === "manicskin" ? "Provenance or Manic EMU" : "Provenance, Delta or Manic EMU";
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

  // Bundles have multiple downloadable variants; treating the "primary" as the
  // single canonical download is misleading. For bundles we replace the big
  // primary button with a stack of full-width per-variant buttons (Option 1).
  const verbForVariant = (label) => isInApp
    ? `📲 Install · ${label}`
    : isIOS
      ? `📲 Open · ${label}`
      : `⬇ ${label}`;

  let primaryActionHtml;
  if (isBundle) {
    const buttons = skin.family.map(v => {
      const labelText = escHtml(v.label || "Variant");
      const cls = isIOS && !isInApp ? "btn btn-primary btn-full ios-install" : "btn btn-primary btn-full";
      const downloadAttr = isIOS || isInApp ? "" : "download";
      const text = verbForVariant(labelText);
      return `<a href="${escHtml(v.downloadURL)}" class="${cls}" ${downloadAttr}>${text}</a>`;
    }).join("");
    primaryActionHtml = `
      <div class="modal-variants-pick">
        <div class="modal-variants-pick-title">Pick a variant to download</div>
        ${buttons}
        ${isIOS || isInApp ? "" : downloadAllBtn(skin.family, "btn btn-outline btn-full")}
      </div>`;
  } else {
    primaryActionHtml = isInApp
      ? `<a href="${escHtml(url)}" class="btn btn-primary">📲 Install Skin</a>`
      : isIOS
        ? `<a href="${escHtml(url)}" class="btn btn-primary ios-install">📲 Install</a>`
        : `<a href="${escHtml(url)}" class="btn btn-primary" download>⬇ Download .${escHtml(ext)}</a>`;
  }

  const includesHtml = inner.length ? `
    <div class="modal-includes">
      <div class="modal-variants-pick-title">Includes ${inner.length} variant${inner.length !== 1 ? "s" : ""}</div>
      <div>${escHtml(inner.join(", "))}</div>
      <div class="modal-includes-note">One download. Switch between them in the app.</div>
    </div>` : "";

  const hintText = isBundle
    ? `Each button downloads a different layout from the bundle — install any combination.`
    : isInApp
      ? `Tap <strong>Install Skin</strong> to add it to this app's skin library.`
      : isIOS
        ? `Tap <strong>Install</strong> and iOS opens the skin in ${installApps}. iCube and iFly install skins from their in-app catalog.`
        : `On iPhone or iPad, open this page in Safari and tap the download link to install it in ${installApps}. iCube and iFly install skins from their in-app catalog.`;

  const dualScreenWarning = isDual ? `
    <div class="dual-screen-warning">
      ⚠️ <strong>Dual-screen layouts aren't active in Provenance yet.</strong> DS and 3DS dual-screen support is in development there.
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
        ${includesHtml}
        ${primaryActionHtml}
        <div class="modal-actions${isBundle ? ' modal-actions-secondary' : ''}">
          ${isBundle ? "" : `<button class="btn btn-outline" onclick="copyUrl('${escHtml(url)}')" id="copy-btn">📋 Copy File URL</button>`}
          ${isBundle ? `<button class="btn btn-outline" onclick="copyUrl('${escHtml(url)}')" id="copy-btn">📋 Copy Primary URL</button>` : ""}
          <button class="btn btn-outline" onclick="shareLink('${escHtml(skin.id || "")}')" id="share-btn">
            🔗 Share
          </button>
          <a class="btn btn-outline" href="${escHtml(reportUrl(skin))}" target="_blank" rel="noopener">⚑ Report this skin</a>
          ${retroArchButton(skin)}
        </div>
        <p class="modal-hint">${hintText}</p>
        ${renderRelatedSkins(skin)}
      </div>
    </div>
    <div class="modal-counter">${currentSkinIdx + 1} / ${filteredCache.length}</div>`;
}

/** RetroArch has no "open overlay" hand-off, so the button goes to the converter page, which zips
    the overlay and lists the Files steps. Inside Provenance's web view that page cannot save a zip,
    so the button asks the app to convert and export it instead (provenance://skins/retroarch). */
function retroArchButton(skin) {
  const id = encodeURIComponent(skin.id || "");
  return isInApp
    ? `<a class="btn btn-outline" href="provenance://skins/retroarch?skin=${id}">🕹 Send to RetroArch</a>`
    : `<a class="btn btn-outline" href="retroarch.html?skin=${id}">🕹 Get for RetroArch</a>`;
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
      title: skin?.name || "EmuSkins",
      text: `Controller skin on EmuSkins: ${skin?.name || ""}`,
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
    `width="${sz}" height="${sz}" loading="lazy" decoding="async" onerror="this.onerror=null;this.src='${fb}'">`;
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

// Typing re-filters 1,300 skins and recounts every chip; wait for a pause.
let searchTimer = null;
document.getElementById("search")?.addEventListener("input", e => {
  searchQuery = e.target.value.trim();
  updateSearchClear();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    updateChipCounts();
    renderGrid();
  }, 120);
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
