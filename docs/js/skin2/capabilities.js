/* EmuSkins — skin format 2.0, capabilities, panels and semantic inputs (docs/js/skin2/).

   Port of SkinKit's Skin2Capabilities.swift, Skin2Panel.swift (constants) and Skin2SemanticInputs.swift. A
   capability is what the app and the running game can supply right now (a memory unit's picture, a wired coin
   input); it reaches a skin through the environment and the `has` condition. The registries are closed: a skin
   cannot invent a name. */
/** The pictures an app may supply to an accessory screen, by source name. */
export const PICTURE_SOURCES = ["vmu.p1", "vmu.p2", "vmu.p3", "vmu.p4"];
/** Width / height of each picture source: an accessory screen without an `aspect` takes it. */
export const NATIVE_ASPECT = Object.fromEntries(PICTURE_SOURCES.map((s) => [s, 48 / 32]));
/** The most accessory screens a skin may have. */
export const MAX_ACCESSORY_SCREENS = 4;
/** The capability for a picture source: vmu.p1 → picture.vmu.p1. */
export const pictureCapability = (source) => `picture.${source}`;
/** The capability for a semantic input: arcade.coin1 → input.arcade.coin1. */
export const inputCapability = (name) => `input.${name}`;
/** Inputs that are not controller buttons, by dotted name. A control with one is present only while the app has
    input.<name>. Two-position switches are reserved and not built yet. */
export const SEMANTIC_INPUTS = [
    { name: "arcade.coin1", kind: "momentary", label: "Coin 1" },
    { name: "arcade.coin2", kind: "momentary", label: "Coin 2" },
    { name: "arcade.service", kind: "momentary", label: "Service" },
    { name: "arcade.test", kind: "momentary", label: "Test" },
    { name: "console.reset", kind: "momentary", label: "Reset" },
    { name: "console.select", kind: "momentary", label: "Select" },
    { name: "console.difficulty.left", kind: "twoPosition", label: "Left Difficulty" },
    { name: "console.difficulty.right", kind: "twoPosition", label: "Right Difficulty" },
    { name: "console.tvType", kind: "twoPosition", label: "TV Type" },
    { name: "vmu.a", kind: "momentary", label: "Memory Unit A" },
    { name: "vmu.b", kind: "momentary", label: "Memory Unit B" },
    { name: "vmu.mode", kind: "momentary", label: "Memory Unit Mode" },
    { name: "vmu.sleep", kind: "momentary", label: "Memory Unit Sleep" },
    { name: "vmu.up", kind: "momentary", label: "Memory Unit Up" },
    { name: "vmu.down", kind: "momentary", label: "Memory Unit Down" },
    { name: "vmu.left", kind: "momentary", label: "Memory Unit Left" },
    { name: "vmu.right", kind: "momentary", label: "Memory Unit Right" },
];
export const semanticInput = (name) => SEMANTIC_INPUTS.find((e) => e.name === name);
/** A dotted name is a semantic input; classic input names have no dot. */
export const isSemanticInput = (input) => input.includes(".");
export function isKnownCapability(capability) {
    if (capability.startsWith("picture."))
        return PICTURE_SOURCES.includes(capability.slice("picture.".length));
    if (capability.startsWith("input."))
        return semanticInput(capability.slice("input.".length)) !== undefined;
    return false;
}
// ── Panels ───────────────────────────────────────────────────────────────
export const MAX_PANELS = 6;
export const MAX_PANEL_NAME_LENGTH = 64;
/** A panel name sits inside a flag (panel.<name>.open), so it has no dots. */
export const PANEL_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_-]*$/;
export const PANEL_HANDLE_PATTERN = /^#[A-Za-z_][A-Za-z0-9_.-]*$/;
/** Flags with this prefix belong to the skin view; an app may not supply them. */
export const PANEL_FLAG_PREFIX = "panel.";
/** The app action a shelf's handle sends. The skin view takes it; it never reaches the app. */
export const TOGGLE_PANEL_INPUT = "togglePanel";
/** The flag that is on while the shelf named `name` is open. */
export const panelOpenFlag = (name) => `${PANEL_FLAG_PREFIX}${name}.open`;
