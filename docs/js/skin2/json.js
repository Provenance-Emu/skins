/* EmuSkins — skin format 2.0, JSON values and errors (docs/js/skin2/).

   Port of SkinKit's Skin2JSON.swift and the error type of Skin2Document.swift. A skin is plain JSON; the
   preprocessor works on it before typed decoding, so tokens, part parameters and variant patches never leak
   into the typed model. */
/** Why a skin did not load: where (a JSON Pointer into skin.json) and what. */
export class Skin2Error extends Error {
    pointer;
    detail;
    constructor(pointer, message) {
        super(`${pointer === "" ? "/" : pointer}: ${message}`);
        this.name = "Skin2Error";
        this.pointer = pointer;
        this.detail = message;
    }
}
export function isObject(v) {
    return typeof v === "object" && v !== null && !Array.isArray(v);
}
/** The JSON type name used in messages: object, array, string, number, boolean, null. */
export function typeName(v) {
    if (v === null || v === undefined)
        return "null";
    if (Array.isArray(v))
        return "array";
    return typeof v === "object" ? "object" : typeof v;
}
/** JSON Pointers (RFC 6901) name places in a skin: /root/children/2/layout/size/width. */
export function pointerAppend(pointer, token) {
    return `${pointer}/${String(token).replace(/~/g, "~0").replace(/\//g, "~1")}`;
}
/** Deep copy of a JSON value (the preprocessor never mutates its input). */
export function cloneJSON(v) {
    return JSON.parse(JSON.stringify(v));
}
/** Parses skin.json text; throws a Skin2Error for invalid JSON. */
export function parseJSON(text) {
    try {
        return JSON.parse(text);
    }
    catch (e) {
        throw new Skin2Error("", `not valid JSON: ${e.message}`);
    }
}
