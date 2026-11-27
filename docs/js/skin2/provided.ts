/* EmuSkins — skin format 2.0, what a resolved skin provides (docs/js/skin2/).

   Port of SkinKit's Skin2Provided.swift. It says what the skin itself gives the player, so the app can hide its
   own copy (show the floating memory unit unless `pictures` has vmu.p1). It is read from the resolved tree, never
   from the document, so a declaration alone claims nothing:

   - a picture is provided when the app has picture.<source> and an accessory screen with that source is present,
     at least 48 × 32 pt, inside the canvas and more opaque than 0.05;
   - an input (semantic inputs only) is provided when a control that sends it is present with a hit frame of at
     least 44 × 44 pt inside the canvas;
   - a node in a closed shelf counts as it would with the shelf open, as long as the shelf's handle is reachable;
   - a screen or control marked "duplicate": true claims nothing. */

import { pictureCapability } from "./capabilities.js";
import type { Environment, Rect, Size } from "./geometry.js";
import { canvasRect, rect } from "./geometry.js";
import type { ResolvedNode, Resolution } from "./layout.js";
import { isAccessoryScreen, semanticInputsOf } from "./model.js";

export interface Provided {
  /** Picture sources the skin shows (vmu.p1), sorted. */
  pictures: string[];
  /** Semantic inputs the skin has a control for (arcade.coin1), sorted. */
  inputs: string[];
  /** The panels that are present, by name, and whether each is open (a fixed panel always is). */
  panels: Record<string, boolean>;
}

export const NOTHING_PROVIDED: Provided = { pictures: [], inputs: [], panels: {} };
export const MINIMUM_PICTURE: Size = { width: 48, height: 32 };
export const MINIMUM_PROVIDED_CONTROL: Size = { width: 44, height: 44 };
export const MINIMUM_OPACITY = 0.05;

const TOLERANCE = 0.0001;

function fits(frame: Rect, minimum: Size, canvas: Rect): boolean {
  const grown = rect.outset(canvas, { top: TOLERANCE, left: TOLERANCE, bottom: TOLERANCE, right: TOLERANCE });
  return frame.width >= minimum.width - TOLERANCE && frame.height >= minimum.height - TOLERANCE && rect.contains(grown, frame);
}

/** `opened` is the same layout with every reachable closed shelf (`closed`) open; only nodes of those shelves are
    read from it. */
export function computeProvided(
  resolution: Pick<Resolution, "root" | "environment" | "panels">, opened: Pick<Resolution, "root" | "environment"> | undefined, closed: Set<string>,
): Provided {
  const pictures = new Set<string>(), inputs = new Set<string>();
  const panels: Record<string, boolean> = {};
  for (const panel of resolution.panels) panels[panel.panel.name] = panel.isOpen;
  const collect = (r: ResolvedNode, above: number, env: Environment, only: Set<string> | undefined) => {
    const opacity = above * r.opacity;
    const counts = only === undefined || (r.panelName !== undefined && only.has(r.panelName));
    if (counts && !r.node.duplicate) {
      const source = r.node.source;
      if (isAccessoryScreen(r.node) && source !== undefined && env.capabilities.has(pictureCapability(source))
          && opacity > MINIMUM_OPACITY && fits(r.frame, MINIMUM_PICTURE, canvasRect(env))) pictures.add(source);
      if (r.hitFrame && fits(r.hitFrame, MINIMUM_PROVIDED_CONTROL, canvasRect(env))) for (const name of semanticInputsOf(r.node)) inputs.add(name);
    }
    for (const child of r.children) collect(child, opacity, env, only);
  };
  collect(resolution.root, 1, resolution.environment, undefined);
  if (opened) collect(opened.root, 1, opened.environment, closed);
  return { pictures: [...pictures].sort(), inputs: [...inputs].sort(), panels };
}

/** What a resolved skin provides. */
export const provided = (resolution: Resolution): Provided => resolution.provided;

/** The same report with `pictures` cut down to the sources the app has delivered a picture for. */
export function providedKeeping(p: Provided, delivered: Iterable<string>): Provided {
  const have = new Set(delivered);
  return { pictures: p.pictures.filter((s) => have.has(s)), inputs: p.inputs, panels: p.panels };
}
