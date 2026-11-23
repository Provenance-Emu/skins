"""
Skin lines: one design that comes in many configurations (design:
specs/2026-11-23-skin-lines-design.md).

A rules file (`lines/<id>.json`, written by a maintainer) names a source repo
and a list of axes. Each axis reads an entry's name or its `variantLabel` and
gives the entry a value, or several when one file serves more than one. The
catalog build calls `assign`, which sets `lineId` and `options` on the entries
that fit and returns the line records for the catalog's top-level `lines`.

Nothing is guessed. An entry with no value on some axis, or whose options are
already taken by another member, stays out of the line and keeps showing as an
ordinary family; so does the rest of its family.
"""

import glob
import itertools
import json
import os
import re

import family_cards

LINES_DIR = "lines"

# `build_catalog.py --check-only` fails when more than this share of a line's
# candidates fall out: the rules have drifted from the creator's naming.
MAX_FALLOUT = 0.05

# A line needs members from at least this many layouts (groupIds).
MIN_LAYOUTS = 2

AXIS_SOURCES = ("name", "variantLabel")
VALUE_METADATA = ("device", "hand", "mapping", "swatch")


def option_values(value) -> list[str]:
    """An option as a list: one file can serve several values on an axis."""
    return list(value) if isinstance(value, (list, tuple)) else [value]


def catalog_id(rule: dict) -> str:
    return f"{rule['creator']}-{rule['id']}"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------------------
# Rules files
# ---------------------------------------------------------------------------

def _rule_problems(rule) -> list[str]:
    if not isinstance(rule, dict):
        return ["a line must be an object"]
    problems = []
    for key in ("id", "name", "creator"):
        if not isinstance(rule.get(key), str) or not rule.get(key):
            problems.append(f"missing `{key}`")
    match = rule.get("match")
    if not isinstance(match, dict) or not isinstance(match.get("source"), str) or not match.get("source"):
        problems.append("missing `match.source`")
    axes = rule.get("axes")
    if not isinstance(axes, list) or not axes:
        problems.append("missing `axes`")
        return problems
    default = rule.get("default")
    if not isinstance(default, dict):
        problems.append("missing `default`")
        default = {}
    seen_axes = set()
    for axis in axes:
        if not isinstance(axis, dict) or not axis.get("id") or not axis.get("label"):
            problems.append("an axis needs `id` and `label`")
            continue
        aid = axis["id"]
        if aid in seen_axes:
            problems.append(f"axis `{aid}` is declared twice")
        seen_axes.add(aid)
        if axis.get("from") not in AXIS_SOURCES:
            problems.append(f"axis `{aid}`: `from` must be one of {', '.join(AXIS_SOURCES)}")
        values = axis.get("values")
        if values is None and axis.get("from") == "variantLabel":
            if aid not in default:
                problems.append(f"`default` has no value for `{aid}`")
            continue
        if not isinstance(values, list) or not values:
            problems.append(f"axis `{aid}`: missing `values`")
            continue
        declared = {v.get("id") for v in values if isinstance(v, dict) and v.get("id")}
        for value in values:
            if not isinstance(value, dict):
                problems.append(f"axis `{aid}`: a value must be an object")
                continue
            if not value.get("otherwise") and not value.get("tokens") and axis.get("from") == "name":
                problems.append(f"axis `{aid}`: a value needs `tokens` or `otherwise`")
            if "as" in value:
                unknown = [i for i in option_values(value["as"]) if i not in declared]
                if unknown:
                    problems.append(f"axis `{aid}`: `as` names undeclared value(s) {', '.join(unknown)}")
            elif not value.get("id") or not value.get("label"):
                problems.append(f"axis `{aid}`: a value needs `id` and `label`, or `as`")
        if aid not in default:
            problems.append(f"`default` has no value for `{aid}`")
        elif default[aid] not in declared:
            problems.append(f"`default.{aid}` is `{default[aid]}`, which the axis does not declare")
    return problems


