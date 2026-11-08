"""Thumbnail release shards (SkinKit#128).

A GitHub release holds at most 1000 assets, and the `thumbnails` release hit that
cap. Thumbnails now live in a family of releases: `thumbnails` (the original),
`thumbnails-2`, `thumbnails-3`, ... Every asset is named `{skin id}.png` or
`{skin id}-landscape.png`, and a given name lives in exactly one shard.

Rules this module holds for everything that touches the releases:

  - Nothing ever moves. Catalog entries (and the app builds that cached them)
    keep pointing at the URL they have; `thumbnails` keeps every asset it has until
    `prune_thumbnails.py` removes an orphan.
  - An asset that already exists is replaced in the shard it is in.
  - A new asset goes to the first shard with room under SOFT_CAP (the margin
    covers re-uploads and a concurrent run). When every shard is full the next
    `thumbnails-N` is created by the CI job that needs it.
  - A skin's portrait and landscape images share a shard.

The app reads `thumbnailURL` from the catalog as given, so none of this changes
what a client does.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Callable

REPO = "Provenance-Emu/skins"
BASE_TAG = "thumbnails"
HARD_CAP = 1000            # GitHub's limit on assets per release
SOFT_CAP = 950             # a new asset only goes to a shard below this
MAX_SHARDS = 50            # a safety stop for discovery and tag creation
ASSETS_PER_PAGE = 100
MAX_ASSET_PAGES = 100      # 10,000 assets per release is far past the cap

SHARD_TAG_RE = re.compile(r"^thumbnails(?:-([2-9]|[1-9]\d+))?$")
ASSET_NAME_RE = re.compile(r"^([0-9a-f]{16})(-landscape)?\.png$")

GetJson = Callable[[str], object]


# ---------------------------------------------------------------------------
# Tags, names and URLs
# ---------------------------------------------------------------------------

def is_shard_tag(tag: str) -> bool:
    return isinstance(tag, str) and SHARD_TAG_RE.fullmatch(tag) is not None


def shard_number(tag: str) -> int:
    """1 for `thumbnails`, N for `thumbnails-N`. ValueError for anything else."""
    m = SHARD_TAG_RE.fullmatch(tag)
    if not m:
        raise ValueError(f"not a thumbnail shard tag: {tag!r}")
    return int(m.group(1)) if m.group(1) else 1


def tag_for_number(n: int) -> str:
    if n < 1:
        raise ValueError("shard numbers start at 1")
    return BASE_TAG if n == 1 else f"{BASE_TAG}-{n}"


def sort_tags(tags) -> list[str]:
    return sorted((t for t in tags if is_shard_tag(t)), key=shard_number)


def next_tag(tags) -> str:
    """The tag after the highest existing shard (`thumbnails-2` when only
    `thumbnails` exists)."""
    numbers = [shard_number(t) for t in tags if is_shard_tag(t)]
    return tag_for_number(max(numbers, default=0) + 1)


def parse_asset_name(name: str):
    """(skin id, is_landscape) for `{16 hex}.png` / `{16 hex}-landscape.png`, else None."""
    m = ASSET_NAME_RE.fullmatch(name or "")
    if not m:
        return None
    return m.group(1), bool(m.group(2))


def download_url(tag: str, name: str, repo: str = REPO) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"


def _release_url_re(repo: str):
    return re.compile(
        rf"^https://github\.com/{re.escape(repo)}/releases/download/([^/?#]+)/([^/?#]+)$")


def parse_release_url(url, repo: str = REPO):
    """(tag, asset name) of one of our own thumbnail release URLs, else None.
    Only shard tags qualify: a URL aimed at another release (`mirror`) is not ours."""
    if not isinstance(url, str):
        return None
    m = _release_url_re(repo).match(url)
    if not m or not is_shard_tag(m.group(1)):
        return None
    return m.group(1), m.group(2)


def raw_base(repo: str = REPO) -> str:
    return f"https://raw.githubusercontent.com/{repo}/main/thumbnails"


def parse_raw_url(url, repo: str = REPO):
    """The file name of a thumbnail served from the repo's `thumbnails/` folder
    (the fallback used when the release upload failed), else None."""
    if not isinstance(url, str):
        return None
    prefix = raw_base(repo) + "/"
    if not url.startswith(prefix):
        return None
    name = url[len(prefix):]
    return name if parse_asset_name(name) else None


def is_own_thumbnail_url(url, repo: str = REPO) -> bool:
    """A thumbnail we host: any shard of the release family, or the repo folder."""
    if not isinstance(url, str):
        return False
    return parse_release_url(url, repo) is not None or url.startswith(raw_base(repo) + "/")


def tag_for_removal(urls, name: str, repo: str = REPO) -> str:
    """The release holding `name` for a removed skin, from the skin's own URLs.
    Only a URL whose file name is exactly `name` and whose tag is a shard tag counts,
    so a skin file can't aim the cleanup at another release or another skin's asset.
    Falls back to the original `thumbnails`."""
    for url in urls:
        parsed = parse_release_url(url, repo)
        if parsed and parsed[1] == name:
            return parsed[0]
    return BASE_TAG


# ---------------------------------------------------------------------------
# Reading the releases
# ---------------------------------------------------------------------------

def http_get_json(url: str, token: str = ""):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Provenance-SkinCatalog/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def discover_shard_releases(get_json: GetJson = http_get_json, repo: str = REPO) -> list[dict]:
    """Every release of the family, lowest shard first. Raises on a request error:
    a caller that can't tell which shards exist must not guess."""
    found = []
    for page in range(1, 11):
        batch = get_json(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}")
        found.extend(r for r in batch if is_shard_tag(r.get("tag_name")))
        if len(batch) < 100:
            break
    found.sort(key=lambda r: shard_number(r["tag_name"]))
    return found[:MAX_SHARDS]


