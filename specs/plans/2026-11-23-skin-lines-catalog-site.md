# Skin Lines (catalog and site) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A regular skin set such as TheMameKing's shows as one card with option pickers on emuskins.com, driven by new `lines` data in the catalog.

**Architecture:** A maintainer-written YAML rules file per line turns entry names into option values at catalog build time. `build_catalog.py` writes the result into `catalog.json` (top-level `lines`, per-entry `lineId` and `options`) and one small `docs/lines/<id>.json` per line. The site collapses a line's members into one card and resolves a selection to a file with one pure JavaScript function, pinned by fixture cases that SkinKit will reuse.

**Tech Stack:** Python 3.11+ (pytest, Pillow, PyYAML new), plain JavaScript with no build step (classic scripts, `node --test`), Playwright browser tests in `tests/browser/`.

**Spec:** `specs/2026-11-23-skin-lines-design.md` (steps 1 and 2 of its "Order of work"). SkinKit (step 3) and creator-owned `.emuskins.yml` files (step 4) are separate plans.

## Global Constraints

- `catalog.json` stays flat, one entry per file. `CATALOG_VERSION` stays 3. `groupId`, `groupOrder`, `variantLabel`, `variants`, `mergedFrom` keep their meaning.
- Resolved `lineId` and `options` are written only by the build into the catalog, never into `skins/**/*.json`.
- Nothing is guessed: an entry that matches no value on an axis, or collides with another member, stays out of the line and is listed as an ordinary family.
- A line needs at least two members with different `groupId`s; otherwise it is not emitted.
- `--check-only` fails when more than 5% of a line's candidate entries fall out.
- No existing URL changes: `docs/s/<id>.html`, `?skin=<id>`, `authors/<slug>.html`. `skin-redirects.json` is not touched.
- Generated files are never edited by hand (`docs/catalog*.json`, `docs/lines/`, `docs/l/`, `docs/authors/`, `docs/systems/`, `docs/s/`).
- New scripts under `scripts/` follow the existing pattern: importable functions plus `main()`, tests in `tests/test_<name>.py`.
- Cards never show the word "line". The badge text is exactly `{layoutCount} layouts · {n} colours` (the colours part only when the line has a `colour` axis).
- TheMameKing's entries are not on `main` (opted out by skins#92). Every test uses fixtures; no task depends on them being restored.
- Commit after each task with a conventional subject. Do not push, open PRs or post on GitHub.

## Review Focus

1. A new layout name with a token the rules don't know (his v1.9 set, or a renamed colour): the entry must stay listed as an ordinary family and the build must say so, not crash or drop it. (Task 1)
2. One token inside another ("Twin Stick" in "Twin Stick Balanced", "D-Pad" in "D-Pad Only", "4-Button" in "4-Button Classic", "iPad Tate"): the longer or earlier rule must win. (Tasks 1 and 2)
3. Link health hides some members, including the default: the line must still render, falling back to another member, and must disappear cleanly when fewer than two families remain. (Task 3)
4. A shared `?skin=<id>` link for a member of a line: it must open that exact file, not the line's default. (Tasks 5 and 6)
5. A search for an option label ("left-handed twin stick"): the line must appear once, opened on a matching member. (Task 5)

## File Structure

| File | Responsibility |
|---|---|
| `scripts/skin_lines.py` (new) | Load rules files, assign options to entries, validate, build line records |
| `lines/themameking-arcade.yml` (new) | Rules for his set |
| `tests/fixtures/lines/themameking-entries.json` (new) | His 3,300 names, labels and group ids, from git history |
| `fixtures/lines/resolve-cases.json` (new) | Resolver cases shared by JS now and SkinKit later |
| `docs/js/lines.js` (new) | Pure resolver, as a classic script on `globalThis.emuskinsLines` |
| `docs/js/line-page.js` (new) | The picker on a line page |
| `scripts/generate_line_pages.py` (new) | `docs/l/<id>.html` |
| `scripts/build_catalog.py`, `scripts/family_cards.py`, `docs/js/browse.js`, `scripts/generate_author_pages.py`, `scripts/generate_system_pages.py`, `scripts/generate_skin_pages.py`, `scripts/generate_sitemap.py`, `scripts/generate_rss.py`, `scripts/compute_creator_stats.py`, `scripts/process_optout.py`, `scripts/build_site.sh` | Modified as each task says |

---

### Task 1: Rules parser and option assignment

**Files:**
- Create: `scripts/skin_lines.py`
- Test: `tests/test_skin_lines.py`
- Modify: every workflow under `.github/workflows/` that runs `pip install` before a Python script or pytest (at least `test.yml:62` and `build-catalog.yml:81`): add `PyYAML`

**Interfaces:**
- Produces:
  - `LINES_DIR = "lines"`, `MAX_FALLOUT = 0.05`
  - `load_rules(lines_dir: str = LINES_DIR) -> tuple[list[dict], list[str]]` — one rules dict per `lines/*.yml` line, and a list of problems (bad YAML, missing keys, duplicate ids, a `default` naming an undeclared value)
  - `assign(entries: list[dict], rules: list[dict]) -> tuple[list[dict], dict]` — returns line records in the spec's §2 shape (`id`, `name`, `creator`, `systems`, `description`, `axes`, `default`, `memberCount`, `layoutCount`) and a report `{line_id: {"candidates": int, "members": int, "fallout": [{"id", "name", "reason"}]}}`. Sets `entry["lineId"]` and `entry["options"]` on members in place and removes both keys from every other entry.
  - `check(report: dict) -> list[str]` — one problem string per line whose fallout exceeds `MAX_FALLOUT`
  - `option_values(value) -> list[str]` — `"a"` → `["a"]`, `["a","b"]` → the list