def load_rules(lines_dir: str = LINES_DIR) -> tuple[list[dict], list[str]]:
    """Every valid line in `lines_dir/*.json`, and what is wrong with the rest."""
    rules, problems, seen = [], [], {}
    for path in sorted(glob.glob(os.path.join(lines_dir, "*.json"))):
        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            problems.append(f"{path}: {e}")
            continue
        lines = doc.get("lines") if isinstance(doc, dict) else None
        if not isinstance(lines, list) or not lines:
            problems.append(f"{path}: expected an object with a `lines` list")
            continue
        for rule in lines:
            found = _rule_problems(rule)
            if found:
                problems.extend(f"{path}: {p}" for p in found)
                continue
            cid = catalog_id(rule)
            if cid in seen:
                problems.append(f"{path}: line `{cid}` is already defined in {seen[cid]}")
                continue
            seen[cid] = path
            rules.append(dict(rule, _path=path))
    return rules, problems


def rules_for_source(lines_dir: str, source: str) -> list[str]:
    """Paths of rules files whose every line matches `source` (owner/repo, any case)."""
    out = []
    for path in sorted(glob.glob(os.path.join(lines_dir, "*.json"))):
        try:
            with open(path) as f:
                lines = json.load(f).get("lines") or []
        except (OSError, ValueError, AttributeError):
            continue
        sources = [str(((line or {}).get("match") or {}).get("source", "")).lower() for line in lines]
        if sources and all(s == source.lower() for s in sources):
            out.append(path)
    return out


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------

def _has_token(name: str, token: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])", name) is not None


def _order_key(entry: dict):
    order = entry.get("groupOrder")
    return (order is None, order if order is not None else 0, str(entry.get("id") or ""))


def _layout_key(entry: dict) -> str:
    return entry.get("groupId") or f"entry:{entry.get('id')}"


def _name_value(axis: dict, base_name: str):
    for value in axis["values"]:
        if value.get("otherwise") or any(_has_token(base_name, t) for t in value.get("tokens") or []):
            return list(value["as"]) if "as" in value else value["id"]
    return None


def _label_value(axis: dict, label: str):
    if not label:
        return None
    values = axis.get("values")
    if values is None:
        return slugify(label) or None
    wanted = label.strip().lower()
    for value in values:
        tokens = [t.lower() for t in value.get("tokens") or []]
        if value.get("otherwise") or wanted in tokens or wanted == str(value.get("label", "")).lower():
            return list(value["as"]) if "as" in value else value["id"]
    return None


def _options_for(rule: dict, entry: dict):
    """(`options`, None) or (None, reason)."""
    base_name = family_cards.family_name(entry) if entry.get("variantLabel") else (entry.get("name") or "")
    options = {}
    for axis in rule["axes"]:
        if axis["from"] == "name":
            value = _name_value(axis, base_name)
        else:
            value = _label_value(axis, entry.get("variantLabel") or "")
        if value is None:
            return None, f"no value for {axis['id']}"
        options[axis["id"]] = value
    return options, None


def _combinations(rule: dict, options: dict):
    return itertools.product(*[option_values(options[a["id"]]) for a in rule["axes"]])


def _fits(options: dict, selection: dict) -> bool:
    return all(selection.get(axis) in option_values(value) for axis, value in options.items())


def _axis_record(axis: dict, members: list[dict], options: dict) -> dict:
    used = []
    for m in members:
        for v in option_values(options[m["id"]][axis["id"]]):
            if v not in used:
                used.append(v)
    declared = {v["id"]: v for v in axis.get("values") or [] if v.get("id")}
    if declared:
        ids = [i for i in declared if i in used]
        if any("order" in declared[i] for i in ids):
            ids.sort(key=lambda i: declared[i].get("order", 0))
    else:
        ids = used
    labels = {}
    if not declared:
        for m in members:
            labels.setdefault(options[m["id"]][axis["id"]], m.get("variantLabel"))
    values = []
    for i in ids:
        rule_value = declared.get(i, {})
        value = {"id": i, "label": rule_value.get("label") or labels.get(i) or i}
        value.update({k: rule_value[k] for k in VALUE_METADATA if k in rule_value})
        values.append(value)
    return {"id": axis["id"], "label": axis["label"], "role": axis.get("role") or "choice", "values": values}


