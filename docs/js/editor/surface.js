/* EmuSkins — the editor's canvas surface (docs/js/editor/).

   Draws a set of rectangles (buttons, screens, an input frame) over a stage and
   turns pointer drags and keys into calls on the page. Each rectangle is a real,
   positioned element with data attributes (data-key="item:3"), not a shape on a
   canvas: it gets hit-testing, focus and stable test selectors for free, and the
   artwork canvas underneath stays a plain picture.

   The surface owns no skin state. The page gives it frames in mapping points and a
   view (scale); during a drag it asks the page what the frame should be (snapping,
   aspect lock) through handlers.drag(), shows that, and reports the final frame
   once through handlers.commit() on pointerup. Browser only.
*/

import { HANDLES } from "./geometry.js";

const DRAG_THRESHOLD_PX = 3;

export class Surface {
  /**
   *   stage     the element rectangles are placed in (position: relative)
   *   handlers  {
   *     select(key|null),
   *     drag({key, mode, handle, startFrame, dx, dy, shift, alt}) → { frame, guides: {x:[], y:[]} },
   *     commit({key, mode, frame}),
   *     key(event)
   *   }
   */
  constructor(stage, handlers) {
    this.stage = stage;
    this.handlers = handlers;
    this.view = { scale: 1 };
    this.disabled = false;
    this.rects = [];
    this.drag = null;

    this.layer = document.createElement("div");
    this.layer.className = "ed-layer";
    this.layer.tabIndex = 0;
    this.layer.setAttribute("role", "group");
    this.stage.appendChild(this.layer);

    this.layer.addEventListener("pointerdown", e => this.onDown(e));
    this.layer.addEventListener("pointermove", e => this.onMove(e));
    this.layer.addEventListener("pointerup", e => this.onUp(e));
    this.layer.addEventListener("pointercancel", e => this.onUp(e, true));
    this.layer.addEventListener("keydown", e => handlers.key && handlers.key(e));
  }

  focus() { this.layer.focus({ preventScroll: true }); }

  setDisabled(disabled) { this.disabled = disabled; this.layer.classList.toggle("ed-readonly", disabled); }

  /** Size the stage and place the rectangles. rects: [{ key, kind, label, frame, ext, selected, index }] */
  render(view, rects, label = "") {
    this.view = view;
    this.rects = rects;
    this.stage.style.width = `${view.pxWidth}px`;
    this.stage.style.height = `${view.pxHeight}px`;
    this.layer.setAttribute("aria-label", label);
    this.layer.textContent = "";
    for (const r of rects) this.layer.appendChild(this.buildRect(r));
    this.guideEls = [];
  }

  buildRect(r) {
    const el = document.createElement("div");
    el.className = `ed-rect ed-${r.kind}${r.selected ? " ed-selected" : ""}`;
    el.dataset.key = r.key;
    el.dataset[r.kind === "item" ? "item" : "screen"] = String(r.index);
    el.setAttribute("role", "button");
    el.setAttribute("aria-pressed", r.selected ? "true" : "false");
    el.setAttribute("aria-label", r.label);
    this.place(el, r.frame);

    if (r.ext) {
      const ext = document.createElement("div");
      ext.className = "ed-ext";
      const s = this.view.scale;
      ext.style.left = `${-(r.ext.left || 0) * s}px`;
      ext.style.top = `${-(r.ext.top || 0) * s}px`;
      ext.style.width = `${(r.frame.width + (r.ext.left || 0) + (r.ext.right || 0)) * s}px`;
      ext.style.height = `${(r.frame.height + (r.ext.top || 0) + (r.ext.bottom || 0)) * s}px`;
      el.appendChild(ext);
    }
    const label = document.createElement("span");
    label.className = "ed-label";
    label.textContent = r.label;
    el.appendChild(label);

    if (r.selected && !this.disabled) {
      for (const h of HANDLES) {
        const hd = document.createElement("div");
        hd.className = `ed-handle ed-handle-${h}`;
        hd.dataset.handle = h;
        el.appendChild(hd);
      }
    }
    return el;
  }

  place(el, f) {
    const s = this.view.scale;
    el.style.left = `${f.x * s}px`;
    el.style.top = `${f.y * s}px`;
    el.style.width = `${f.width * s}px`;
    el.style.height = `${f.height * s}px`;
  }

  rectEl(key) { return this.layer.querySelector(`[data-key="${key}"]`); }

  drawGuides(guides) {
    for (const el of this.guideEls || []) el.remove();
    this.guideEls = [];
    if (!guides) return;
    const s = this.view.scale;
    for (const x of guides.x) this.addGuide("ed-guide-x", { left: `${x * s}px`, top: "0", height: "100%" });
    for (const y of guides.y) this.addGuide("ed-guide-y", { top: `${y * s}px`, left: "0", width: "100%" });
  }

  addGuide(cls, style) {
    const g = document.createElement("div");
    g.className = `ed-guide ${cls}`;
    Object.assign(g.style, style);
    this.layer.appendChild(g);
    this.guideEls.push(g);
  }

  onDown(e) {
    if (e.button !== undefined && e.button !== 0) return;
    const rectEl = e.target.closest && e.target.closest(".ed-rect");
    if (!rectEl) { this.handlers.select(null); return; }
    const key = rectEl.dataset.key;
    const wasSelected = rectEl.classList.contains("ed-selected");
    this.handlers.select(key);
    this.focus();
    if (this.disabled) return;
    const r = this.rects.find(x => x.key === key);
    if (!r) return;
    const handle = e.target.dataset && e.target.dataset.handle;
    this.drag = {
      key, mode: handle ? "resize" : "move", handle: handle || null,
      startFrame: r.frame, startX: e.clientX, startY: e.clientY, moved: false, frame: r.frame, wasSelected, pointerId: e.pointerId,
    };
    try { this.layer.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events have no active pointer */ }
    e.preventDefault();
  }

  onMove(e) {
    const d = this.drag;
    if (!d) return;
    const px = e.clientX - d.startX, py = e.clientY - d.startY;
    if (!d.moved && Math.hypot(px, py) < DRAG_THRESHOLD_PX) return;
    d.moved = true;
    const result = this.handlers.drag({
      key: d.key, mode: d.mode, handle: d.handle, startFrame: d.startFrame,
      dx: px / this.view.scale, dy: py / this.view.scale, shift: e.shiftKey, alt: e.altKey,
    });
    if (!result) return;
    d.frame = result.frame;
    const el = this.rectEl(d.key);
    if (el) {
      this.place(el, result.frame);
      const ext = el.querySelector(".ed-ext");
      const r = this.rects.find(x => x.key === d.key);
      if (ext && r && r.ext) {
        const s = this.view.scale;
        ext.style.width = `${(result.frame.width + (r.ext.left || 0) + (r.ext.right || 0)) * s}px`;
        ext.style.height = `${(result.frame.height + (r.ext.top || 0) + (r.ext.bottom || 0)) * s}px`;
      }
    }
    this.drawGuides(result.guides);
  }

  onUp(e, cancelled = false) {
    const d = this.drag;
    if (!d) return;
    this.drag = null;
    try { this.layer.releasePointerCapture(d.pointerId); } catch (err) { /* already released */ }
    this.drawGuides(null);
    if (d.moved && !cancelled) this.handlers.commit({ key: d.key, mode: d.mode, frame: d.frame });
    else if (d.moved) this.handlers.commit({ key: d.key, mode: d.mode, frame: d.startFrame });
  }
}
