"use strict";

// Mature-skin handling for the static pages: system pages, author pages and
// single-skin pages. The home page does the same in browse.js; both read the
// one localStorage key below, so the choice follows the viewer across pages.
//
//   system/author pages: #mature-note says how many mature skins the page hides
//     and toggles them. They are not in the page HTML. When the viewer opts in,
//     this script lists them from catalog.min.json into #mature-grid.
//   skin pages: <main data-mature> stays hidden behind #mature-gate until the
//     viewer confirms (or has already opted in). Its thumbnail is data-src, so
//     nothing loads before that.
(function () {
  const PREF_KEY = "prov-show-mature";
  const TAG = "mature";
  const SITE_ROOT = new URL("../", document.currentScript ? document.currentScript.src : window.location.href);
  const REPORT_ISSUE_URL = "https://github.com/Provenance-Emu/skins/issues/new";

  function prefOn() {
    try { return localStorage.getItem(PREF_KEY) === "1"; } catch (e) { return false; }
  }

  function savePref(on) {
    try {
      if (on) localStorage.setItem(PREF_KEY, "1"); else localStorage.removeItem(PREF_KEY);
    } catch (e) { /* private mode: the choice lasts until reload */ }
  }

  function confirmOptIn() {
    return window.confirm(
      "Mature skins may contain adult content and are hidden by default. Show them on this device?");
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

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

  // -------------------------------------------------------------------------
  // System and author pages
  // -------------------------------------------------------------------------

  function matureCard(skin) {
    const page = new URL(`s/${encodeURIComponent(skin.id)}.html`, SITE_ROOT).href;
    const card = el("article", "skin-card");
    const thumb = el("div", "card-thumb");
    if (skin.thumbnailURL) {
      const img = el("img");
      img.src = skin.thumbnailURL;
      img.alt = skin.name || "";
      img.loading = "lazy";
      img.decoding = "async";
      img.width = 350;
      img.height = 219;
      img.addEventListener("error", () => { img.style.display = "none"; });
      thumb.appendChild(img);
    }
    const body = el("div", "card-body");
    const name = el("a", "card-name", skin.name || "Unnamed Skin");
    name.href = page;
    name.style.color = "inherit";
    body.appendChild(name);
    if (skin.author) body.appendChild(el("div", "card-author", skin.author));
    const foot = el("div", "card-footer");
    const open = el("a", "btn btn-success btn-sm", "View");
    open.href = page;
    const report = el("a", "report-link", "Report");
    report.href = reportUrl(skin);
    report.target = "_blank";
    report.rel = "noopener";
    report.title = "Report this skin";
    foot.append(open, report);
    card.append(thumb, body, foot);
    return card;
  }

  async function initListing(note) {
    const count = parseInt(note.dataset.count, 10) || 0;
    if (!count) return;
    const wrap = document.getElementById("mature-wrap");
    const grid = document.getElementById("mature-grid");
    const text = document.getElementById("mature-note-text");
    const button = document.getElementById("mature-toggle");
    const noun = count === 1 ? "mature skin" : "mature skins";
    let loaded = false;

    async function load() {
      if (loaded) return;
      loaded = true;
      try {
        const res = await fetch(new URL("catalog.min.json", SITE_ROOT));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const key = note.dataset.key;
        const scope = note.dataset.scope;
        const skins = (data.skins || []).filter(s =>
          (s.tags || []).includes(TAG) &&
          (scope === "system" ? (s.systems || []).includes(key) : s.author === key));
        skins.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
        skins.forEach(s => grid.appendChild(matureCard(s)));
      } catch (e) {
        loaded = false;
        grid.appendChild(el("p", "mature-error", "Couldn't load the mature skins. Try again later."));
      }
    }

    function render() {
      const on = prefOn();
      text.textContent = on ? `Showing ${count} ${noun}.` : `${count} ${noun} hidden.`;
      button.textContent = on ? "Hide mature skins" : "Show mature skins";
      wrap.hidden = !on;
      if (on) load();
    }

    button.addEventListener("click", () => {
      if (prefOn()) { savePref(false); } else if (confirmOptIn()) { savePref(true); } else { return; }
      render();
    });
    note.hidden = false;
    render();
  }

  // -------------------------------------------------------------------------
  // Single-skin pages
  // -------------------------------------------------------------------------

  function initGate(page) {
    const gate = document.getElementById("mature-gate");
    if (!gate) { page.hidden = false; return; }

    function reveal() {
      page.querySelectorAll("img[data-src]").forEach(img => {
        img.src = img.dataset.src;
        img.removeAttribute("data-src");
      });
      page.hidden = false;
      gate.hidden = true;
    }

    if (prefOn()) { reveal(); return; }
    gate.hidden = false;
    const go = document.getElementById("mature-gate-continue");
    if (go) go.addEventListener("click", reveal);
  }

  const note = document.getElementById("mature-note");
  if (note) initListing(note);
  const page = document.querySelector("main[data-mature]");
  if (page) initGate(page);
})();