Rules file shape (YAML, the spec's §3 keys): top-level `lines:` list; each line has `id`, `name`, `creator`, `description` (optional), `match: {source: str, namePrefix: str (optional)}`, `axes`, `default`. An axis has `id`, `label`, `role`, `from` (`name` or `variantLabel`) and `values`. A value rule has `tokens: [..]` or `otherwise: true`, and either `id` + `label` (plus optional `device`, `hand`, `mapping`, `swatch`) or `as: [ids]`. Every id used by `as` must be declared by another rule on the same axis. For `from: variantLabel` with no `values`, each distinct label becomes a value: `id` is the label slugified (lowercase, non-alphanumerics to `-`, trimmed), `label` the label itself, in first-seen `groupOrder` order.

- [ ] **Step 1: Write the failing tests**

Use a helper `entry(id, name, label, group, order=0, source="A/b")` returning a catalog-shaped dict, and a `RULES` dict with axes `device` (tokens `iPad` → `ipad`; `Tate` → `as: [island, notch]`; `Dynamic Island` → `island`; otherwise `notch`), `stick` (`D-Pad Only` → `dpad-only`; `D-Pad` → `dpad`; otherwise `joystick`) and `colour` (`from: variantLabel`).

```python
def test_assigns_options_from_name_and_label():
    e = [entry("1", "Pad Dynamic Island - Red", "Red", "g1"),
         entry("2", "Pad D-Pad - Red", "Red", "g2")]
    lines, report = skin_lines.assign(e, [RULES])
    assert e[0]["lineId"] == "a-pad"
    assert e[0]["options"] == {"device": "island", "stick": "joystick", "colour": "red"}
    assert e[1]["options"] == {"device": "notch", "stick": "dpad", "colour": "red"}
    assert lines[0]["memberCount"] == 2 and lines[0]["layoutCount"] == 2

def test_as_assigns_several_values():
    e = [entry("1", "Pad Tate - Red", "Red", "g1"), entry("2", "Pad iPad - Red", "Red", "g2")]
    skin_lines.assign(e, [RULES])
    assert e[0]["options"]["device"] == ["island", "notch"]

def test_earlier_rule_wins_over_contained_token():
    e = [entry("1", "Pad D-Pad Only - Red", "Red", "g1"), entry("2", "Pad iPad Tate - Red", "Red", "g2")]
    skin_lines.assign(e, [RULES])
    assert e[0]["options"]["stick"] == "dpad-only"
    assert e[1]["options"]["device"] == "ipad"

def test_tokens_match_whole_words_only():
    # "iPadish" must not match the "iPad" token
    e = [entry("1", "Pad iPadish - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2")]
    skin_lines.assign(e, [RULES])
    assert e[0]["options"]["device"] == "notch"

def test_colliding_entry_stays_out_and_is_reported():
    e = [entry("1", "Pad - Red", "Red", "g1"), entry("2", "Pad D-Pad - Red", "Red", "g2"),
         entry("3", "Pad Classic - Red", "Red", "g3")]          # same options as "1"
    lines, report = skin_lines.assign(e, [RULES])
    assert "lineId" not in e[2]
    assert report["a-pad"]["fallout"][0]["id"] == "3"
    assert "same options as" in report["a-pad"]["fallout"][0]["reason"]

def test_axis_without_otherwise_drops_unmatched_entry():
    # RULES_STRICT: the device axis has no `otherwise` rule
    e = [entry("1", "Pad Dynamic Island - Red", "Red", "g1"), entry("2", "Pad iPad - Red", "Red", "g2"),
         entry("3", "Pad Watch - Red", "Red", "g3")]
    lines, report = skin_lines.assign(e, [RULES_STRICT])
    assert "lineId" not in e[2] and report["a-pad"]["fallout"][0]["reason"] == "no value for device"

def test_line_with_one_family_is_not_emitted():
    e = [entry("1", "Pad - Red", "Red", "g1"), entry("2", "Pad - Blue", "Blue", "g1", 1)]
    lines, _ = skin_lines.assign(e, [RULES])
    assert lines == [] and "lineId" not in e[0]

def test_family_split_across_line_boundary_falls_out_whole():
    # a groupId with one member inside the line and one that collides: neither joins

def test_default_falls_back_when_default_member_is_absent():
    # RULES default names colour "blue"; only red entries exist
    lines, _ = skin_lines.assign(e, [RULES])
    assert lines[0]["default"]["colour"] == "red"

def test_stale_line_fields_are_cleared():
    e = [entry("1", "Other - Red", "Red", "g1", source="X/y")]
    e[0]["lineId"] = "old"; e[0]["options"] = {"a": "b"}
    skin_lines.assign(e, [RULES])
    assert "lineId" not in e[0] and "options" not in e[0]

def test_check_flags_fallout_over_five_percent():
    assert skin_lines.check({"a-pad": {"candidates": 100, "members": 94, "fallout": [{}] * 6}})
    assert not skin_lines.check({"a-pad": {"candidates": 100, "members": 95, "fallout": [{}] * 5}})
    assert not skin_lines.check({"a-pad": {"candidates": 0, "members": 0, "fallout": []}})   # opted-out source

def test_load_rules_reports_bad_files(tmp_path):
    # a file with invalid YAML, one missing `axes`, one whose `as` names an undeclared id:
    # each yields one problem string naming the file; none raises
```

Write the two commented tests in the same style. The line id in the catalog is `<creator>-<id>` (here creator `a`, id `pad`).

- [ ] **Step 2: Run them and see them fail**

Run: `pytest tests/test_skin_lines.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'skin_lines'`

- [ ] **Step 3: Implement `scripts/skin_lines.py`**

Decisions the tests don't fix:
- The name an axis reads is the entry's `name` with its trailing `variantLabel` and separator removed (reuse `family_cards.family_name`).
- A token matches when it appears not adjacent to a letter, digit or hyphen on either side, case-sensitively.
- Collision rule: expand each entry's options to every combination of its values; an entry whose combinations overlap an earlier member's (in `groupOrder`, then `id` order) falls out with reason `same options as <id>`. Then any `groupId` with a member that fell out falls out whole, reason `family not wholly in line`.
- `layoutCount` is the number of distinct `groupId`s among members (an ungrouped member counts as one).
- `default` in the record: the rules' `default` when a member fits it; otherwise the options of the first member by (`groupOrder`, `id`), taking the first value where an option is a list.
- Axes in the record carry only `id`, `label`, `role`, `values`; each value carries `id`, `label` and whichever of `device`, `hand`, `mapping`, `swatch` the rule gave. Values no member uses are omitted.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_skin_lines.py -v`
Expected: PASS

- [ ] **Step 5: Add PyYAML to CI and commit**

```bash
grep -ln "pip install" .github/workflows/*.yml   # add PyYAML to each line that installs Pillow or pytest
git add scripts/skin_lines.py tests/test_skin_lines.py .github/workflows
git commit -m "feat(catalog): skin line rules and option assignment"
```

---

### Task 2: Rules for TheMameKing's arcade set

**Files:**
- Create: `lines/themameking-arcade.yml`
- Create: `tests/fixtures/lines/themameking-entries.json`
- Test: `tests/test_lines_themameking.py`

**Interfaces:**
- Consumes: `skin_lines.load_rules`, `skin_lines.assign`, `skin_lines.check`
- Produces: line id `themameking-arcade`

- [ ] **Step 1: Build the fixture from history**

His entries were last in the catalog at commit `f0c272d3`. Write the fixture as a JSON array of `{id, name, variantLabel, groupId, groupOrder, source, systems, deviceSupport}` for every entry whose `source` is `TheMameKing/manic-emu-arcade-skins`:

```bash
git show f0c272d3:docs/catalog.json | python3 -c "
import json,sys
keep=('id','name','variantLabel','groupId','groupOrder','source','systems','deviceSupport')
s=[{k:e.get(k) for k in keep} for e in json.load(sys.stdin)['skins'] if e.get('source')=='TheMameKing/manic-emu-arcade-skins']
json.dump(s,open('tests/fixtures/lines/themameking-entries.json','w'),separators=(',',':'))
print(len(s))"
```

Expected: `3300`

- [ ] **Step 2: Write the failing test**

```python
def load():
    entries = json.load(open(FIXTURE))
    rules, problems = skin_lines.load_rules("lines")
    assert problems == []
    lines, report = skin_lines.assign(entries, rules)
    return entries, lines[0], report["themameking-arcade"]

def test_every_entry_joins_the_line():
    entries, line, report = load()
    assert report["candidates"] == 3300 and report["members"] == 3300 and report["fallout"] == []
    assert line["memberCount"] == 3300 and line["layoutCount"] == 150

def test_axes_and_value_counts():
    _, line, _ = load()
    assert [a["id"] for a in line["axes"]] == ["device", "game", "controls", "stick", "look", "hand", "colour"]
    sizes = {a["id"]: len(a["values"]) for a in line["axes"]}
    assert sizes == {"device": 3, "game": 2, "controls": 10, "stick": 2, "look": 4, "hand": 2, "colour": 22}

def test_default_is_six_button_dynamic_island_nightfall():
    _, line, _ = load()
    assert line["default"] == {"device": "island", "game": "horizontal", "controls": "6-button",
                               "stick": "joystick", "look": "normal", "hand": "right",
                               "colour": "nightfall-purple"}

def test_known_names():
    entries, _, _ = load()
    by_name = {e["name"]: e["options"] for e in entries}
    o = by_name["Arcade Tate Twin Stick Balanced Left-Handed - Blackout"]
    assert o == {"device": ["island", "notch"], "game": "tate", "controls": "twin-stick-balanced",
                 "stick": "joystick", "look": "normal", "hand": "left", "colour": "blackout"}
    assert by_name["Arcade 6 Pro - Sakura"]["controls"] == "6-button"
    assert by_name["Arcade iPad Tate 4-Button - Emerald"]["device"] == "ipad"
    assert by_name["Arcade 4-Button Classic D-Pad Full Screen - Whiskey"]["controls"] == "4-button"
    assert by_name["Arcade Tate D-Pad Only - Gunmetal"]["controls"] == "dpad-only"
    assert by_name["Arcade iPad 3-Button Handheld D-Pad - Rose Gold"]["look"] == "handheld"
```

- [ ] **Step 3: Run it and see it fail**

Run: `pytest tests/test_lines_themameking.py -v`
Expected: FAIL (no rules file, `lines == []`)

- [ ] **Step 4: Write `lines/themameking-arcade.yml`**

`id: arcade`, `name: Arcade Skins for Manic EMU`, `creator: themameking`, `match: {source: TheMameKing/manic-emu-arcade-skins}`. Axes in this order, value rules in this order (checked against all 3,300 names on 2026-11-23: no fallout, no collisions):

| Axis (role) | Rules, first match wins |
|---|---|
| `device` (device) | `iPad` → `ipad` "iPad" `{idiom: ipad}`; `Dynamic Island` → `island` "Dynamic Island" `{idiom: iphone, cutout: island}`; `Tate` → `as: [island, notch]`; otherwise → `notch` "Notch" `{idiom: iphone, cutout: notch}` |
| `game` (choice) | `Tate` → `tate` "Tate (vertical)"; otherwise → `horizontal` "Horizontal" |
| `controls` (choice) | `Twin Stick Balanced` → `twin-stick-balanced`; `Twin Stick` → `twin-stick`; `D-Pad Only` → `dpad-only`; `3-Button Wide Spacing` → `3-button-wide`; `6-Button` or `6 Pro` → `6-button`; `5-Button`; `4-Button`; `3-Button`; `2-Button`; `1-Button` (labels "6 buttons", "Twin stick (balanced)" and so on) |
| `stick` (choice) | `D-Pad` → `dpad` "D-pad"; otherwise → `joystick` "Joystick" |
| `look` (choice) | `Handheld` → `handheld`; `Tabletop` → `tabletop`; `Full Screen` → `full-screen`; otherwise → `normal` "Normal" |
| `hand` (hand) | `Left-Handed` → `left` `{hand: left}`; otherwise → `right` `{hand: right}` |
| `colour` (colour) | `from: variantLabel`, no `values` |

The values are listed in the file in display order, which for `controls` is 1 to 6 buttons, wide 3, twin stick, twin stick balanced, D-pad only; rule order (above) and display order differ, so give each value rule an explicit `order:` integer and have `skin_lines.assign` sort a record's values by it when present (add that to `skin_lines.py` with one test in `tests/test_skin_lines.py`: values come out in `order`, not rule order).

`default`: as asserted in the test.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_lines_themameking.py tests/test_skin_lines.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lines tests/fixtures/lines tests/test_lines_themameking.py scripts/skin_lines.py tests/test_skin_lines.py
git commit -m "feat(catalog): line rules for TheMameKing's arcade set"
```

---

### Task 3: Lines in the catalog build

**Files:**
- Modify: `scripts/build_catalog.py` (`build_catalog`, `build_browse_index`, `main`)
- Modify: `scripts/process_optout.py` (cleanup step)
- Test: `tests/test_build_catalog.py`, `tests/test_browse_index.py`, `tests/test_optout.py`

**Interfaces:**
- Consumes: `skin_lines.load_rules`, `assign`, `check`, `option_values`
- Produces:
  - `build_catalog(entries: list[dict], lines: list[dict] = ()) -> dict` — adds top-level `"lines"` (omitted when empty)
  - `build_browse_index` copies `lines` through unchanged
  - `write_line_files(catalog: dict, out_dir: str) -> list[str]` — writes `<out_dir>/lines/<id>.json` and deletes files there for lines that no longer exist
  - `--lines-dir` argument, default `skin_lines.LINES_DIR`
  - Line file shape: `{"line": <line record>, "members": [{"id", "name", "groupId", "groupOrder", "variantLabel", "options", "thumbnailURL", "screenshotURLs", "downloadURL", "fileSize", "author", "creator"}]}`, members sorted by (`groupOrder`, `id`), compact separators

- [ ] **Step 1: Write the failing tests**

```python
def test_catalog_carries_lines_and_member_options(tmp_path):
    # two families that RULES (from test_skin_lines) joins into one line
    lines, _ = skin_lines.assign(entries, [RULES])
    catalog = build_catalog.build_catalog(entries, lines)
    assert catalog["lines"][0]["id"] == "a-pad"
    assert all(s["lineId"] == "a-pad" and "options" in s for s in catalog["skins"])
    assert catalog["version"] == 3

def test_catalog_without_lines_has_no_lines_key():
    assert "lines" not in build_catalog.build_catalog([plain_entry])

def test_browse_index_keeps_lines_and_options():
    index = build_catalog.build_browse_index(catalog)
    assert index["lines"] == catalog["lines"]
    assert index["skins"][0]["lineId"] == "a-pad" and "options" in index["skins"][0]

def test_line_files_written_and_stale_ones_removed(tmp_path):
    (tmp_path / "lines").mkdir(); (tmp_path / "lines" / "gone.json").write_text("{}")
    paths = build_catalog.write_line_files(catalog, str(tmp_path))
    data = json.loads((tmp_path / "lines" / "a-pad.json").read_text())
    assert data["line"]["id"] == "a-pad" and len(data["members"]) == 2
    assert not (tmp_path / "lines" / "gone.json").exists()

def test_hidden_members_leave_the_line_before_it_is_counted():
    # main() must call skin_lines.assign AFTER split_hidden: with one of two families hidden,
    # the catalog has no lines and the visible entry has no lineId (run main() against tmp dirs,
    # as the existing main-level tests in this file do)

def test_check_only_fails_on_fallout_over_five_percent(tmp_path, capsys):
    # a rules file whose axis has no `otherwise` and entries where 1 of 10 candidates has no value:
    # main(--check-only) exits 1 and stderr names the line and the fallen-out entry
```

In `tests/test_optout.py`: after an opt-out of `A/b`, a `lines/*.yml` file whose only line has `match.source: A/b` is deleted, and one matching another source is kept.

- [ ] **Step 2: Run them and see them fail**

Run: `pytest tests/test_build_catalog.py tests/test_browse_index.py tests/test_optout.py -v`
Expected: the new tests FAIL (`build_catalog() takes 1 positional argument`, no `write_line_files`)

- [ ] **Step 3: Implement**

In `main()`: load rules next to the other validations and add its problems to `error_count`. In `--check-only`, run `assign` on a deep copy of the loaded entries and add `skin_lines.check(report)` problems. In a full build, call `assign(entries, rules)` after `split_hidden` and `merge_variants`, before `assign_creators`; print one line per line built (`Line themameking-arcade: 3300 members, 150 layouts`) and one per fallen-out entry; pass `lines` to `build_catalog`; call `write_line_files(catalog, out_dir)`. Add `- **Lines:** N` to the step summary. Rules problems in a full build are printed and the build continues without lines, the way `creator_errors` is handled.

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `pytest tests/ -q`
Expected: PASS, no regressions

- [ ] **Step 5: Commit**

```bash
git add scripts/build_catalog.py scripts/process_optout.py tests/test_build_catalog.py tests/test_browse_index.py tests/test_optout.py
git commit -m "feat(catalog): write lines, member options and per-line files"
```

---

### Task 4: The resolver and its shared cases

**Files:**
- Create: `fixtures/lines/resolve-cases.json`
- Create: `docs/js/lines.js`
- Test: `tests/js/lines/resolve.test.js`
- Modify: `tests/js/package.json` (add `"lines/*.test.js"` to the `test` script)

**Interfaces:**
- Produces, on `globalThis.emuskinsLines` (a classic script, loaded with `<script src>`; Node tests load it with `createRequire`):
  - `values(option) -> string[]`
  - `resolve(line, members, selection, changedAxis = null) -> { member, selection }` — `selection` in the result is the returned member's value on every axis (where the member has several, the requested value if it is one of them, else its first)
  - `isAvailable(line, members, selection, axisId, valueId) -> boolean`
  - `initialSelection(line, members, traits = {}, stored = null) -> selection` — `traits` is `{ idiom?: "iphone"|"ipad", cutout?: "island"|"notch"|"none", hand?: "left"|"right", mappings?: string[] }`
  - `memberById(members, id) -> member | undefined`
  - `selectionFor(member) -> selection` (first value on multi-valued axes)

Algorithm (spec §4), fixed here so two implementations agree:
- Axis order is the line's, with `changedAxis` moved to the front when given.
- A member's score is the tuple of 1/0 per axis in that order: 1 when the selected value is among the member's values. The highest tuple wins, compared left to right.
- Ties: a member that fits `line.default` on every axis first, then lowest `groupOrder` (missing last), then lowest `id`.
- `isAvailable`: some member has `valueId` on `axisId` and matches `selection` on every axis that comes before `axisId` in the line's order.
- `initialSelection`: start from `line.default`. On each `device` axis take the first value whose `device.idiom` equals `traits.idiom` and whose `device.cutout` is absent or equals `traits.cutout`; no match keeps the default. On each `hand` axis take the value whose `hand` equals `traits.hand`. On each `mapping` axis take the value for the first of `traits.mappings` the axis offers. Then apply `stored` for every axis id and value id it names that still exist. Return `resolve(line, members, that).selection`.

- [ ] **Step 1: Write the cases file**

Shape: `{ "line": {...}, "members": [...], "cases": [{ "name", "fn", "args": {...}, "expect": {...} }] }` with one toy line: axes `device` (`island`, `notch`, `ipad`, role device, with `device` objects), `game` (`horizontal`, `tate`), `hand` (`right`, `left`, role hand), `colour` (`red`, `blue`, role colour); default `island/horizontal/right/red`. Members (id: options, groupOrder):

| id | device | game | hand | colour | groupOrder |
|---|---|---|---|---|---|
| `a1` | island | horizontal | right | red | 0 |
| `a2` | island | horizontal | right | blue | 1 |
| `b1` | island | horizontal | left | red | 2 |
| `c1` | notch | horizontal | right | red | 3 |
| `d1` | [island, notch] | tate | right | red | 4 |
| `d2` | [island, notch] | tate | right | blue | 5 |
| `e1` | ipad | horizontal | right | red | 6 |
| `e2` | ipad | tate | right | blue | 7 |

Cases, each with the exact expected member id and selection:

| name | call | expect |
|---|---|---|
| exact match | resolve, default selection | `a1` |
| later axis gives way | resolve `{island, horizontal, left, blue}` | `b1`, selection colour `red` |
| changed axis is honoured | resolve `{island, tate, left, red}` with changedAxis `game` | `d1`, selection hand `right`, device `island` |
| multi-valued keeps the requested value | resolve `{notch, tate, right, blue}` | `d2`, selection device `notch` |
| after the changed axis, line order decides | resolve `{ipad, tate, right, red}` with changedAxis `colour` | `e1` (order `colour, device, game, hand`: `e1` scores 1,1,0,1 and `d1` 1,0,1,1), selection game `horizontal` |
| tie goes to default-fitting member | resolve `{}` (empty selection) | `a1` |
| tie goes to lowest groupOrder | resolve `{colour: blue}` only | `a2` |
| available | isAvailable default selection, `hand`, `left` | true |
| unavailable | isAvailable `{ipad, horizontal, …}`, `hand`, `left` | false |
| first axis always available | isAvailable any selection, `device`, `ipad` | true |
| initial, iPad | initialSelection traits `{idiom: ipad}` | device `ipad`, member `e1` |
| initial, notch iPhone | initialSelection traits `{idiom: iphone, cutout: notch}` | device `notch`, member `c1` |
| initial, left hand | initialSelection traits `{idiom: iphone, cutout: island, hand: left}` | `b1` |
| initial, unknown device keeps default | initialSelection traits `{}` | `a1` |
| initial, stored wins | initialSelection traits `{idiom: ipad}`, stored `{device: notch, colour: blue}` | device `notch`; member by the algorithm: `c1` (device outranks colour), selection colour `red` |
| stored value that no longer exists is ignored | stored `{colour: green}` | `a1` |

- [ ] **Step 2: Write the failing test**

`tests/js/lines/resolve.test.js` loads `docs/js/lines.js` with `createRequire(import.meta.url)`, reads the cases file, and runs one `test()` per case: call `emuskinsLines[fn]` with the case's args, compare `member.id` and `selection` (or the boolean) with `assert.deepStrictEqual`.

- [ ] **Step 3: Run it and see it fail**

Run: `cd tests/js && npm test`
Expected: FAIL, cannot find `docs/js/lines.js`

- [ ] **Step 4: Implement `docs/js/lines.js`**

A classic script wrapped in an IIFE that assigns `globalThis.emuskinsLines`. No DOM access, no `import`/`export`.

- [ ] **Step 5: Run the tests**

Run: `cd tests/js && npm test`
Expected: PASS, every case

- [ ] **Step 6: Commit**

```bash
git add fixtures/lines docs/js/lines.js tests/js/lines tests/js/package.json
git commit -m "feat(site): line resolver with shared cases"
```

---

### Task 5: One card per line on the browse page

**Files:**
- Modify: `docs/js/browse.js` (`clusterByGroup` and its callers, `applySearch`, `countVariantCards`, `renderGrid`, `renderStats`, `cardHTML`, `openModal`/`openLinkedSkin`)
- Modify: `docs/index.html` (load `js/lines.js` before `browse.js`; the first stat's label)
- Modify: `docs/style.css` (line badge)
- Modify: `scripts/build_site.sh` (version `js/lines.js` like `browse.js`)
- Test: `tests/browser/lines-browse.cjs` (add to `tests/browser/package.json`'s test script), fixture `tests/browser/fixtures/lines-catalog.json`

**Interfaces:**
- Consumes: `emuskinsLines.*`; catalog `lines`, entry `lineId`/`options`
- Produces: `clusterByLine(cards, lines) -> cards` in `browse.js`: runs after `clusterByGroup`; replaces every family card whose primary has a `lineId` with one card per line, placed where the line's first family stood. The line card is the family card of the line's default member's family, plus `line` (the record), `lineMembers` (all members passing the current filters) and `_lineName`.

Behaviour to build:
- **Card:** title `line.name`; thumbnail of the default member, or of the first filtered member when the default is filtered out; badge `150 layouts · 22 colours` from `line.layoutCount` and the `colour` axis; the click target is `l/<line.id>.html`, with `?skin=<id>` when the card was opened on a non-default member. No variant list, no "Download all".
- **Search:** a line matches when any member's name matches, or when every search word matches the member's name or one of its option labels (so "left-handed twin stick" works). The card then links to the first matching member.
- **Filters and sorting:** filters apply to members; the line shows when any member passes. Under "recent" a line sorts by its newest member's `addedAt`; under "popular" by the sum of member counts.
- **Counts:** `#results-count` reads `N designs · M skins` whenever a family or line is in the result. The first home-page stat becomes designs: `stat-total` shows the design count and its label reads `Designs`, with the file count as a `title` attribute (`4,698 files`). A design is a line, a family outside any line, or a single entry. `countVariantCards` counts a line as one.
- **Deep links:** `?skin=<id>` on the browse page for a line member redirects to `l/<lineId>.html?skin=<id>` (`location.replace`).

- [ ] **Step 1: Write the browser test and its fixture**

The fixture catalog has the Task 4 toy line as 8 entries (line id `a-pad`, name "Toy Pad", `layoutCount` 6), plus one ordinary two-member family and two single skins. Serve it the way `variant-gallery.cjs` serves its catalog. Assert:

```js
// 1. grid shows 4 cards: one for the line, one family, two singles
// 2. the line card's title is "Toy Pad" and its badge text is "6 layouts · 2 colours"
// 3. #results-count is "4 designs · 12 skins"; #stat-total is "4" and its label "Designs"
// 4. typing "left" in search leaves one card, whose link is l/a-pad.html?skin=b1
// 5. typing "tate blue" leaves one card linking to ?skin=d2
// 6. opening /?skin=c1 navigates to l/a-pad.html?skin=c1
// 7. with "recent" sort, the line card comes first when its member e2 has the newest addedAt
```

- [ ] **Step 2: Run it and see it fail**

Run: `npm test --prefix tests/browser`
Expected: `lines-browse.cjs` FAILS at assertion 1 (10 cards)

- [ ] **Step 3: Implement the changes in `browse.js`, `index.html`, `style.css`, `build_site.sh`**

- [ ] **Step 4: Run the browser tests**

Run: `npm test --prefix tests/browser`
Expected: PASS, including the existing `variant-gallery.cjs` and `browse-preferences.cjs`

- [ ] **Step 5: Commit**

```bash
git add docs/js/browse.js docs/index.html docs/style.css scripts/build_site.sh tests/browser
git commit -m "feat(site): show a skin line as one card on the browse page"
```

---

### Task 6: The line page

**Files:**
- Create: `scripts/generate_line_pages.py`, `docs/js/line-page.js`
- Modify: `scripts/build_site.sh` (run the generator after `generate_skin_pages.py`; version `line-page.js`), `scripts/generate_sitemap.py` (one URL per line), `docs/style.css`, `scripts/share_meta.py` only if a new page type needs registering
- Test: `tests/test_line_pages.py`, `tests/test_share_meta.py` (add the line page type), `tests/browser/line-page.cjs`

**Interfaces:**
- Consumes: `docs/catalog.json` `lines`; `docs/lines/<id>.json` (Task 3); `emuskinsLines` (Task 4); `share_meta.head_meta`
- Produces: `docs/l/<line-id>.html`; `generate_line_pages.generate_line_page(line: dict, default_member: dict, author_pages: dict) -> str`; `main()` deletes pages under `docs/l/` for lines that no longer exist

Page content, server-rendered so it works as a share target and without JS: site nav and footer (same chrome as skin pages), `<h1>` with the line name, the creator link, `150 layouts · 22 colours`, the description, the default member's thumbnail, and a download link for the default member. The page embeds no member data; `line-page.js` fetches `../lines/<id>.json`.

`line-page.js` behaviour:
- Build one control per axis that has more than one value, in axis order: buttons for up to 6 values, a `<select>` above that, swatch buttons for a `colour` axis (label as `title` and `aria-label`; a neutral chip when a value has no `swatch`).
- Initial selection: `?skin=<id>` if present (`selectionFor` that member); else `initialSelection` with traits from the browser (`idiom: ipad` when the UA or `maxTouchPoints` says iPad; `iphone` with `cutout: island` when the UA is an iPhone and `screen.height >= 852`, else `notch`; none on desktop), `hand` from `localStorage["emuskins.hand"]`, and `stored` from `localStorage["emuskins.line.<id>"]`.
- On a change: `resolve(line, members, selection, axisId)`, re-render every control from the returned selection, mark values failing `isAvailable` with `aria-disabled="true"` (still clickable; a click resolves like any change), store the selection, and `history.replaceState` to `?skin=<member id>`.
- The panel shows the resolved member's thumbnail and screenshots, its full name, file size, credit, an Install/Download button for that one file (reuse the install-link logic of the skin pages), a link "This skin's page" to `../s/<id>.html`, and "All colours for this layout" using the `data-download-all` button and `family_cards.DOWNLOAD_ALL_JS` over the members sharing its `groupId`.
- A `hand` axis change also writes `localStorage["emuskins.hand"]`.

- [ ] **Step 1: Write the failing Python tests**

```python
def test_page_has_name_badge_default_download_and_scripts():
    html = generate_line_pages.generate_line_page(LINE, DEFAULT_MEMBER, {})
    assert "<h1" in html and "Toy Pad" in html
    assert "6 layouts · 2 colours" in html
    assert DEFAULT_MEMBER["downloadURL"] in html
    assert 'src="../js/lines.js' in html and 'src="../js/line-page.js' in html
    assert 'data-line-id="a-pad"' in html

def test_main_writes_one_page_per_line_and_removes_stale(tmp_path): ...
def test_sitemap_lists_line_pages(): ...        # https://emuskins.com/l/a-pad.html appears once
```

and in `tests/test_share_meta.py`, run the existing tag checks over a generated line page (canonical `https://emuskins.com/l/a-pad.html` equals `og:url`; image is the default member's share card or thumbnail, as skin pages do).

- [ ] **Step 2: Write the failing browser test `tests/browser/line-page.cjs`** (toy line from Task 5's fixture, with `docs/lines/a-pad.json` generated from it)

```js
// 1. loads l/a-pad.html: controls for device, game, hand, colour; selected member a1
// 2. click hand "Left-handed": panel shows b1, URL ends ?skin=b1
// 3. click game "Tate": panel shows d1, hand control shows "Right-handed", "Left-handed" has aria-disabled
// 4. click colour blue: panel shows d2
// 5. load l/a-pad.html?skin=e2: device iPad, game Tate, colour blue selected; download link is e2's
// 6. reload l/a-pad.html after step 4: opens on d2 (stored selection)
// 7. "All colours for this layout" on d1 lists 2 URLs (d1, d2)
// 8. with JavaScript disabled the page still shows the name and a download link for a1
```

- [ ] **Step 3: Run both and see them fail**

Run: `pytest tests/test_line_pages.py tests/test_share_meta.py -v && npm test --prefix tests/browser`
Expected: FAIL (no module `generate_line_pages`; 404 for `l/a-pad.html`)

- [ ] **Step 4: Implement the generator, `line-page.js`, CSS, sitemap and build script changes**

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -q && npm test --prefix tests/browser`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_line_pages.py scripts/generate_sitemap.py scripts/build_site.sh docs/js/line-page.js docs/style.css tests
git commit -m "feat(site): line page with option pickers"
```

---

### Task 7: Line cards on author and system pages, and a link from skin pages

**Files:**
- Modify: `scripts/family_cards.py`, `scripts/generate_author_pages.py`, `scripts/generate_system_pages.py`, `scripts/generate_skin_pages.py`
- Test: `tests/test_family_cards.py`, `tests/test_author_pages.py`, `tests/test_skin_pages.py` (create if absent), and the system-page test file that covers `build_card`

**Interfaces:**
- Consumes: catalog `lines`, entry `lineId`
- Produces in `family_cards.py`:
  - `split_lines(clusters: list[tuple[dict, list[dict]]], lines: list[dict]) -> list[tuple]` — takes the `(primary, siblings)` tuples `cluster_groups` returns and replaces all clusters of one line with a single `("line", line, members)` item at the position of the line's first cluster; other items pass through
  - `line_badge(line: dict) -> str` — `"150 layouts · 22 colours"`, or `"150 layouts"` without a colour axis
  - `line_card_html(line: dict, members: list[dict], href_prefix: str) -> str` — the card: default member's thumbnail (first member when the default is not among `members`), `line["name"]`, the badge, a link to `{href_prefix}l/{line["id"]}.html`

- [ ] **Step 1: Write the failing tests**

```python
def test_split_lines_collapses_a_line_to_one_item():
    out = family_cards.split_lines([(a1, [a2]), (single, []), (b1, []), (c1, [])], [LINE])
    assert [o[0] if o[0] == "line" else o[0]["id"] for o in out] == ["line", "single"]
    assert len(out[0][2]) == 4

def test_line_badge():
    assert family_cards.line_badge(LINE) == "6 layouts · 2 colours"
    assert family_cards.line_badge(LINE_NO_COLOUR) == "6 layouts"

def test_line_card_links_to_line_page_and_escapes_name():
    html = family_cards.line_card_html({**LINE, "name": "A <b>"}, MEMBERS, "../")
    assert 'href="../l/a-pad.html"' in html and "A &lt;b&gt;" in html and "<b>" not in html

def test_author_page_renders_one_card_for_a_line():
    html = generate_author_pages.generate_author_page("A", "a", MEMBERS + [single], lines=[LINE])
    assert html.count('class="skin-card') == 2          # use the page's real card class
    assert "6 layouts · 2 colours" in html

def test_skin_page_links_to_its_line():
    html = generate_skin_pages.generate_skin_page(b1, {}, {}, (), line=LINE)
    assert 'href="../l/a-pad.html?skin=b1"' in html and "Part of Toy Pad" in html
```

Plus the same one-card assertion for a system page.

- [ ] **Step 2: Run them and see them fail**

Run: `pytest tests/test_family_cards.py tests/test_author_pages.py tests/test_skin_pages.py -v`
Expected: FAIL (`split_lines` missing; unexpected keyword `lines`)

- [ ] **Step 3: Implement**

`generate_author_page` and `generate_system_page` gain a `lines=()` keyword and call `split_lines` after `cluster_groups`; their `main()` passes `catalog.get("lines", [])`. The author page's "N skins" count line reads designs first when the creator has a line (`1 design · 3,300 skins`). `generate_skin_page` gains `line=None`; `main()` looks the line up by `lineId`. The system page's inline `skinsData` script (`build_skins_data_script`) gets one entry per line with `lineId` and `url` so its client-side search and modal treat a click as navigation to the line page.

- [ ] **Step 4: Run the whole Python suite**

Run: `pytest tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/family_cards.py scripts/generate_author_pages.py scripts/generate_system_pages.py scripts/generate_skin_pages.py tests
git commit -m "feat(site): line cards on author and system pages"
```

---

### Task 8: Creator stats and the feed

**Files:**
- Modify: `scripts/compute_creator_stats.py` (`compute_stats`), `scripts/generate_rss.py`
- Test: `tests/test_creator_stats.py`, `tests/test_rss.py` (create if absent)

**Interfaces:**
- Consumes: entry `lineId`; catalog `lines`
- Produces: `stats["lines"]` (int); `stats["releases"]` counts each line once; `generate_rss.feed_items(skins: list[dict], lines: list[dict], limit: int) -> list[dict]` with `{title, link, description, date, guid}`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_line_is_one_release():
    # 4 families in line "a-pad" + 1 other family + 2 ungrouped entries
    stats, facts = compute_creator_stats.compute_stats(entries)
    assert stats["releases"] == 4 and stats["lines"] == 1
    assert stats["files"] == len(entries)
    assert facts["largestFamily"] == 2                 # unchanged by lines

def test_creator_without_lines_reports_zero():
    assert compute_creator_stats.compute_stats([single])[0]["lines"] == 0

def test_feed_groups_a_lines_additions_by_day():
    # 5 members of line a-pad across 3 groupIds added 2026-11-20, 1 member (1 groupId) added
    # 2026-11-22, 1 unrelated skin added 2026-11-21
    items = generate_rss.feed_items(skins, [LINE], limit=50)
    assert [i["title"] for i in items] == [
        "1 new layout in Toy Pad", "Unrelated Skin", "3 new layouts in Toy Pad"]
    assert items[0]["link"] == "https://emuskins.com/l/a-pad.html"
    assert items[0]["guid"] == "line:a-pad:2026-11-22"
```

- [ ] **Step 2: Run them and see them fail**

Run: `pytest tests/test_creator_stats.py tests/test_rss.py -v`
Expected: FAIL (`KeyError: 'lines'`; no `feed_items`)

- [ ] **Step 3: Implement**

`compute_stats`: families whose members carry a `lineId` count once per line toward `releases`; everything else is unchanged. Check `RULES` and `badges.json` still agree (`build_catalog.py --check-only`), and that the report in `format_report` buckets `lines`. In `generate_rss.py`, move item building out of `main()` into `feed_items`; "layouts" in a title is the number of distinct `groupId`s added that day, singular for one.

- [ ] **Step 4: Run every suite**

Run: `pytest tests/ -q && (cd tests/js && npm test) && npm test --prefix tests/browser && python3 scripts/build_catalog.py --check-only`
Expected: all PASS; `--check-only` prints `All entries valid.`

- [ ] **Step 5: Update `CLAUDE.md` and commit**

Add to the skins repo's `CLAUDE.md`: `skin_lines.py` under Key Modules, `lineId`/`options`/`lines` under the schema section, `docs/lines/*.json` and `docs/l/*.html` under generated files, `docs/js/lines.js` and the shared cases file, and `PyYAML` as a dependency.

```bash
git add scripts/compute_creator_stats.py scripts/generate_rss.py tests CLAUDE.md
git commit -m "feat(site): count a skin line as one release and one feed item"
```

---

## After the last task

- With his entries opted out, a real build emits no lines: `lines/themameking-arcade.yml` matches nothing, which is not an error (zero candidates is not fallout). The feature becomes visible when the opt-out is reverted (owner decision, spec "Open decisions" 1).
- To see it locally before then, build against the pre-opt-out skins: check out `skins/` from `f0c272d3` into a scratch directory and run `python3 scripts/build_catalog.py --skins-dir <scratch>/skins --output <scratch>/docs/catalog.json`, then the page generators against that output.
