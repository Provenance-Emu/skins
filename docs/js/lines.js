// Skin lines: resolve a selection of options to one file.
//
// A classic script (no import/export) so browse.js, the line page and Node tests
// can all load it; everything hangs off `globalThis.emuskinsLines`. Pure: no DOM.
//
// The rules are the spec's (specs/2026-11-23-skin-lines-design.md §4) and are pinned
// by fixtures/lines/resolve-cases.json, which SkinKit's Swift resolver must pass too.
(function () {
  "use strict";

  // An option as a list: one file can serve several values on an axis.
  function values(option) {
    if (option == null) return [];
    return Array.isArray(option) ? option.slice() : [option];
  }

  function axisOrder(line, changedAxis) {
    const ids = (line.axes || []).map(a => a.id);
    if (changedAxis == null || !ids.includes(changedAxis)) return ids;
    return [changedAxis, ...ids.filter(id => id !== changedAxis)];
  }

  function has(member, axisId, valueId) {
    return valueId != null && values((member.options || {})[axisId]).includes(valueId);
  }

  function fits(member, line, selection) {
    return (line.axes || []).every(a => has(member, a.id, selection[a.id]));
  }

  function orderOf(member) {
    return member.groupOrder == null ? Infinity : member.groupOrder;
  }

  // Negative when `a` is the better pick.
  function compare(a, b, order, selection, line) {
    for (const axisId of order) {
      const d = (has(b, axisId, selection[axisId]) ? 1 : 0) - (has(a, axisId, selection[axisId]) ? 1 : 0);
      if (d) return d;
    }
    const def = line.default || {};
    const d = (fits(b, line, def) ? 1 : 0) - (fits(a, line, def) ? 1 : 0);
    if (d) return d;
    if (orderOf(a) !== orderOf(b)) return orderOf(a) - orderOf(b);
    return String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0;
  }

  // The member's value on every axis: the requested one where the member has it,
  // else the member's first.
  function selectionFor(member, wanted) {
    const out = {};
    for (const [axisId, option] of Object.entries(member.options || {})) {
      const own = values(option);
      out[axisId] = wanted && own.includes(wanted[axisId]) ? wanted[axisId] : own[0];
    }
    return out;
  }

  // The member that matches `selection` on the most axes, earlier axes outweighing
  // later ones; `changedAxis` (the one the user just touched) goes first.
  function resolve(line, members, selection, changedAxis) {
    const wanted = selection || {};
    if (!members || !members.length) return { member: null, selection: { ...wanted } };
    const order = axisOrder(line, changedAxis);
    let best = members[0];
    for (const m of members) {
      if (compare(m, best, order, wanted, line) < 0) best = m;
    }
    const ordered = {};
    const resolved = selectionFor(best, wanted);
    for (const a of line.axes || []) if (a.id in resolved) ordered[a.id] = resolved[a.id];
    return { member: best, selection: ordered };
  }

  // Whether some member has `valueId` together with what is selected on the axes before it.
  function isAvailable(line, members, selection, axisId, valueId) {
    const ids = (line.axes || []).map(a => a.id);
    const before = ids.slice(0, Math.max(0, ids.indexOf(axisId)));
    return (members || []).some(m =>
      has(m, axisId, valueId) && before.every(id => has(m, id, (selection || {})[id])));
  }

  function deviceMatches(device, traits) {
    if (!device || !traits.idiom || device.idiom !== traits.idiom) return false;
    return device.cutout == null || device.cutout === traits.cutout;
  }

  // Default, then what the device and preferences decide, then the user's stored choice.
  function initialSelection(line, members, traits, stored) {
    const t = traits || {};
    const selection = { ...(line.default || {}) };
    for (const axis of line.axes || []) {
      const vals = axis.values || [];
      let pick = null;
      if (axis.role === "device") {
        pick = vals.find(v => deviceMatches(v.device, t));
      } else if (axis.role === "hand" && t.hand) {
        pick = vals.find(v => v.hand === t.hand);
      } else if (axis.role === "mapping" && Array.isArray(t.mappings)) {
        for (const mapping of t.mappings) {
          pick = vals.find(v => v.mapping === mapping);
          if (pick) break;
        }
      }
      if (pick) selection[axis.id] = pick.id;
      const kept = stored && stored[axis.id];
      if (kept != null && vals.some(v => v.id === kept)) selection[axis.id] = kept;
    }
    return resolve(line, members, selection).selection;
  }

  function memberById(members, id) {
    return (members || []).find(m => m.id === id);
  }

  globalThis.emuskinsLines = { values, resolve, isAvailable, initialSelection, memberById, selectionFor };
})();
