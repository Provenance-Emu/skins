#!/usr/bin/env bash
set -euo pipefail

# Writes added-dates.json too (committed below); the first run backfills every file.
# The previous docs/catalog.json is the baseline for the thumbnail-count guard.
FLAGS=""
if [ "$ACCEPT_COUNT_JUMPS" = "true" ]; then FLAGS="--accept-count-jumps"; fi
python3 scripts/build_catalog.py --output docs/catalog.json $FLAGS
# Also write to repo root so the app can fetch via raw.githubusercontent.com/…/main/catalog.json
cp docs/catalog.json catalog.json

python3 scripts/compute_creator_stats.py

python3 scripts/generate_share_cards.py

python3 scripts/generate_system_pages.py
python3 scripts/generate_author_pages.py
python3 scripts/generate_skin_pages.py
python3 scripts/generate_sitemap.py
python3 scripts/generate_rss.py

CSS_VER=$(md5sum docs/style.css | cut -c1-8)
JS_VER=$(md5sum docs/js/browse.js | cut -c1-8)
# Idempotent: replaces existing ?v=... or bare filename
# The shared skin modules (docs/js/skin/) import each other and the pages import them, with
# no version in the committed source. Hash them with any ?v= stripped, then give every
# relative import and skin JSON fetch the same ?v= so one changed file busts them all
# (the service worker serves ?v= URLs cache-first, so an unversioned import would go stale).
# This edits the build copy that gets deployed; the commit step below only adds HTML/generated files.
strip_v() { sed -E 's/\?v=[0-9a-f]{8}//g' "$@"; }
SKIN_VER=$(strip_v docs/js/skin/*.js docs/js/skin/*.json | md5sum | cut -c1-8)
RA_VER=$(strip_v docs/js/retroarch-page.js | cat - <(echo "$SKIN_VER") | md5sum | cut -c1-8)
SUBMIT_VER=$(strip_v docs/js/submit.js | cat - <(echo "$SKIN_VER") | md5sum | cut -c1-8)
sed -i -E "s#(from \"\./(skin/)?[A-Za-z0-9_-]+\.js)(\?v=[0-9a-f]{8})?\"#\1?v=$SKIN_VER\"#g" docs/js/retroarch-page.js docs/js/submit.js docs/js/skin/*.js
sed -i -E "s#(fetch\(\"js/skin/[A-Za-z0-9_-]+\.json)(\?v=[0-9a-f]{8})?\"#\1?v=$SKIN_VER\"#g" docs/js/retroarch-page.js
# The editor (docs/edit.html, docs/js/edit-page.js, docs/js/editor/) imports the skin modules with
# the same SKIN_VER (a module must have one URL, or it loads twice) and its own files with EDIT_VER,
# which also changes whenever a skin module does.
EDIT_VER=$(strip_v docs/js/edit-page.js docs/js/editor/*.js | cat - <(echo "$SKIN_VER") | md5sum | cut -c1-8)
sed -i -E "s#(from \"(\./|\.\./)skin/[A-Za-z0-9_-]+\.js)(\?v=[0-9a-f]{8})?\"#\1?v=$SKIN_VER\"#g" docs/js/edit-page.js docs/js/editor/*.js
sed -i -E "s#(from \"(\./editor/|\./)[A-Za-z0-9_-]+\.js)(\?v=[0-9a-f]{8})?\"#\1?v=$EDIT_VER\"#g" docs/js/edit-page.js docs/js/editor/*.js
sed -i -E "s#(fetch\(\"js/skin/[A-Za-z0-9_-]+\.json)(\?v=[0-9a-f]{8})?\"#\1?v=$SKIN_VER\"#g" docs/js/edit-page.js
sed -i "s|href=\"style\.css[^\"]*\"|href=\"style.css?v=$CSS_VER\"|g" docs/index.html docs/submit.html docs/retroarch.html docs/edit.html
sed -i "s|src=\"js/browse\.js[^\"]*\"|src=\"js/browse.js?v=$JS_VER\"|g" docs/index.html
sed -i "s|src=\"js/retroarch-page\.js[^\"]*\"|src=\"js/retroarch-page.js?v=$RA_VER\"|g" docs/retroarch.html
sed -i "s|src=\"js/edit-page\.js[^\"]*\"|src=\"js/edit-page.js?v=$EDIT_VER\"|g" docs/edit.html
sed -i "s|src=\"js/submit\.js[^\"]*\"|src=\"js/submit.js?v=$SUBMIT_VER\"|g" docs/submit.html
echo "CSS hash: $CSS_VER  JS hash: $JS_VER"
