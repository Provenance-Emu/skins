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

# Run full test suite
pytest tests/ -v

# Run a single test file
pytest tests/test_skin_schema.py -v

# Generate static pages (system + author pages, RSS, sitemap)
python3 scripts/generate_system_pages.py
python3 scripts/generate_author_pages.py
python3 scripts/generate_rss.py
python3 scripts/generate_sitemap.py

# Crawl external sources for new skins (dry run)
python3 scripts/crawl_sources.py --dry-run

# Generate thumbnails
python3 scripts/generate_thumbnails.py
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
- `docs/authors/*.html` — built by `generate_author_pages.py`
- `docs/feed.xml`, `docs/sitemap.xml` — built by respective generators
- `thumbnails/*.png` — built by `generate_thumbnails.py`

### Skin JSON Schema

Required fields: `id`, `name`, `systems`, `downloadURL`, `source`

- **`id`**: 16-char lowercase hex, generated deterministically from `source + downloadURL` via `skin_schema.py:generate_id()`
- **`systems`**: array of system short codes (e.g., `["gba"]`). Valid codes defined in `SYSTEM_MAP` in `skin_schema.py`
- **`downloadURL`**: must end in `.deltaskin` or `.manicskin`
- Skins with unknown/multi-system mappings go under `skins/unofficial/`

### Key Modules (`scripts/`)

- **`skin_schema.py`** — shared schema, `SYSTEM_MAP` (150+ system name variants → short codes), ID generation, validation logic. This is the single source of truth for valid systems and field validation.
- **`build_catalog.py`** — catalog builder with GitHub Releases download count fetching
- **`extract_metadata.py`** — extracts `info.json` from skin ZIP archives via HTTP range requests (≤4 requests, falls back to full download)
- **`process_submission.py`** — handles 4 submission types: direct skin URL, GitHub repo URL, GitHub release URL, JSON metadata URL
- **`crawl_sources.py`** — weekly crawler consuming `sources.json` to discover new skins from external repos and sites

### CI/CD Workflows (`.github/workflows/`)

- **build-catalog.yml** — rebuilds catalog + static pages on push to main
- **process-submission.yml** — processes skin submissions from GitHub Issues
- **crawl-sources.yml** — weekly Monday 3am UTC crawl of external sources
- **test.yml** — pytest on Python 3.11 & 3.12 when `scripts/` or `tests/` change
- **validate-pr.yml** — validates changed skin JSON files in PRs
- **generate-thumbnails.yml** — generates thumbnails, uploads to GitHub Releases (`thumbnails` tag)

### Thumbnail System

Thumbnails are stored in GitHub Releases (tag: `thumbnails`) and referenced by `thumbnailURL` in skin JSON. The workflow uses smart rebasing to avoid merge conflicts on concurrent updates.

## Adding a New Skin

1. Create a JSON file at `skins/{system}/{slug}.json` with required fields
2. Generate the `id` using `skin_schema.generate_id(source, downloadURL)`
3. Run `python3 scripts/validate_skin.py skins/{system}/{slug}.json` to validate
4. The catalog and static pages are regenerated automatically on merge
