/* EmuSkins — skin format 2.0, the standard parts library hook (docs/js/skin2/).

   `"use": "std.faceButton"` resolves against this table when a skin does not define the part itself. SkinKit's
   standard parts library (face button, kidney button, trigger bar, cross d-pad with lit arrows, dished stick
   with octagonal gate, pill, keypad key; `parts.std@2.0`) lands in SkinKit#123 as JSON under
   SkinKit/Sources/SkinKit2Core/Resources/parts/. This table is empty until that merges, and std.* parity is
   not covered by the fixtures here yet.

   To wire it in: fill STD_PARTS with the part definitions ({"params": {...}, "node": {...}}, keyed by the
   dotted name "std.faceButton") — vendored from the SkinKit resources the way fixtures/format2/ is — and add the
   std.* fixtures to fixtures/format2/. Nothing else changes: the preprocessor falls back to this table, and
   renderers and the validator only ever see the expanded tree. Until then a skin that uses a std.* part fails
   with "the standard parts library (std.x) is not available in this reader". */
export const STD_PARTS = {};
