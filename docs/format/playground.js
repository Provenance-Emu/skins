/* EmuSkins — the format 2.0 playground (docs/format/playground.html): a source editor beside a live preview and
   the validator's report. Everything runs in the page. The draft is kept in localStorage, and a share link holds
   the source in the URL fragment, which browsers don't send to the server. */
import { ALL_FEATURES, loadDocumentJSON, traitSetsFor, usedFeatures, validateText } from "../js/skin2/index.js";
import { DEFAULT_FAMILY, FAMILY_LABELS, formatJSON, locatePointer, renderPreview } from "./preview.js";

const DRAFT_KEY = "emuskins.format.playground.draft";
const DEFAULT_EXAMPLE = "gamecube";
const $ = (id) => document.getElementById(id);

const editor = $("pg-source");
const device = $("pg-device");
const status = $("pg-status");
const issues = $("pg-issues");
const note = $("pg-note");
const pickers = { family: $("pg-family"), theme: $("pg-theme"), variant: $("pg-variant") };
const orientationButtons = [...document.querySelectorAll("[data-orientation-button]")];
const state = { orientation: "portrait", family: DEFAULT_FAMILY, theme: "", variant: "", guides: false };

let loaded = "";
let ticket = 0;
let timer;

// ── Share links ────────────────────────────────────────────────────────────

async function pack(text) {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("deflate-raw"));
  const bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function unpack(code) {
  const binary = atob(code.replace(/-/g, "+").replace(/_/g, "/"));
  const stream = new Blob([Uint8Array.from(binary, (c) => c.charCodeAt(0))]).stream()
    .pipeThrough(new DecompressionStream("deflate-raw"));
  return new Response(stream).text();
}

async function fetchExample(name) {
  if (!/^[a-z0-9-]+$/.test(name)) throw new Error("Unknown example.");
  const response = await fetch(`examples/${name}.json`);
  if (!response.ok) throw new Error("Could not load that example.");
  return formatJSON(JSON.parse(await response.text()));
}

// ── Report and preview ─────────────────────────────────────────────────────

function fill(select, options, wanted) {
  select.replaceChildren(...options.map(([value, label]) => Object.assign(document.createElement("option"), { value, textContent: label })));
  select.value = options.some(([value]) => value === wanted) ? wanted : options[0]?.[0] ?? "";
  select.closest("label").hidden = options.length < 2;
  return select.value;
}

function updatePickers(doc) {
  const traits = traitSetsFor(doc.bake?.traits);
  const families = [...new Set(traits.map((trait) => trait.family))];
  state.family = fill(pickers.family, families.map((family) => [family, FAMILY_LABELS[family] ?? family]), state.family);
  state.theme = fill(pickers.theme, [["", "Default theme"], ...doc.themeNames.map((name) => [name, name])], state.theme);
  state.variant = fill(pickers.variant,
    [["", "No variant"], ...Object.entries(doc.variants).map(([name, variant]) => [name, variant.label ?? name])], state.variant);
  const available = traits.filter((trait) => trait.family === state.family).map((trait) => trait.orientation);
  if (!available.includes(state.orientation)) state.orientation = available[0] ?? "portrait";
  for (const button of orientationButtons) {
    button.disabled = !available.includes(button.value);
    button.setAttribute("aria-pressed", String(button.value === state.orientation));
  }
}

function showIssues(report) {
  issues.replaceChildren(...report.issues.map((issue) => {
    const item = document.createElement("li");
    item.className = "issue issue-" + issue.severity;
    const badge = Object.assign(document.createElement("span"), { className: "issue-badge", textContent: issue.severity });
    const message = Object.assign(document.createElement("span"), { className: "issue-message", textContent: issue.message });
    item.append(badge, message);
    if (issue.pointer) {
      const jump = Object.assign(document.createElement("button"), { type: "button", className: "issue-pointer", textContent: issue.pointer });
      jump.title = "Select this place in the source";
      jump.addEventListener("click", () => select(issue.pointer));
      item.append(jump);
    }
    return item;
  }));
  issues.hidden = report.issues.length === 0;
}

function select(pointer) {
  const range = locatePointer(editor.value, pointer);
  if (!range) return;
  editor.focus();
  editor.setSelectionRange(range.start, range.end);
  const line = editor.value.slice(0, range.start).split("\n").length;
  const lineHeight = parseFloat(getComputedStyle(editor).lineHeight) || 20;
  editor.scrollTop = Math.max(0, (line - 4) * lineHeight);
}

async function refresh() {
  const text = editor.value;
  const current = ++ticket;
  try {
    localStorage.setItem(DRAFT_KEY, text);
  } catch { /* Private browsing or a full quota: the draft just isn't kept. */ }

  const report = validateText(text);
  showIssues(report);
  const count = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const summary = report.errors.length ? count(report.errors.length, "error")
    : report.warnings.length ? `Valid, with ${count(report.warnings.length, "warning")}` : "Valid";
  status.dataset.state = report.errors.length ? "error" : report.warnings.length ? "warning" : "ok";

  if (!report.document) {
    status.textContent = `${summary}. The preview shows the last source that loaded.`;
    device.classList.add("is-stale");
    return;
  }
  updatePickers(report.document);
  try {
    device.classList.add("is-busy");
    const { canvas, trait, controls } = await renderPreview(text, {
      ...state, theme: state.theme || undefined, variant: state.variant || undefined,
    });
    if (current !== ticket) return;
    device.dataset.orientation = trait.orientation;
    device.dataset.family = trait.family;
    device.replaceChildren(canvas);
    device.classList.remove("is-stale");
    status.textContent = `${summary}. ${count(controls, "control")} at ${trait.size.width} × ${trait.size.height} pt.`;
  } catch (error) {
    if (current !== ticket) return;
    device.classList.add("is-stale");
    status.dataset.state = "error";
    status.textContent = `${summary}. Could not draw the preview: ${error.detail ?? error.message}`;
  } finally {
    if (current === ticket) device.classList.remove("is-busy");
  }
}

