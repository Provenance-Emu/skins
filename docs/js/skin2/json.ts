/* EmuSkins — skin format 2.0, JSON values and errors (docs/js/skin2/).

   Port of SkinKit's Skin2JSON.swift and the error type of Skin2Document.swift. A skin is plain JSON; the
   preprocessor works on it before typed decoding, so tokens, part parameters and variant patches never leak
   into the typed model. */

export type JSONValue = null | boolean | number | string | JSONValue[] | { [key: string]: JSONValue };
export type JSONObject = { [key: string]: JSONValue };

/** Why a skin did not load: where (a JSON Pointer into skin.json) and what. */
export class Skin2Error extends Error {
  readonly pointer: string;
  readonly detail: string;
  constructor(pointer: string, message: string) {
    super(`${pointer === "" ? "/" : pointer}: ${message}`);
    this.name = "Skin2Error";
    this.pointer = pointer;
    this.detail = message;
  }
}

export function isObject(v: JSONValue | undefined): v is JSONObject {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** The JSON type name used in messages: object, array, string, number, boolean, null. */
export function typeName(v: JSONValue | undefined): string {
  if (v === null || v === undefined) return "null";
  if (Array.isArray(v)) return "array";
  return typeof v === "object" ? "object" : typeof v;
}

/** JSON Pointers (RFC 6901) name places in a skin: /root/children/2/layout/size/width. */
export function pointerAppend(pointer: string, token: string | number): string {
  return `${pointer}/${String(token).replace(/~/g, "~0").replace(/\//g, "~1")}`;
}

/** Deep copy of a JSON value (the preprocessor never mutates its input). */
export function cloneJSON<T extends JSONValue>(v: T): T {
  return JSON.parse(JSON.stringify(v));
}

/** Parses skin.json text; throws a Skin2Error for invalid JSON. */
export function parseJSON(text: string): JSONValue {
  try {
    return JSON.parse(text) as JSONValue;
  } catch (e) {
    throw new Skin2Error("", `not valid JSON: ${(e as Error).message}`);
  }
}
