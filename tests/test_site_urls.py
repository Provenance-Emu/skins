"""The site lives on emuskins.com; nothing under docs/ may point at the old hosts.

Covers committed generated output (sitemap, feed, system/author/skin pages) so
a stale copy on provenance-emu.com/skins or provenance-emu.github.io/skins
can't linger. Also checks the generators prune pages they no longer produce.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
sys.path.insert(0, str(ROOT / "scripts"))

import generate_author_pages as authors  # noqa: E402
import generate_system_pages as systems  # noqa: E402

OLD_HOSTS = ("provenance-emu.github.io/skins", "provenance-emu.com/skins")


def test_no_old_skins_hosts_under_docs():
    offenders = []
    for path in DOCS.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # images and other binaries
        for host in OLD_HOSTS:
            if host in text:
                offenders.append(f"{path.relative_to(ROOT)}: {host}")
    assert not offenders, "stale URLs:\n" + "\n".join(offenders)


def _catalog(tmp_path):
    skins = [
        {"id": f"a{i}", "name": f"Skin {i}", "author": "Kept Author",
         "systems": ["gba"], "downloadURL": f"https://example.com/{i}.deltaskin"}
        for i in range(3)
    ]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"skins": skins}), encoding="utf-8")
    return path


def test_author_pages_prune_orphans(tmp_path, monkeypatch):
    out = tmp_path / "authors"
    out.mkdir()
    (out / "gone-author.html").write_text("stale")
    monkeypatch.setattr(authors, "CATALOG_PATH", _catalog(tmp_path))
    monkeypatch.setattr(authors, "AUTHORS_DIR", out)
    authors.main()
    names = {p.name for p in out.glob("*.html")}
    assert "gone-author.html" not in names
    assert {"kept-author.html", "index.html"} <= names


def test_system_pages_prune_orphans(tmp_path, monkeypatch):
    out = tmp_path / "systems"
    out.mkdir()
    (out / "gamegear.html").write_text("stale")
    monkeypatch.setattr(systems, "CATALOG_PATH", _catalog(tmp_path))
    monkeypatch.setattr(systems, "SYSTEMS_DIR", out)
    systems.main()
    names = {p.name for p in out.glob("*.html")}
    assert "gamegear.html" not in names
    assert {"gba.html", "index.html"} <= names
