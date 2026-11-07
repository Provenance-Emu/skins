#!/usr/bin/env bash
# Run only in a disposable CI checkout: every attempt discards the previous build.
set -euo pipefail

generated=(
  docs/catalog.json docs/catalog.min.json catalog.json added-dates.json
  badge-dates.json count-holds.json docs/creators.json docs/creators/
  docs/cards/ docs/s/ docs/systems/ docs/authors/ docs/sitemap.xml docs/feed.xml
  docs/index.html docs/submit.html docs/retroarch.html docs/edit.html
)
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'

for attempt in 1 2 3; do
  echo "Build/publish attempt $attempt of 3"
  # An explicit ref handles both advancing and force-updated main. Do not rebase
  # generated files: rebuild them from the new source, including deployment-only JS.
  git fetch origin +refs/heads/main:refs/remotes/origin/main
  git reset --hard refs/remotes/origin/main
  git clean -fd -- "${generated[@]}"
  bash scripts/build_site.sh

  paths=()
  for path in "${generated[@]}"; do
    if [[ -e "$path" ]] || git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
      paths+=("$path")
    fi
  done
  git add -A -- "${paths[@]}"
  if ! git diff --cached --quiet; then
    git commit -m 'chore: rebuild catalog + static pages [skip ci]'
  fi
  # Always push, even for a no-change build: this detects a main update during
  # generation. Never force push. A rejected attempt cannot upload/deploy Pages.
  if git push origin HEAD:refs/heads/main; then
    exit 0
  fi
  echo 'Push rejected; retrying with a fresh build of main.' >&2
done

echo 'Could not publish after 3 attempts; leaving Pages unchanged.' >&2
exit 1
