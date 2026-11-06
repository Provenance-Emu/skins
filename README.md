# EmuSkins

> **Community controller skins for [Provenance](https://provenance-emu.com), [iCube](https://icube-emu.com) and [iFly](https://ifly-emu.com), and for Delta and Manic EMU**

**[🎮 Browse Skins](https://emuskins.com)** · **[➕ Submit a Skin](https://emuskins.com/submit.html)** · **[📖 Wiki](https://wiki.provenance-emu.com/info/skin-catalog-contributing)**

---

EmuSkins ([emuskins.com](https://emuskins.com)) is a community-maintained index of `.deltaskin` and `.manicskin` controller overlays. Provenance, iCube and iFly read `catalog.json` for their built-in skin browsers (in Provenance: Settings → Skins → Browse Catalog), and the files install in Delta and Manic EMU too. The site is run by the team behind Provenance, iCube and iFly.

## Submitting a Skin

### Option 1 — Web form (easiest)

Visit **[emuskins.com/submit.html](https://emuskins.com/submit.html)**, paste your skin URL, and click Submit. A bot will process it and open a PR automatically.

### Option 2 — GitHub Issue

[Open a skin submission issue](https://github.com/Provenance-Emu/skins/issues/new?template=submit-skin.yml) with your skin URL. The bot processes it within ~60 seconds.

### Option 3 — Pull Request (advanced)

1. Fork this repo
2. Generate a unique ID:
   ```bash
   printf 'manual:https://example.com/MySkin.deltaskin' | shasum -a 256 | cut -c1-16
   ```
3. Add a JSON file to `skins/{system}/your-skin-name.json`
4. Open a PR

### Option 4 — Register your repo

If you maintain a repo of skins, [register it](https://github.com/Provenance-Emu/skins/issues/new?template=register-source.yml) and our weekly crawler will auto-import new skins as you add them.

## Remove your skins

If the skins came from a GitHub repo you own, you can remove them and keep them out without waiting on a maintainer.

1. [Open the "Remove my GitHub repo" form](https://github.com/Provenance-Emu/skins/issues/new?template=remove-repo.yml) with the repo URL.
2. A bot checks that you control it. A personal repo is verified when you open the issue from the account that owns it. An org repo is verified when you are a public member of the org. Anything else (a collaborator, a renamed account) gets instructions: commit a `.emuskins-optout` file containing the issue number to the root of the repo's default branch, then comment `/verify`. Only the issue author's `/verify` counts.
3. Once verified, the bot appends the repo to `blocklist.json`, deletes its `skins/**/*.json` entries, thumbnails and `thumbnails`/`mirror` release assets, rebuilds the catalog, and closes the issue. The skins leave [emuskins.com](https://emuskins.com) and `catalog.json` when that rebuild finishes.

The "Block every repo under my account" box adds `owner/*` instead of `owner/repo`. It only works when you are the account (personal) or a public org member. A `.emuskins-optout` file proves one repo, so it never gets the account-wide block.

For skins hosted anywhere else (DeltaStyles, Google Drive, aggregator sites like `delta-skins/delta-skins.github.io` for individual artists), use the [other removal form](https://github.com/Provenance-Emu/skins/issues/new?template=remove-other.yml). A person reads it, and the bot verifies nothing.

The crawler, the submission bot and `build_catalog.py` all check `blocklist.json`, so a blocked repo isn't re-imported on the next Monday crawl, a resubmission gets "this repo has opted out of EmuSkins", and a stray skin file that slips back into `skins/` stays out of the catalog. It matches `source`, the `owner/repo` in `downloadURL` (`raw.githubusercontent.com/{o}/{r}/...`, `github.com/{o}/{r}/raw|releases/...`) and the one in `originalURL` (mirror rehosts), case-insensitively.

To undo an opt-out, a maintainer deletes its line from `blocklist.json` (one entry per line, so mind the comma on the new last line; an invalid file fails the crawl and the build instead of being read as empty). That only lifts the block. The deleted entries, thumbnails and release assets stay deleted: skins from a repo listed in `sources.json` or found by discovery come back on the next Monday crawl, and skins that came in through a submission need submitting again. Git history isn't rewritten, so older commits still contain the removed entries.

## Creator stats, badges and disputes

`docs/creators.json` (and `docs/creators/<slug>.json`) carries a `stats` and a `badges` block for every creator, computed by `scripts/compute_creator_stats.py` after each catalog build. `badges.json` names and describes every badge for both the creator side and the apps' on-device user side. Nothing is hand-edited per creator.

- Counted per creator: `releases` (a family of variants is one), `files`, `variantsCompleted`, `systems`, `dualScreen`, `firstAddedAt`, `lastAddedAt` and a coarse `reachTier`. Skins hidden for broken downloads, `sample` skins, the build's own "All variants" files and disputed skins don't count.
- `reachTier` comes from `downloadCount`, which is how often a skin's thumbnail was fetched. It is views, not installs. Counts under 50 are dropped as noise, a published count never goes down, and one that rose more than 10x since the last build is held at the old value for one build (`count-holds.json` remembers it; if the jump is still there on the next build it publishes). Run `build-catalog.yml` by hand with "accept_count_jumps" to publish a jump immediately.
- Badges are earned the first build their rule is true. `badge-dates.json` keeps that date. Unclaimed creators get `creator.first-release` and the `creator.systems.*` badges; claiming a profile unlocks the rest.
- `python3 scripts/compute_creator_stats.py --dry-run` prints the distribution over the current catalog without writing anything.

### Copied work

Report a skin with the [report form](https://github.com/Provenance-Emu/skins/issues/new?template=report-skin.yml) ("Copied from another author without credit"; link the original). A maintainer reviews it. If it holds up, they add the `disputed` label to the issue. `.github/workflows/dispute.yml` then adds the skin's id to `disputed.json` and rebuilds, and the skin stops counting toward its creator's stats and badges. It stays listed and nothing is deleted. Labelling that same issue `resolved` removes the id and the skin counts again (a `resolved` label on any other report about the skin leaves the dispute alone). `disputed.json` can also be edited by hand in a PR (`{"version": 1, "disputed": {"<skin id>": {"issue": 123, "since": "2026-11-05"}}}`).

## Supported Systems

| Code | System |
|------|--------|
| `gba` | Game Boy Advance |
| `gbc` | Game Boy Color / Game Boy |
| `nes` | Nintendo Entertainment System |
| `snes` | Super Nintendo |
| `n64` | Nintendo 64 |
| `nds` | Nintendo DS |
| `genesis` | Sega Genesis / Mega Drive |
| `unofficial` | Multi-system / other |

## Repository Structure

```
skins/
  gba/          ← One JSON file per skin
  gbc/
  nes/
  ...
docs/
  index.html    ← Browse site (GitHub Pages)
  submit.html   ← Submit form
  retroarch.html ← Skin → RetroArch overlay converter (js/skin/)
  catalog.json  ← Auto-built master catalog (do not edit manually)
scripts/
  build_catalog.py       ← Builds catalog.json from skins/
  process_submission.py  ← Processes submission URLs
  crawl_sources.py       ← Crawls external repos/sites
  blocklist.py           ← Opted-out repos (blocklist.json)
  process_optout.py      ← Verifies and applies repo opt-outs
  github_ownership.py    ← GitHub ownership checks shared by the opt-out and claim bots
  process_claim.py       ← Verifies and publishes creator profile claims
  mirror_creator_images.py ← Resizes and mirrors creator avatars/banners
  extract_metadata.py    ← Stream-extracts info.json from skin ZIPs
  validate_skin.py       ← Validates skin JSON entries
sources.json    ← External repos/sites for weekly crawl
```

## Claim your creator page

[Open the "Claim my creator profile" form](https://github.com/Provenance-Emu/skins/issues/new?template=claim-profile.yml) with your name as it appears on emuskins.com, a bio, an avatar, links and socials. A bot checks the skins are yours and publishes the profile as `creators/<name>.json`.

- Skins in a GitHub repo you own (or an org repo where you are a public member): open the issue from that account and the bot finishes on its own.
- Skins in other GitHub repos: commit a `.emuskins-creator` file containing the issue number to each repo's default branch, then comment `/verify`.
- Skins from deltastyles.com or delta-skins.github.io: a maintainer matches you to the uploader and comments `/approve`.

A bio with a link in it, or with words on the mature list, also waits for a maintainer. Your avatar and banner are copied to EmuSkins and shrunk; pages and apps never load the original. To change a profile later, open a PR that edits your `creators/<name>.json` from the account that claimed it, or file the form again with the same names. To remove it, delete the file.

## Convert a skin to a RetroArch overlay

[emuskins.com/retroarch.html](https://emuskins.com/retroarch.html) turns a `.deltaskin` or `.manicskin` into a RetroArch overlay in the browser: one folder with a `.cfg`, PNG images and a README, zipped. Nothing is uploaded. Open it with `?skin=<catalog id>` to convert a catalog skin, `?url=<download URL>` for any direct link, or drop a file on the page.

Install on RetroArch for iOS:

1. Tap the zip in **Files › Downloads** to unzip it.
2. Move the folder to **On My iPhone › RetroArch › RetroArch › overlays** (open RetroArch once first so the folder exists).
3. In RetroArch, **Settings › On-Screen Display › On-Screen Overlay › Overlay Preset** and pick the `.cfg` in that folder. Auto-Rotate Overlay switches between the landscape and portrait layouts.

The conversion logic is `docs/js/skin/retroarch-convert.js` (an ES module with no DOM code) and the button table is `docs/js/skin/retroarch-input-map.json`, which SkinKit will share for a Swift port. Buttons keep the skin's frame plus extended edges as their hitbox; d-pads become nine rects on a 3×3 grid; thumbsticks become `analog_left` / `analog_right` with the skin's stick image as a movable cap; alternate layouts become extra overlays the skin's toggle button switches to. Face buttons follow each libretro core's default RetroPad layout (Genesis A B C on Y B A, N64 Z on L2, PlayStation shapes on their usual buttons). DS touch inputs, per-game layouts, screen filters and layouts whose artwork is missing from the archive have no RetroArch equivalent and are listed on the page and in the README instead of being dropped silently; Apple TV layouts convert as artwork only. Prior art: [warmenhoven/skin2overlay](https://github.com/warmenhoven/skin2overlay); this is our own implementation. Tests: `node --test tests/js/*.test.js` (also run by `pytest` when node is installed).

## For Skin Makers — Why Host on GitHub?

- **Free, forever** — unlimited public repo storage
- **Version control** — track changes, roll back mistakes
- **Instant updates** — changes appear in the catalog within a week (or immediately with a manual PR)
- **Stable URLs** — raw GitHub URLs never break as long as your branch/path stays the same
- **No account on a third-party site** — you own your content

See the [wiki guide](https://wiki.provenance-emu.com/info/skin-catalog-contributing) for a full walkthrough.

## Attribution

Skins in this catalog are created by their respective authors. The catalog links to files hosted externally — Provenance does not claim ownership of any skin content.

Sources currently crawled:
- [delta-skins.github.io](https://delta-skins.github.io) — delta-skins community
- [Polyphian/deltaEmu](https://github.com/Polyphian/deltaEmu) — Polyphian
- [LitRitt/emuskins](https://github.com/LitRitt/emuskins) — LitRitt (GPL-3.0)

---

**Questions?** Ask on [Discord](https://discord.gg/provenance) or open an issue.