def _assign_line(rule: dict, entries: list[dict]) -> tuple["dict | None", dict]:
    source = rule["match"]["source"].lower()
    prefix = rule["match"].get("namePrefix") or ""
    candidates = sorted(
        (e for e in entries
         if str(e.get("source") or "").lower() == source and (e.get("name") or "").startswith(prefix)),
        key=_order_key)
    fallout, options, taken = [], {}, {}

    def drop(entry, reason):
        fallout.append({"id": entry.get("id"), "name": entry.get("name"), "reason": reason})

    for e in candidates:
        opts, reason = _options_for(rule, e)
        if opts is None:
            drop(e, reason)
            continue
        combos = list(_combinations(rule, opts))
        clash = next((taken[c] for c in combos if c in taken), None)
        if clash is not None:
            drop(e, f"same options as {clash}")
            continue
        for c in combos:
            taken[c] = e.get("id")
        options[e["id"]] = opts

    broken = {_layout_key(e) for e in candidates if e.get("id") not in options and e.get("groupId")}
    members = []
    for e in candidates:
        if e.get("id") not in options:
            continue
        if _layout_key(e) in broken:
            del options[e["id"]]
            drop(e, "family not wholly in line")
            continue
        members.append(e)

    report = {"candidates": len(candidates), "members": len(members), "fallout": fallout}
    layouts = {_layout_key(e) for e in members}
    if len(layouts) < MIN_LAYOUTS:
        report["members"] = 0
        return None, report

    line_id = catalog_id(rule)
    for e in members:
        e["lineId"] = line_id
        e["options"] = options[e["id"]]

    default = dict(rule["default"])
    if not any(_fits(options[e["id"]], default) for e in members):
        default = {axis: option_values(value)[0] for axis, value in options[members[0]["id"]].items()}

    record = {
        "id": line_id,
        "name": rule["name"],
        "creator": rule["creator"],
        "systems": sorted({s for e in members for s in e.get("systems") or []}),
    }
    if rule.get("description"):
        record["description"] = rule["description"]
    record.update({
        "axes": [_axis_record(axis, members, options) for axis in rule["axes"]],
        "default": default,
        "memberCount": len(members),
        "layoutCount": len(layouts),
    })
    return record, report


def assign(entries: list[dict], rules: list[dict]) -> tuple[list[dict], dict]:
    """Set `lineId`/`options` on the entries each rule takes (and clear them
    everywhere else). Returns the line records and a per-line report."""
    for e in entries:
        e.pop("lineId", None)
        e.pop("options", None)
    lines, report = [], {}
    for rule in rules:
        free = [e for e in entries if "lineId" not in e]
        record, line_report = _assign_line(rule, free)
        report[catalog_id(rule)] = line_report
        if record:
            lines.append(record)
    return lines, report


def check(report: dict) -> list[str]:
    """One problem per line that lost more than MAX_FALLOUT of its candidates."""
    problems = []
    for line_id, r in sorted(report.items()):
        candidates, fallout = r.get("candidates") or 0, r.get("fallout") or []
        if candidates and len(fallout) / candidates > MAX_FALLOUT:
            sample = "; ".join(f"{f.get('name')} ({f.get('reason')})" for f in fallout[:5])
            problems.append(
                f"line {line_id}: {len(fallout)} of {candidates} entries do not fit its rules "
                f"(over {MAX_FALLOUT:.0%}): {sample}")
    return problems