function schedule() {
  clearTimeout(timer);
  timer = setTimeout(refresh, 250);
}

function setSource(text, { asLoaded = true } = {}) {
  editor.value = text;
  if (asLoaded) loaded = text;
  editor.scrollTop = 0;
  void refresh();
}

function say(message) {
  note.textContent = message;
  clearTimeout(say.timer);
  say.timer = setTimeout(() => { note.textContent = ""; }, 4000);
}

// ── Toolbar ────────────────────────────────────────────────────────────────

$("pg-example").addEventListener("change", async (event) => {
  const name = event.target.value;
  event.target.value = "";
  if (!name) return;
  const dirty = editor.value.trim() && editor.value !== loaded;
  if (dirty && !confirm("Replace your source with this example?")) return;
  try {
    setSource(await fetchExample(name));
    history.replaceState(null, "", `?example=${name}`);
  } catch (error) {
    say(error.message);
  }
});

$("pg-format").addEventListener("click", () => {
  try {
    setSource(formatJSON(JSON.parse(editor.value)), { asLoaded: false });
  } catch {
    say("Fix the JSON syntax error first.");
  }
});

$("pg-requires").addEventListener("click", () => {
  let json;
  try {
    json = JSON.parse(editor.value);
    const base = loadDocumentJSON(json);
    const documents = [base,
      ...base.themeNames.map((theme) => loadDocumentJSON(json, { theme })),
      ...Object.keys(base.variants).map((variant) => loadDocumentJSON(json, { variant }))];
    const used = usedFeatures(json, documents);
    const requires = ALL_FEATURES.filter((name) => used.has(name));
    const range = json.requires === undefined ? undefined : locatePointer(editor.value, "/requires");
    const text = range
      ? editor.value.slice(0, range.start) + JSON.stringify(requires, null, 2).replace(/\n/g, "\n  ") + editor.value.slice(range.end)
      : formatJSON({ formatVersion: json.formatVersion, requires, ...json });
    setSource(text, { asLoaded: false });
    say(`requires now lists ${requires.length} feature${requires.length === 1 ? "" : "s"}.`);
  } catch (error) {
    say("Fix the other errors first: " + (error.detail ?? error.message));
  }
});

$("pg-download").addEventListener("click", () => {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([editor.value], { type: "application/json" }));
  link.download = "skin.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
});

$("pg-share").addEventListener("click", async () => {
  try {
    history.replaceState(null, "", location.pathname + "#s=" + await pack(editor.value));
    await navigator.clipboard.writeText(location.href);
    say(location.href.length > 8000 ? "Link copied. It is long, so some apps may cut it short." : "Link copied.");
  } catch {
    say("The link is in the address bar. Copy it from there.");
  }
});

for (const [name, picker] of Object.entries(pickers)) {
  picker.addEventListener("change", () => {
    state[name] = picker.value;
    void refresh();
  });
}
for (const button of orientationButtons) {
  button.addEventListener("click", () => {
    state.orientation = button.value;
    void refresh();
  });
}
$("pg-guides").addEventListener("change", (event) => {
  state.guides = event.target.checked;
  void refresh();
});

// ── Editor keys ────────────────────────────────────────────────────────────

let tabLeaves = false;
editor.addEventListener("input", schedule);
editor.addEventListener("blur", () => { tabLeaves = false; });
editor.addEventListener("keydown", (event) => {
  const { selectionStart: start, selectionEnd: end, value } = editor;
  if (event.key === "Escape") {
    // Escape, then Tab, moves focus out of the editor.
    tabLeaves = true;
  } else if (event.key === "Tab" && !tabLeaves && !event.shiftKey && start === end) {
    event.preventDefault();
    editor.setRangeText("  ", start, end, "end");
    schedule();
  } else if (event.key === "Enter" && !event.isComposing && start === end) {
    event.preventDefault();
    const line = value.slice(value.lastIndexOf("\n", start - 1) + 1, start);
    const indent = line.match(/^\s*/)[0] + (/[{[]\s*$/.test(line) ? "  " : "");
    editor.setRangeText("\n" + indent, start, end, "end");
    schedule();
  }
});

// ── First load ─────────────────────────────────────────────────────────────

(async () => {
  const shared = location.hash.startsWith("#s=") ? location.hash.slice(3) : "";
  const example = new URLSearchParams(location.search).get("example");
  try {
    if (shared) return setSource(await unpack(shared), { asLoaded: false });
    if (example) return setSource(await fetchExample(example));
  } catch (error) {
    say(shared ? "That share link could not be read." : error.message);
  }
  let draft = null;
  try {
    draft = localStorage.getItem(DRAFT_KEY);
  } catch { /* No storage: start from the example. */ }
  if (draft?.trim()) return setSource(draft, { asLoaded: false });
  try {
    setSource(await fetchExample(DEFAULT_EXAMPLE));
  } catch (error) {
    say(error.message);
  }
})();
