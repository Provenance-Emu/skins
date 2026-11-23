/* EmuSkins — live examples in the format 2.0 documentation. Each <figure data-skin-example="examples/x.json">
   gets a preview drawn by the site renderer, orientation buttons, a theme picker when the source has themes, and
   its source. Add data-layout="split" to show the source beside the preview. Figures load as they scroll into
   view. */
import { loadDocument } from "../js/skin2/index.js";
import { formatJSON, highlightJSON, makeSwitches, renderPreview, SAMPLE_CAPTION } from "./preview.js";

let queue = Promise.resolve();
/** One render at a time, so a page of examples doesn't freeze while it draws. */
const enqueue = (work) => (queue = queue.then(work, work));

function element(tag, properties = {}, ...children) {
  const node = Object.assign(document.createElement(tag), properties);
  node.append(...children);
  return node;
}

function segmented(label, values, onChange) {
  const group = element("div", { className: "seg" });
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", label);
  const buttons = values.map((value) => {
    const button = element("button", { type: "button", textContent: value[0].toUpperCase() + value.slice(1) });
    button.addEventListener("click", () => {
      select(value);
      onChange(value);
    });
    return button;
  });
  const select = (value) => buttons.forEach((button, index) => button.setAttribute("aria-pressed", String(values[index] === value)));
  group.append(...buttons);
  return { group, select };
}

function setUp(figure) {
  const split = figure.dataset.layout === "split";
  const state = { orientation: figure.dataset.orientation || "portrait", theme: undefined };
  const status = element("p", { className: "example-status", textContent: "Loading preview…" });
  status.setAttribute("role", "status");
  const device = element("div", { className: "device" });
  const sample = element("p", { className: "example-sample", textContent: SAMPLE_CAPTION, hidden: true });
  const stage = element("div", { className: "example-stage" }, device, sample, status);
  const switches = makeSwitches(() => void show());
  const code = element("code");
  const source = element("pre", { className: "example-source", tabIndex: 0 }, code);
  source.setAttribute("aria-label", "Skin source");
  const body = element("div", { className: "example-body" }, stage, source);
  const tools = element("div", { className: "example-tools" });
  const caption = figure.querySelector("figcaption") ?? element("figcaption");
  const bar = element("div", { className: "example-bar" }, caption, tools);
  figure.classList.add("example", split ? "is-split" : "is-card");
  figure.prepend(bar, switches.element, body);

  let text;
  const canvases = new Map();
  let ticket = 0;

  async function show() {
    // A copy: the render may wait in the queue while the visitor picks something else, and it must draw what
    // `key` names.
    const options = { ...state, capabilities: new Set(switches.state.capabilities), flags: new Set(switches.state.flags) };
    const key = `${options.orientation}|${options.theme ?? ""}|${[...options.capabilities].sort()}|${[...options.flags].sort()}`;
    const current = ++ticket;
    try {
      if (!canvases.has(key)) {
        device.classList.add("is-busy");
        canvases.set(key, await enqueue(() => renderPreview(text, options)));
      }
      if (current !== ticket) return;
      const result = canvases.get(key);
      const { canvas, trait } = result;
      device.dataset.orientation = trait.orientation;
      device.replaceChildren(canvas);
      sample.hidden = !result.sample;
      switches.show(result);
      status.textContent = "";
    } catch (error) {
      canvases.delete(key);
      if (current === ticket) status.textContent = error.message || "Could not draw this example.";
    } finally {
      if (current === ticket) device.classList.remove("is-busy");
    }
  }

  async function load() {
    try {
      const response = await fetch(figure.dataset.skinExample);
      if (!response.ok) throw new Error("Could not load the example.");
      text = await response.text();
      const json = JSON.parse(text);
      code.innerHTML = highlightJSON(formatJSON(json));
      switches.adopt(loadDocument(text));

      const orientation = segmented("Preview orientation", ["portrait", "landscape"], (value) => {
        state.orientation = value;
        void show();
      });
      orientation.select(state.orientation);
      tools.append(orientation.group);

      const themes = Object.keys(json.themes ?? {});
      if (themes.length) {
        const picker = element("select");
        picker.setAttribute("aria-label", "Theme");
        picker.append(element("option", { value: "", textContent: "Default theme" }),
          ...themes.map((name) => element("option", { value: name, textContent: name })));
        picker.addEventListener("change", () => {
          state.theme = picker.value || undefined;
          void show();
        });
        tools.append(picker);
      }

      if (!split) {
        const toggle = element("button", { type: "button", className: "example-toggle", textContent: "Source" });
        toggle.setAttribute("aria-expanded", "false");
        source.hidden = true;
        toggle.addEventListener("click", () => {
          source.hidden = !source.hidden;
          stage.hidden = !source.hidden;
          toggle.setAttribute("aria-expanded", String(!source.hidden));
          toggle.textContent = source.hidden ? "Source" : "Preview";
        });
        tools.append(toggle);
      }
      await show();
    } catch (error) {
      status.textContent = error.message || "Could not load the example.";
    }
  }

  return load;
}

const pending = new WeakMap();
const observer = "IntersectionObserver" in globalThis
  ? new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      void pending.get(entry.target)?.();
    }
  }, { rootMargin: "300px" })
  : undefined;

for (const figure of document.querySelectorAll("figure[data-skin-example]")) {
  const load = setUp(figure);
  if (observer) {
    pending.set(figure, load);
    observer.observe(figure);
  } else {
    void load();
  }
}
