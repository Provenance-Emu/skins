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

To undo an opt-out, a maintainer deletes its line from `blocklist.json` (one entry per line, so mind the comma on the new last line; an invalid file fails the crawl and the build instead of being read as empty). Git history isn't rewritten, so older commits still contain the removed entries.

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
  catalog.json  ← Auto-built master catalog (do not edit manually)
scripts/
  build_catalog.py       ← Builds catalog.json from skins/
  process_submission.py  ← Processes submission URLs
  crawl_sources.py       ← Crawls external repos/sites
  blocklist.py           ← Opted-out repos (blocklist.json)
  process_optout.py      ← Verifies and applies repo opt-outs
  extract_metadata.py    ← Stream-extracts info.json from skin ZIPs
  validate_skin.py       ← Validates skin JSON entries
sources.json    ← External repos/sites for weekly crawl
```

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
