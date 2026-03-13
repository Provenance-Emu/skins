# Provenance Skin Catalog

> **Community controller skins for [Provenance Emulator](https://provenance-emu.com)**

**[🎮 Browse Skins](https://provenance-emu.com/skins)** · **[➕ Submit a Skin](https://provenance-emu.com/skins/submit.html)** · **[📖 Wiki](https://wiki.provenance-emu.com/info/skin-catalog-contributing)**

---

The Provenance Skin Catalog is a community-maintained index of `.deltaskin` and `.manicskin` controller overlays compatible with Provenance. Skins appear directly in Provenance's built-in **Skin Browser** (Settings → Skins → Browse Catalog).

## Submitting a Skin

### Option 1 — Web form (easiest)

Visit **[provenance-emu.com/skins/submit.html](https://provenance-emu.com/skins/submit.html)**, paste your skin URL, and click Submit. A bot will process it and open a PR automatically.

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
