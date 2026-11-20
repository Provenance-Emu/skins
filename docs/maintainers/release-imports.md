# Creator release packs

Register the creator's repository and attribution in sources.json. Add
releaseTags with the approved stable release tags, newest first. Tags are
explicit so releases with older incompatible controls can remain archived.

The weekly source crawler imports configured release packs before scanning
repository files. It validates root skins, skins inside folders, and nested ZIP
packs. New skins are extracted to individual mirror assets the apps can install.

Preview a registered source without publishing:

    python3 scripts/import_release_skins.py --repo Artist/skins --tag v2 --tag v1

Add --publish after reviewing the report. All comparisons and validation finish
before uploading. The command uploads new files, writes their variants sidecar,
and atomically adds metadata files. Existing listings and IDs are preserved.

## Duplicate checks

The importer first reads every existing catalog archive credited to the author,
including packs previously imported from DeltaStyles. It compares contained
files using a fingerprint independent of ZIP compression, member order and
info.json formatting. Copies repeated in starter packs and regular releases
are skipped. Existing identifiers or names with changed content are counted
separately and skipped, pending a reviewed update to the original listing.

An unreadable existing archive stops publication. Supply the original pack
from a backup or the creator as <catalog-id>.zip in a directory and pass
--baseline-dir DIRECTORY. This supplies comparison data when the original host
is unavailable. Preserve original pack contents when preparing this directory.

## TheMameKing onboarding

The first import needs original packs for comparison. During verification,
listing b8fd6cecf5c68c3d pointed to the following URL, which returned 404:

https://deltastyles.com/files/skins/783/1-Button-Dpad-Tate.zip

Obtain original packs, or review an explicit migration of the old listings,
before adding releaseTags to this source. Leave Legacy releases out of the tag
list because they use different Manic input mappings.

A source registration alone scans repository files. Release imports start only
after releaseTags is configured. A manual dry run with --repo and --tag is
available before configuring the weekly import.
