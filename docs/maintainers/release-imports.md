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

## Canonical source migrations

When a creator's GitHub releases have been approved as the authoritative source,
prepare a complete inventory without reading retired download hosts:

    python3 scripts/migrate_release_source.py --repo Artist/skins --tag v2 --tag v1 --stage build/artist

Review the generated plan. It deduplicates releases and starter packs and keeps
an existing ID only for a unique same-system name match to a single skin.
Exact copies under multiple old IDs keep the most-used, then oldest ID. Other duplicate IDs redirect to that skin. Pack-level and unmatched obsolete listings are retired. Their old shared links
redirect to the creator's updated collection.

Publish validated assets and apply the local metadata changes for a review PR:

    python3 scripts/migrate_release_source.py --repo Artist/skins --stage build/artist --publish

The tool validates original metadata hashes and staged file hashes before
publication. Mirror assets are split into releases of at most 900 files and
confirmed uploads are reused on retry. Commit the resulting metadata,
skin-redirects.json, and generated migration report in the same PR.

Set canonical to true on the source registration so later external-site crawls
do not reintroduce retired listings under the same author name. Add releaseTags
for the current approved releases, newest first. Exclude legacy releases with
incompatible button mappings.

TheMameKing's migration uses the current public releases and excludes all
Legacy tags. It preserves 176 existing IDs, retires 160 obsolete or pack-level
records, and skips 140 copies repeated across release packs. The generated
themameking-migration.json report records every retirement.
