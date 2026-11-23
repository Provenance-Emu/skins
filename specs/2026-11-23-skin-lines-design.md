# Skin lines: one card for a design that comes in many configurations

Status: approved 2026-11-23 · not yet planned or built
Repos: `Provenance-Emu/skins` (catalog + emuskins.com), `Provenance-Emu/SkinKit` (the store UI in Provenance, iFly and iCube)
Prompted by: [skins#91](https://github.com/Provenance-Emu/skins/issues/91)
Builds on: SkinKit `docs/specs/2026-10-23-skin-variants-design.md` (variant families)

## Why

One creator, TheMameKing, published an arcade set that is a single design multiplied along a few axes: device, look, controls, stick type, handedness and colour. In the catalog that is 3,300 files, about 70% of every file listed. He asked to replace it with a trimmed repo because his page looked bloated. The maintainer's position is that creators should not prune their work to fit the site; the site and the store should present a large regular set well.

Variant families (`groupId`) already fold his files into 150 cards, one per layout, each with 22 colours. That is still 150 near-identical cards on one author page, a 4.6 MB HTML file, and a store where the user has to read names like "Arcade 6-Button D-Pad Dynamic Island Full Screen Left-Handed" to find the one that fits their phone and hand. A family's variants are free text, so neither the site nor the app can pick for the user.

## What exists today (researched 2026-11-23)

- **The set is exactly regular.** 3,300 entries = 150 layouts × 22 colourways. Every layout has all 22 colours. All are `mame`, `.manicskin`, about 1 MB each, mirrored to the `mirror-themameking-1..4` releases.
- **Layout names decompose into tokens.** Device: notch (named "Pro" or unnamed), "Dynamic Island", "iPad". Game: horizontal or "Tate". Look: normal, "Full Screen", and on iPad "Handheld", "Tabletop", "Full Screen". Controls: "1-Button" to "6-Button", "4-Button Classic", "3-Button Wide Spacing", "Twin Stick", "Twin Stick Balanced", "D-Pad Only". Stick: joystick (unnamed) or "D-Pad". Hand: right (unnamed) or "Left-Handed". The matrix is sparse: iPad has no left-handed layouts, Tate has only 1 to 4 buttons, and a few names are irregular ("Arcade 6 Pro").
- **Catalog schema.** Entries are flat, one per downloadable file. `groupId`, `groupOrder` and `variantLabel` make a variant family; `variants[]` lists what a single file packs; `mergedFrom` marks a catalog-built merge. Nothing describes what a variant *is*.
- **Site.** `browse.js` and `family_cards.py` collapse a `groupId` into one card with a variant gallery. Author and system pages are static HTML, one card per family. Each file has a share page at `docs/s/<id>.html`.
- **SkinKit.** `SkinFamily` and `SkinFamilyIndex` mirror the site's grouping. `SkinStoreDevice` knows iPhone and iPad only. There is no handedness setting.
- **Creator stats.** `compute_creator_stats.py` counts a family as one release, so his profile reads 150 releases.
- **Button-mapping generations.** His repo publishes each set twice: for Manic EMU 2.0.2 and newer (buttons numbered 1 2 3 over 4 5 6) and "Legacy" for 2.0.1. Only the 2.0.2 sets are in the catalog. Twin stick and most iPad sets are the same in both.
- **The set is currently opted out.** Issue 92 removed all 3,300 entries and blocklisted the repo on 2026-11-22; see "Open decisions".

## Goals

1. **One design, one card.** A set like this shows as a single card on the site's browse, system and author pages and in the app's store.
2. **Pick by options, not by reading names.** Opening the card shows one picker per axis. Combinations that don't exist can't be chosen.
3. **The app chooses what it can know.** The device option is set from the device, and handedness from a preference. The user chooses the rest.
4. **Creators add nothing to be listed well.** The catalog can describe a regular set from its names. A creator who wants control can ship a small manifest.
5. **Honest counts.** Headline numbers count designs. File counts stay visible as a second number.
6. **Nothing that works today breaks.** Every existing id, URL and catalog field keeps its meaning, and app builds already shipped keep working against the new catalog.

## Non-goals

- Changing skin files. No merging, repacking or re-theming of a creator's archives (approach C below is left for later).
- Shrinking `catalog.json`. Entries stay flat; a compact encoding for line members is a separate change if the size becomes a problem.
- Lines that span creators or systems. A line has one creator and its members share their `systems`.
- Detecting lines automatically across the whole catalog. A line exists only where a manifest or a rules file declares it.
- tvOS. The tvOS store lists no touch skins.

## Anti-goals (failure even if it works)

- A creator has to restructure or re-upload their work to be grouped.
- A file that is installable today becomes unreachable from the site or the store because it didn't fit the pattern.
- The app silently installs a different variant from the one the picker shows.
- Grouping hides attribution or per-file identity. Each member keeps its entry, credit, source and share page.
- The site and the app resolve the same selections to different files.

## Approaches considered

**A. Collections.** A `collectionId` on entries and a collection page listing the 150 family cards with filter chips. Smallest change. It fixes the author page and the counts, but the user still hunts through 150 layouts and the app cannot pick a device or hand. Not chosen.

**B. Lines with options (chosen, 2026-11-23).** A line declares named axes; each member carries its value on each axis; the site and app show one card with pickers and resolve a selection to a file. The only approach that meets goals 2 and 3. It is additive, so it can ship after the App Store submissions.

**C. Fewer files.** Extend `merge_variants.py` to fold the 22 colours into one themed file per layout. 3,300 entries become 150 and one install brings every colour, but each file is about 22 MB, Manic EMU does not read `themes`, and it does nothing for device or hand. A possible later addition on top of B, not a replacement.

## Design

### 1. Vocabulary

- **Family** (unchanged): entries sharing a `groupId`. In TheMameKing's set, one layout in 22 colours.
- **Line** (new): one design in many configurations, described by axes. In his set, all 3,300 files. A family lies wholly inside one line or outside all lines.
- **Axis**: one thing the user (or the app) chooses, with an ordered list of values.
- **Options**: a member's value on each axis. Within a line, no two members have the same options.

"Line" is the schema word. The UI never needs the noun; cards say "150 layouts · 22 colours".

### 2. Catalog schema

Entries stay flat. Two optional fields per entry and one optional top-level array are added; `version` is not bumped because old decoders ignore unknown keys (the builder confirms this against SkinKit's `SkinCatalog` decoder before shipping).

Per entry:

```json
"lineId": "themameking-arcade",
"options": { "device": "island", "game": "horizontal", "look": "normal",
             "controls": "6-button", "stick": "dpad", "hand": "left",
             "colour": "nightfall-purple" }
```

Top level:

```json
"lines": [{
  "id": "themameking-arcade",
  "name": "Arcade Skins for Manic EMU",
  "creator": "themameking",
  "systems": ["mame"],
  "description": "…",
  "axes": [
    { "id": "device", "label": "Device", "role": "device", "values": [
      { "id": "island", "label": "Dynamic Island", "device": { "idiom": "iphone", "cutout": "island" } },
      { "id": "notch",  "label": "Notch",          "device": { "idiom": "iphone", "cutout": "notch" } },
      { "id": "ipad",   "label": "iPad",           "device": { "idiom": "ipad" } } ] },
    { "id": "game",     "label": "Game",     "role": "choice", "values": [ … ] },
    { "id": "controls", "label": "Controls", "role": "choice", "values": [ … ] },
    { "id": "stick",    "label": "Stick",    "role": "choice", "values": [ … ] },
    { "id": "look",     "label": "Look",     "role": "choice", "values": [ … ] },
    { "id": "hand",     "label": "Hand",     "role": "hand",   "values": [
      { "id": "right", "label": "Right-handed", "hand": "right" },
      { "id": "left",  "label": "Left-handed",  "hand": "left" } ] },
    { "id": "colour",   "label": "Colour",   "role": "colour", "values": [
      { "id": "nightfall-purple", "label": "Nightfall Purple", "swatch": "#5b3fd1" }, … ] }
  ],
  "default": { "device": "island", "game": "horizontal", "look": "normal",
               "controls": "6-button", "stick": "joystick", "hand": "right",
               "colour": "nightfall-purple" },
  "memberCount": 3300,
  "layoutCount": 150
}]
```

Rules, enforced by `build_catalog.py --check-only`:

- `axes` order is priority order (see §4). Axis and value ids are lowercase slugs.
- **Roles.** `device` and `hand` are filled in automatically. `colour` is drawn as swatches (`swatch` optional; the builder may sample it from the thumbnail). `mapping` is the button-mapping generation (§6). `choice` is a plain user pick. A decoder treats an unknown role as `choice`.
- Every member's `options` has exactly the line's axis ids, each with a declared value.
- Options are unique within a line, and `default` names an existing member.
- All members of a `groupId` share one `lineId` (or none) and differ on at least one axis.
- A line needs at least two members with different `groupId`s; otherwise it is not emitted and its entries stay ordinary families.
- An axis with one value is kept in the data and hidden in the UI.

`groupId`, `groupOrder`, `variantLabel`, `variants` and `mergedFrom` are unchanged, so a client that does not know lines shows exactly what it shows today.

### 3. Where a line's definition comes from

Both a creator manifest and catalog-side rules, in one file format with one parser. The creator's file wins when both exist.

- **Catalog rules:** `lines/<line-id>.yml` in the skins repo, written by a maintainer. This is how TheMameKing's set is described; he changes nothing.
- **Creator manifest:** a `lines:` section in `.emuskins.yml` at the root of the creator's repo, read by the crawler and the submission bot. Optional. This is the same creator-owned file proposed on 2026-11-20 for profile settings (display name, bio, accounts, avatar; see "Related proposal"), so a creator has one file, named like the existing `.emuskins-optout` and `.emuskins-creator` markers. It is for creators who want to name the line, set the default, order the values or add swatches themselves.

Format (shown as JSON; the files are YAML with the same keys, which adds PyYAML to the build's dependencies):

```json
{
  "lines": [{
    "id": "arcade",
    "name": "Arcade Skins for Manic EMU",
    "match": { "source": "TheMameKing/manic-emu-arcade-skins" },
    "axes": [
      { "id": "device", "label": "Device", "role": "device", "from": "name", "values": [
        { "id": "ipad",   "label": "iPad",           "tokens": ["iPad"], "device": { "idiom": "ipad" } },
        { "id": "island", "label": "Dynamic Island", "tokens": ["Dynamic Island"], "device": { "idiom": "iphone", "cutout": "island" } },
        { "id": "notch",  "label": "Notch",          "otherwise": true, "device": { "idiom": "iphone", "cutout": "notch" } } ] },
      { "id": "hand", "label": "Hand", "role": "hand", "from": "name", "values": [
        { "id": "left",  "label": "Left-handed",  "tokens": ["Left-Handed"], "hand": "left" },
        { "id": "right", "label": "Right-handed", "otherwise": true, "hand": "right" } ] },
      { "id": "colour", "label": "Colour", "role": "colour", "from": "variantLabel" }
    ],
    "default": { … }
  }]
}
```

- `match` selects candidate entries by `source` (and optionally a name prefix or release tags). A creator manifest can only match its own repo; the line id is prefixed with the creator slug in the catalog.
- An axis reads either the entry's name without its `variantLabel` (`"from": "name"`) or the `variantLabel` (`"from": "variantLabel"`, where each distinct label becomes a value unless `values` lists them).
- For a name axis, values are tried in order; the first whose `tokens` appears in the name as whole words wins, and `otherwise` catches the rest. Longer tokens must be listed before shorter ones that they contain ("Twin Stick Balanced" before "Twin Stick").
- A manifest may instead list files explicitly (`"members": [{ "file": "…", "options": {…} }]`) for sets whose names carry no pattern.
- **Nothing is guessed.** An entry that matches no value on some axis, or whose options collide with another member's, stays out of the line and is listed as an ordinary family. The build prints these, and `--check-only` fails if more than 5% of a line's candidates fall out, so a rules file that has drifted from the creator's naming is noticed.
- The resolved `lineId` and `options` are written into the catalog by `build_catalog.py`, not into `skins/**/*.json`. Skin files stay as the crawler wrote them; rules can change without touching 3,300 files.
- `process_optout.py` deletes a `lines/` rules file whose source is blocked.

### 4. Resolving a selection to a file

One pure function, identical on the site and in SkinKit:

> Given a line's members and the current selection, return the member that matches the selection on the most axes, comparing axes in the line's order (a match on an earlier axis outweighs any number of matches on later ones). Ties go to the line's default member, then to the lowest `groupOrder`.

- The initial selection is the line's `default`, overridden by the automatic values (§5), then by the user's last selection for this line if one is stored.
- When the user changes one axis, that axis is moved to the front for the comparison, so the value just picked is always honoured and the other axes change only as much as they must. The picker then shows the options of the member returned, so what is shown is what installs.
- A value is drawn as unavailable when no member has it together with the values currently selected on the axes before it.
- Cases live in `fixtures/lines/resolve-cases.json` in the skins repo and are vendored into SkinKit, the same arrangement `validate-cases.json` uses for the skin stack. Both implementations must pass all of them.

### 5. What the app picks automatically

- **Device.** SkinKit gains `SkinStoreDeviceTraits { idiom, cutout }`, with `cutout` one of `island`, `notch`, `none`. A `device` axis value matches when its `idiom` equals the device's and its `cutout` is absent or equal. When several match, the first in axis order wins; when none match, the axis keeps the default and stays user-selectable. The user can always change it ("Show for another device"), because people install skins for a different device or prefer another cut.
- **Hand.** A new store setting, "Controls for: Right hand / Left hand", default right, stored by SkinKit beside its other store preferences. A `hand` axis takes it as its initial value. Changing the axis in a picker does not change the setting.
- **Mapping.** See §6.
- **On the site** the device value comes from the browser (iPad, or iPhone with the Dynamic Island guessed from screen size, else the line default), and hand from the saved browse preferences. Both stay ordinary pickers.

Everything else, including colour, is the user's choice. The last selection per line is remembered.

### 6. Button-mapping generations

A `mapping` axis has values such as `{ "id": "manic-2-0-2", "label": "Manic EMU 2.0.2+", "mapping": "manic-2.0.2" }`. A host app tells SkinKit which mapping ids it honours, in preference order, through `SkinStorePolicy`; the first that the line offers is selected and the axis is hidden in that app. On the site it is a visible picker that defaults to the first value.

This ships only as schema. Today only the 2.0.2 sets are in the catalog, so the axis would have one value. Importing the Legacy sets waits on a test of which numbering Provenance's arcade cores follow with a 6-button skin (see "Open decisions").

### 7. Site

- **Card.** Browse, system and author pages show a line as one card: the default member's thumbnail, the line name, the creator, and a badge "150 layouts · 22 colours" (`layoutCount`, and the size of the `colour` axis when there is one). Families that belong to a line are no longer listed as their own cards.
- **Line page.** `docs/l/<line-id>.html`, generated by a new `generate_line_pages.py`, with share tags from `share_meta.py`. It carries the pickers, a preview that follows the selection, the selected file's name, size and credit, an install or download button for that file, and "All colours for this layout" (the existing family download-all). The member table comes from `docs/lines/<line-id>.json`, written by the catalog build, so the page does not load the whole catalog.
- **Deep links.** `l/<line-id>.html?skin=<id>` opens with that member selected. Selections are reflected in the URL so a configuration can be shared.
- **Existing URLs.** `docs/s/<id>.html` pages stay, one per file, with their own share card, and gain a "Part of Arcade Skins for Manic EMU" link to the deep link above. `?skin=<id>` on the browse page still opens that skin. `authors/themameking.html` keeps its URL. No redirects are added or removed, so `skin-redirects.json` and the redirect check from skins#93 are unaffected.
- **Search and filters** run over members, as they do for families today, and return the line card once. Option labels are searchable ("left-handed", "twin stick"). The card opens with the first matching member selected, so a search for "left-handed twin stick" lands on that configuration. A line appears under a device or "has variants" filter when any member passes.
- **Counts.** The home page headline becomes designs, with files second ("660 designs · 4,700 files"). A design is a line, a family outside any line, or a single entry. The "Has variants" count treats a line as one.
- **Author pages** render a line card in place of its families; his page drops from 150 cards to one. `compute_creator_stats.py` counts a line as one release and adds `lines`; `files` and `variants` are unchanged, and `creator.family-builder` still reads the largest family.
- **Recently added.** A line sorts by its newest member and appears once, so an import of hundreds of files takes one place in the recent list instead of several pages. This replaces the "group bulk imports" card proposed on 2026-11-20 for the case where the import is a line; a bulk import of unrelated skins is not covered here.
- **Feed.** `generate_rss.py` emits one item per line per day of additions ("12 new layouts in Arcade Skins for Manic EMU") instead of one per file.

### 8. SkinKit store

- **Model** (SkinCatalogKit, pure, tested on the host): `SkinLine`, `SkinLineAxis`, `SkinLineIndex` (built once from the whole catalog, like `SkinFamilyIndex`) and `SkinLineResolver` (§4). `SkinCatalogEntry` decodes `lineId` and `options`.
- **Browser.** Where the store lists families it lists lines first: a line's members are removed from the family list and replaced by one line card. A host's `SkinStorePolicy` cut is applied before grouping, as for families, so iCube and iFly never see a line whose systems they don't list, and a line cut down to one family shows as that family.
- **Detail.** The line's detail screen is the picker: axes as segmented controls or menus, colour as swatches, the preview following the selection, automatic axes shown with their chosen value and a way to change it. "Install" installs the one selected file. "Install all colours" runs the existing family install-all for the selected layout. No "install everything" for a line.
- **Installed skins** are unchanged: each is one file with its `SkinFamilyMembership`, and the in-game picker keeps grouping by family. An installed member's detail links back to its line when the catalog is loaded.
- **Creator profile sheet.** `SkinCreatorIndex.families(by:in:policy:)` gains a line-aware sibling so the sheet shows a line card, and `SkinCreatorProfileSummary` reports designs alongside files.
- **Older builds** (the TestFlight builds, and 3.4.0 if it ships first) ignore the new keys and keep showing 150 family cards.

### 9. Order of work

1. **Catalog** (skins): the manifest format and parser, `lines/themameking-arcade.yml`, `build_catalog.py` emitting `lines`, `lineId`, `options` and `docs/lines/*.json`, the validation rules, and the resolver fixtures.
2. **Site** (skins): the resolver in JS, line cards, the line page, counts, author pages, stats, feed.
3. **SkinKit**: model and resolver against the vendored fixtures, device traits, the hand setting, the browser and detail UI. Then a SkinKit pin bump in Provenance, iFly and iCube.
4. **Creators**: document the `lines:` section of `.emuskins.yml` on the submit page and read it in the crawler and submission bot.

Steps 1 and 2 need no app release. Step 3 can follow the App Store submissions.

### Left to the builder

- How `cutout` is detected on device and in the browser.
- The picker's exact controls and layout on iPhone, iPad and the web.
- Where swatch colours come from when a manifest gives none.
- Whether line pages render their picker from inline data or fetch `docs/lines/<id>.json`.
- File and function names beyond those given here.

## Related proposal (Codex session, 2026-11-20)

An earlier session reviewed the same creator's page and proposed three things in conversation; none was written up or built. How they relate:

- **Group bulk imports in the recent feed** (one card per import batch, recorded by the importer, with a remembered toggle). Lines cover this for a regular set and need no batch record or toggle. A batch card for imports that are not a line stays a separate, optional follow-up.
- **Compact creator header** (about 200 px instead of 670 px, one stats line "150 layouts · 3,300 variants · MAME"). Independent of this design and compatible with it; with lines the stats line gains a designs count.
- **`.emuskins.yml`, an optional creator-owned config** with automatic defaults. Adopted here as the home of the `lines:` section instead of a second file.

Its two previews are at `~/.codex/visualizations/2026/11/11/01a1cbb0-edea-7182-b719-2e9d8cae165e/` (`compact-creator-preview.html`, `grouped-import-preview.html`).

## Open decisions

1. **Restoring the set.** Issue 92 removed all 3,300 entries, their thumbnails and the creator profile on 2026-11-22 and blocklisted the repo. The site still lists them only because the catalog build failed afterwards (skins#93). None of this design has anything to show until bot commit `f44675a9` and the `blocklist.json` line are reverted. That needs TheMameKing's agreement, since the opt-out was his request.
2. **Legacy (Manic 2.0.1) sets.** Import them as a `mapping` axis, or leave the catalog on 2.0.2 only. Depends on which numbering the three apps' arcade cores follow.
3. **v1.9 (left-handed notch)** was released after the last import and is not in the catalog. The rules file should cover it once it is crawled.