def list_release_assets(release: dict, get_json: GetJson = http_get_json) -> list[dict]:
    """Every asset of a release. The release object only embeds the first assets,
    so the list is paged through its `assets_url` until a short page."""
    assets_url = release.get("assets_url")
    if not assets_url:
        return list(release.get("assets", []))
    assets: list[dict] = []
    for page in range(1, MAX_ASSET_PAGES + 1):
        batch = get_json(f"{assets_url}?per_page={ASSETS_PER_PAGE}&page={page}")
        assets.extend(batch)
        if len(batch) < ASSETS_PER_PAGE:
            break
    return assets


# ---------------------------------------------------------------------------
# Choosing where an upload goes
# ---------------------------------------------------------------------------

def pick_tag(sizes: dict[str, int], need: int = 1, soft_cap: int = SOFT_CAP) -> str:
    """The first shard that can take `need` more assets and stay at or under
    `soft_cap`; when none can, the tag of the next shard to create."""
    for tag in sort_tags(sizes):
        if sizes[tag] + need <= soft_cap:
            return tag
    return next_tag(sizes) if sizes else BASE_TAG


class ShardSet:
    """The family of releases as one store. Side effects go through callables, so
    tests (and dry runs) don't touch the network:

      create_release(tag) -> release dict with `id` and `upload_url`
      upload(release, name, data) -> browser_download_url or None
      delete(asset_id) -> None
    """

    def __init__(self, releases: dict[str, dict], index: dict[str, tuple[str, int]],
                 create_release, upload, delete, soft_cap: int = SOFT_CAP):
        self.releases = dict(releases)                       # tag -> release
        self.index = dict(index)                             # asset name -> (tag, asset id)
        self.create_release = create_release
        self._upload = upload
        self._delete = delete
        self.soft_cap = soft_cap

    @classmethod
    def load(cls, create_release, upload, delete, token: str = "", repo: str = REPO,
             soft_cap: int = SOFT_CAP, get_json=None) -> "ShardSet":
        get = get_json or (lambda url: http_get_json(url, token))
        releases, index = {}, {}
        for rel in discover_shard_releases(get, repo):
            releases[rel["tag_name"]] = rel
            for asset in list_release_assets(rel, get):
                name = asset["name"]
                if name in index:
                    # One name in two shards breaks the one-home rule; the first
                    # (lowest) shard wins and the duplicate is left for prune to report.
                    continue
                index[name] = (rel["tag_name"], asset["id"])
        return cls(releases, index, create_release, upload, delete, soft_cap)

    def sizes(self) -> dict[str, int]:
        sizes = {tag: 0 for tag in self.releases}
        for tag, _ in self.index.values():
            sizes[tag] = sizes.get(tag, 0) + 1
        return sizes

    def tag_for(self, name: str, need: int = 1) -> str:
        """Where `name` goes: the shard it is already in, else the first with room."""
        if name in self.index:
            return self.index[name][0]
        return pick_tag(self.sizes() or {BASE_TAG: 0}, need, self.soft_cap)

    def _release(self, tag: str) -> "dict | None":
        if tag not in self.releases:
            rel = self.create_release(tag)
            if not rel:
                return None
            self.releases[tag] = rel
        return self.releases[tag]

    def upload(self, name: str, data: bytes, tag: "str | None" = None, need: int = 1) -> "str | None":
        """Store `data` as `name`. Returns the download URL, or None when the upload
        failed (the caller falls back to repo storage). An existing asset is replaced
        in its own shard; `tag` picks the shard for a new one (a landscape image
        follows its portrait)."""
        if name in self.index:
            tag = self.index[name][0]
        elif tag is None:
            tag = self.tag_for(name, need)
        release = self._release(tag)
        if release is None:
            return None
        previous = self.index.pop(name, None)
        if previous and previous[1]:
            self._delete(previous[1])
        url = self._upload(release, name, data)
        if url:
            # Id 0: this run uploaded it and has no reason to delete it again, but
            # the entry keeps the shard's size right for the next pick.
            self.index[name] = (tag, 0)
        return url
