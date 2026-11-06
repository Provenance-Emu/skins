# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Part of `personal-os`

This repo is a satellite of [`personal-os`](file:///Users/jmattiello/Workspace/personal-os) at `~/Workspace/personal-os`. A fresh agent session here should read `personal-os/AGENTS.md` first for shared conventions:

- **`VOICE.md`** — voice rules for any public-facing prose (skin descriptions, README copy).
- **`decisions/`** — cross-repo MADR-numbered ADRs.
- **`journal/`** — daily orchestration log; touch entries when shipping work in this repo.
- **`INBOX.md`** — things-to-act-on across all projects.
- **`wiki/projects-index.md`** — registry of every active repo and how it relates to this one.

Don't edit `personal-os/raw/` from a satellite — that's the central drop-zone, one-way.

## Project Overview

Community-maintained catalog of `.deltaskin` and `.manicskin` controller overlay skins for the Provenance Emulator. Skins are indexed as JSON metadata files under `skins/` and compiled into a master `catalog.json` that powers an in-app Skin Browser and a GitHub Pages static site.

## Key Commands

```bash
# Validate catalog integrity (no writes)
python3 scripts/build_catalog.py --check-only

# Build catalog.json from skins/**/*.json
python3 scripts/build_catalog.py

# Validate a single skin JSON file
python3 scripts/validate_skin.py skins/gba/example.json
python3 scripts/validate_skin.py --check-url skins/gba/example.json  # also verifies download URL

# Validate creator profile files (schema; CI adds the PR-author check)
python3 scripts/validate_creator.py creators/<slug>.json

# Run full test suite
pytest tests/ -v

# Run a single test file
pytest tests/test_skin_schema.py -v

# Generate static pages (system + author pages, RSS, sitemap)
python3 scripts/generate_system_pages.py
python3 scripts/generate_author_pages.py
python3 scripts/generate_rss.py
python3 scripts/generate_sitemap.py
python3 scripts/generate_share_cards.py   # 1200x630 share cards → docs/cards/
python3 scripts/generate_skin_pages.py     # per-skin share pages → docs/s/

# Crawl external sources for new skins (dry run)
python3 scripts/crawl_sources.py --dry-run

# Generate thumbnails
python3 scripts/generate_thumbnails.py

# Check every download the way the app installs it (updates link-health.json)
python3 scripts/link_health.py

# Extract skins from zip packs (dry run; --upload publishes to the `mirror` release)
python3 scripts/repack_skins.py --from-health

# Merge variant families into one "All variants" file (dry run; --upload publishes)
python3 scripts/merge_variants.py
```

**Python 3.11+** required. Key dependencies: Pillow (image processing), pytest (testing).

## Architecture

### Data Flow

1. **Skin JSON files** (`skins/{system}/{slug}.json`) — one file per skin, organized by system code
2. **`build_catalog.py`** — aggregates all skin JSON into `docs/catalog.json` (and root `catalog.json`)
3. **Static site generators** — produce system/author HTML pages, RSS feed, sitemap from catalog
4. **GitHub Pages** — serves `docs/` directory as the browsable website

### Critical Rule: Never Edit Generated Files Manually

- `catalog.json` (root and docs/) — built by `build_catalog.py`
- `docs/systems/*.html` — built by `generate_system_pages.py`
- `docs/authors/*.html` — built by `generate_author_pages.py`: one page per creator slug with a listed skin (claimed or not), plus a redirect stub for each alias slug; claimed profiles render from `creators/<slug>.json` (`creator_pages.py`, `creator_profile_html.py`)
- `docs/cards/authors/*.jpg` — built by `generate_share_cards.py` (claimed creators and creators with 3+ skins)
- `added-dates.json` — cache of each skin file's first-commit date (`addedAt`), written by `build_catalog.py` from full git history (`scripts/added_dates.py`)
- `docs/creators.json`, `docs/creators/*.json` — built by `build_catalog.py` from the hand-edited `creators/<slug>.json`
- `docs/s/*.html` — built by `generate_skin_pages.py` (one per skin, so shared links preview that skin)
- `docs/cards/**/*.jpg` — built by `generate_share_cards.py`
- `docs/feed.xml`, `docs/sitemap.xml` — built by respective generators
- `thumbnails/*.png` — built by `generate_thumbnails.py`
- `link-health.json` — written by `link_health.py` and `repack_skins.py`

### Case-sensitive paths

`skins/{system}/` directories must match the system code's case exactly. Two paths that differ only by case (`virtualBoy/` vs `virtualboy/`) collide on macOS and Windows checkouts, so `build_catalog.py --check-only` rejects them.

### Skin JSON Schema

Required fields: `id`, `name`, `systems`, `downloadURL`, `source`

- **`id`**: 16-char lowercase hex, generated deterministically from `source + downloadURL` via `skin_schema.py:generate_id()`
- **`systems`**: array of system short codes (e.g., `["gba"]`). Valid codes defined in `SYSTEM_MAP` in `skin_schema.py`
- **`downloadURL`**: must end in `.deltaskin` or `.manicskin`
- Skins with unknown/multi-system mappings go under `skins/unofficial/`
- **`groupId` / `groupOrder` / `variantLabel`** (optional): entries sharing a `groupId` are variants of one release. `variantLabel` is the variant's own name inside its group ("Doom"), and it requires `groupId`. The crawler, `repack_skins.py`, `migrate_deltastyles.py` and `backfill_group_ids.py` set it; `scripts/backfill_variant_labels.py` fills the rest using the website's rule (text after " — " / " - ", else the name minus the group's base name, else unset)
- **`mergedFrom` / `mergedHash`** (optional, together): an "All variants" entry `merge_variants.py` built from its family's other members (`groupOrder` 0, `variantLabel` "All variants"). `mergedFrom` lists the member ids, base first; they must exist and share the entry's `groupId`. `mergedHash` is what the job compares to skip unchanged families. Never edit these entries by hand

### Key Modules (`scripts/`)

- **`skin_schema.py`** — shared schema, `SYSTEM_MAP` (150+ system name variants → short codes), ID generation, validation logic. This is the single source of truth for valid systems and field validation.
- **`build_catalog.py`** — catalog builder with GitHub Releases download count fetching
- **`extract_metadata.py`** — extracts `info.json` from skin ZIP archives via HTTP range requests (≤4 requests, falls back to full download)
- **`process_submission.py`** — handles 4 submission types: direct skin URL, GitHub repo URL, GitHub release URL, JSON metadata URL
- **`crawl_sources.py`** — weekly crawler consuming `sources.json` to discover new skins from external repos and sites. Dedupes against `skins/**/*.json` (including `originalURL`), not just the catalog, because the catalog leaves out hidden skins
- **`link_health.py`** — checks each download the way Provenance installs it: 2xx status, a ZIP, `info.json` at the archive root, and artwork for its layouts. Artwork names resolve the way the app's `Archive.entry(matchingAssetNamed:)` does: exact path, then case-insensitive file name anywhere, then the same stem as `.pdf`/`.png`/`.svg`. Failing entries go in `link-health.json`. `build_catalog.py` hides an entry after 2 consecutive runs with a deterministic failure (404/410, not a zip, no root `info.json`, no artwork in any layout), and only while its `downloadURL` matches the URL that was checked. Network errors and 5xx never hide. Skins missing artwork for only some layouts stay listed and are recorded under `partialArtwork`. A run where more than 10% of skins newly fail writes nothing (circuit breaker)
- **`polite_http.py`** — the HTTP layer for deltastyles.com (SkinKit#16): at most 2 requests at once spaced 1s apart, one download per URL per run into a cache dir keyed by URL hash (`SKIN_CACHE_DIR`), `If-None-Match`/`If-Modified-Since` from the validators saved with each cached file, a User-Agent with the repo URL, and on 403/429 a back-off then `HostBlocked` for the rest of the run (never retries around a block). `link_health.py`, `crawl_sources.py`, `generate_thumbnails.py`, `extract_metadata.py` and `repack_skins.py` all go through it for polite hosts; link-health exports the archives of skins missing a thumbnail as the `skin-cache` artifact for `generate-thumbnails.yml`
- **`blocklist.py`** / **`process_optout.py`** — repo opt-out (SkinKit#34). `blocklist.json` (array, one entry per line) lists opted-out `owner/repo` or `owner/*`; `is_blocked(entry)` matches `source`, `downloadURL` and `originalURL`, and is enforced in `process_submission.py`, `crawl_sources.py` and `build_catalog.split_hidden`. `process_optout.py` verifies ownership (account match, org public member, or `.emuskins-optout` + `/verify`) and runs the cleanup; it takes `--dry-run`. Issue values reach it through `env:` only
- **`repack_skins.py`** — for zips holding one or more skins (or a skin one folder down), extracts each skin, checks it, uploads it to the `mirror` GitHub Release, and rewrites the entry. One skin keeps the entry's `id`; a pack becomes one entry per skin sharing a `groupId`. Rewritten entries record the source archive in `originalURL`
- **`merge_variants.py`** — for families (`groupId`) whose members link-health checked `ok`, classifies the original members (themes: only the background art differs; alt: exactly two that differ in layout; else split), builds one archive whose `representations` is the base's untouched plus `themes` or `altRepresentations` with renamed artwork, uploads it to `mirror`, and writes one extra entry with `mergedFrom`/`mergedHash`. Unchanged hashes are skipped; a family that turns split or drops below two visible members loses its merged entry. `link-health.yml` runs it as a report, publishing only when started with `merge` on. Rules and fixtures: `fixtures/merge/` (`scripts/generate_merge_fixtures.py`); design: SkinKit `docs/specs/2026-11-03-skin-editing-tools-design.md` §3

### CI/CD Workflows (`.github/workflows/`)

- **build-catalog.yml** — rebuilds catalog + static pages on push to main
- **process-submission.yml** — processes skin submissions from GitHub Issues
- **crawl-sources.yml** — weekly Monday 3am UTC crawl of external sources
- **optout.yml** — runs `process_optout.py` for `repo-optout` issues and `/verify` comments
- **test.yml** — pytest on Python 3.11 & 3.12 when `scripts/` or `tests/` change
- **validate-pr.yml** — validates changed skin JSON files in PRs
- **generate-thumbnails.yml** — generates thumbnails, uploads to GitHub Releases (`thumbnails` tag)
- **link-health.yml** — weekly Tuesday 4am UTC: runs `link_health.py`, repacks zip packs to the `mirror` release, commits `link-health.json`, then dispatches the catalog and thumbnail builds

### Thumbnail System

Thumbnails are stored in GitHub Releases (tag: `thumbnails`) and referenced by `thumbnailURL` in skin JSON. The workflow uses smart rebasing to avoid merge conflicts on concurrent updates.

## Adding a New Skin

1. Create a JSON file at `skins/{system}/{slug}.json` with required fields
2. Generate the `id` using `skin_schema.generate_id(source, downloadURL)`
3. Run `python3 scripts/validate_skin.py skins/{system}/{slug}.json` to validate
4. The catalog and static pages are regenerated automatically on merge

### Share tags

Every page's title, description, canonical, Open Graph and Twitter tags come from `scripts/share_meta.py` (`head_meta()`); `docs/index.html` and `docs/submit.html` carry the same block by hand. `tests/test_share_meta.py` checks every page type: required tags, canonical == `og:url`, `twitter:image` == `og:image`, and the image's real size matching its tags. Cards keep their text inside the centre 630×630 (`SAFE_WIDTH`) so square crops (WhatsApp, iMessage) still read.
