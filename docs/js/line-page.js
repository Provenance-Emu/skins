// The picker on a line page (docs/l/<id>.html, built by scripts/generate_line_pages.py).
// One control per option; every change resolves to one file through emuskinsLines
// (docs/js/lines.js). Design: specs/2026-11-23-skin-lines-design.md §4, §5, §7.
(function () {
  "use strict";
  const L = globalThis.emuskinsLines;
  const main = document.querySelector("main.line-page");
  if (!L || !main) return;

  const lineId = main.dataset.lineId;
  const HAND_KEY = "emuskins.hand";
  const STORE_KEY = `emuskins.line.${lineId}`;
  const MAX_BUTTONS = 6;   // more values than this become a <select>

  const $ = id => document.getElementById(id);
  const read = key => { try { return localStorage.getItem(key); } catch (e) { return null; } };
  const write = (key, value) => { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } };
  const el = (tag, attrs, text) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (text != null) node.textContent = text;
    return node;
  };

  // What the browser can tell us about the device. A guess: every picker stays changeable.
  function deviceTraits() {
    const ua = navigator.userAgent || "";
    const traits = {};
    const iPad = /iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
    if (iPad) traits.idiom = "ipad";
    else if (/iPhone|iPod/.test(ua)) {
      traits.idiom = "iphone";
      // Screen heights in points: Dynamic Island phones are 852, 874, 932 and 956; notch phones
      // are 812, 844, 896 and 926.
      const h = Math.max(screen.height, screen.width);
      traits.cutout = h === 852 || h === 874 || h >= 932 ? "island" : "notch";
    }
    const hand = read(HAND_KEY);
    if (hand === "left" || hand === "right") traits.hand = hand;
    return traits;
  }

  function storedSelection() {
    try { return JSON.parse(read(STORE_KEY) || "null"); } catch (e) { return null; }
  }

  function fileExt(url) {
    const name = String(url || "").split("?")[0].split("/").pop().toLowerCase();
    return name.includes(".") ? name.split(".").pop() : "deltaskin";
  }

  function fileSize(bytes) {
    if (!bytes) return "";
    return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  fetch(new URL(`../lines/${encodeURIComponent(lineId)}.json`, document.baseURI))
    .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
    .then(start)
    .catch(err => console.warn("Line options unavailable; the default file stays on offer.", err));

  function start(data) {
    const line = data.line;
    const members = data.members || [];
    if (!line || !members.length) return;
    const form = $("line-options");
    const traits = deviceTraits();
    const automatic = new Set();   // axes the device or the hand preference filled in

    const linked = L.memberById(members, new URLSearchParams(location.search).get("skin"));
    let selection;
    if (linked) {
      selection = L.selectionFor(linked);
    } else {
      const stored = storedSelection();
      selection = L.initialSelection(line, members, traits, stored);
      const plain = L.initialSelection(line, members, {}, null);
      for (const axis of line.axes || []) {
        const fromTraits = (axis.role === "device" && traits.idiom) || (axis.role === "hand" && traits.hand);
        if (fromTraits && !(stored && stored[axis.id]) && selection[axis.id] !== plain[axis.id]) automatic.add(axis.id);
      }
    }

    const axes = (line.axes || []).filter(a => (a.values || []).length > 1);
    for (const axis of axes) form.appendChild(buildAxis(axis));
    form.hidden = false;
    form.addEventListener("submit", e => e.preventDefault());
    render(L.resolve(line, members, selection), false);

    function buildAxis(axis) {
      const field = el("fieldset", { class: "line-axis", "data-axis": axis.id });
      const legend = el("legend", {}, axis.label || axis.id);
      legend.appendChild(el("span", { class: "auto", hidden: "" }, "chosen for you"));
      field.appendChild(legend);
      if (axis.role !== "colour" && axis.values.length > MAX_BUTTONS) {
        const select = el("select", { "aria-label": axis.label || axis.id });
        for (const v of axis.values) select.appendChild(el("option", { value: v.id }, v.label || v.id));
        select.addEventListener("change", () => change(axis, select.value));
        field.appendChild(select);
        return field;
      }
      const row = el("div", { class: "line-values" });
      for (const v of axis.values) {
        const label = v.label || v.id;
        const button = axis.role === "colour"
          ? el("button", { type: "button", class: "line-value swatch", "data-value": v.id, title: label, "aria-label": label })
          : el("button", { type: "button", class: "line-value", "data-value": v.id }, label);
        if (axis.role === "colour") {
          if (v.swatch) button.style.background = v.swatch;
          else { button.classList.remove("swatch"); button.textContent = label; }
        }
        button.addEventListener("click", () => change(axis, v.id));
        row.appendChild(button);
      }
      field.appendChild(row);
      return field;
    }

    function change(axis, valueId) {
      automatic.delete(axis.id);
      if (axis.role === "hand") {
        const value = axis.values.find(v => v.id === valueId);
        if (value && value.hand) write(HAND_KEY, value.hand);
      }
      render(L.resolve(line, members, { ...selection, [axis.id]: valueId }, axis.id), true);
    }

    function render(result, remember) {
      const member = result.member;
      selection = result.selection;
      for (const axis of axes) {
        const field = form.querySelector(`[data-axis="${CSS.escape(axis.id)}"]`);
        field.querySelector(".auto").hidden = !automatic.has(axis.id);
        const select = field.querySelector("select");
        if (select) {
          select.value = selection[axis.id];
          for (const option of select.options) {
            const ok = L.isAvailable(line, members, selection, axis.id, option.value);
            option.textContent = (axis.values.find(v => v.id === option.value).label || option.value) + (ok ? "" : " (changes other options)");
          }
          continue;
        }
        for (const button of field.querySelectorAll("[data-value]")) {
          const id = button.dataset.value;
          button.setAttribute("aria-pressed", String(id === selection[axis.id]));
          // Never disabled: picking it works, and the other options follow. The dimmed look
          // and the tooltip say so.
          const ok = L.isAvailable(line, members, selection, axis.id, id);
          button.classList.toggle("is-unavailable", !ok);
          const label = (axis.values.find(v => v.id === id) || {}).label || id;
          button.title = ok ? (axis.role === "colour" ? label : "") : `${label}: changes other options`;
        }
      }

      const img = $("line-img");
      if (img && member.thumbnailURL) img.src = member.thumbnailURL;
      const previews = $("line-previews");
      previews.textContent = "";
      const shots = [member.thumbnailURL, ...(member.screenshotURLs || [])].filter((u, i, all) => u && all.indexOf(u) === i);
      if (shots.length > 1) {
        shots.forEach((url, i) => {
          const a = el("a", { href: url, target: "_blank", rel: "noopener" });
          a.appendChild(el("img", { src: url, loading: "lazy", alt: `${member.name} — preview ${i + 1}` }));
          previews.appendChild(a);
        });
      }

      $("line-selected").textContent = member.name || "";
      $("line-selected").dataset.skinId = member.id;
      $("line-selected-meta").textContent = [fileSize(member.fileSize), member.author ? `by ${member.author}` : ""].filter(Boolean).join(" · ");
      const download = $("line-download");
      download.href = member.downloadURL || "#";
      if (download.hasAttribute("download")) download.textContent = `⬇ Download .${fileExt(member.downloadURL)}`;
      $("line-skin-page").href = `../s/${encodeURIComponent(member.id)}.html`;

      const all = $("line-download-all");
      const family = member.groupId ? members.filter(m => m.groupId === member.groupId) : [];
      const urls = family.map(m => m.downloadURL).filter(Boolean);
      const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
      all.hidden = isIOS || urls.length < 2;
      all.setAttribute("data-download-all", JSON.stringify(urls));
      const what = (line.axes || []).some(a => a.role === "colour") ? "colours" : "variants";
      if (!all.disabled) all.textContent = `⬇ All ${what} for this layout (${urls.length})`;

      const url = new URL(location.href);
      url.searchParams.set("skin", member.id);
      history.replaceState({}, "", url);
      if (remember) write(STORE_KEY, JSON.stringify(selection));
    }
  }
})();
