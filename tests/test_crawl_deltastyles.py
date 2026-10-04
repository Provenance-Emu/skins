"""Tests for the deltastyles.com scraper's system detection.

deltastyles.com has no GameCube/Wii category, so those skins show up under
Arcade. The scraper must trust the skin's own `gameTypeIdentifier` over the
listing category. Network access is fully mocked.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import crawl_sources as cs

GC_URL = "https://deltastyles.com/files/skins/760/gamecubepocket.manicskin"
ARCADE_URL = "https://deltastyles.com/files/skins/613/mortalkombat1992.manicskin"


class _FakeResponse:
    def __init__(self, body=b"<html></html>"):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def scrape(monkeypatch):
    """Run scrape_deltastyles(['arcade']) against a stubbed listing + resolver."""
    monkeypatch.setattr(cs.time, "sleep", lambda *_: None)
    monkeypatch.setattr(cs.urllib.request, "urlopen", lambda *a, **k: _FakeResponse())

    def run(skins, variants_by_path, info_by_url):
        monkeypatch.setattr(cs, "_deltastyles_parse_listing", lambda html: skins)
        monkeypatch.setattr(
            cs, "_deltastyles_resolve_variants", lambda path: variants_by_path[path]
        )

        def fake_info(url, token=""):
            result = info_by_url[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(cs, "stream_extract_info_json", fake_info)
        return cs.scrape_deltastyles(["arcade"])

    return run


def _skin(path, name):
    return {"_detail_path": path, "name": name, "author": "someone"}


class TestDeltaStylesGtiRouting:
    def test_gamecube_skin_in_arcade_bucket_routes_to_gamecube(self, scrape):
        entries = scrape(
            [_skin("/skins/760-gamecube-pocket", "GameCube Pocket")],
            {"/skins/760-gamecube-pocket": [{"downloadURL": GC_URL, "label": "gamecubepocket"}]},
            {GC_URL: {"gameTypeIdentifier": "public.aoshuang.game.ngc"}},
        )
        assert [e["systems"] for e in entries] == [["gamecube"]]
        assert entries[0]["gameTypeIdentifier"] == "public.aoshuang.game.ngc"

    def test_real_arcade_skin_stays_mame(self, scrape):
        entries = scrape(
            [_skin("/skins/613-mortal-kombat-1992", "Mortal Kombat 1992")],
            {"/skins/613-mortal-kombat-1992": [{"downloadURL": ARCADE_URL, "label": "mk"}]},
            {ARCADE_URL: {"gameTypeIdentifier": "public.aoshuang.game.arcade"}},
        )
        assert entries[0]["systems"] == ["mame"]

    def test_info_json_failure_falls_back_to_category(self, scrape):
        entries = scrape(
            [_skin("/skins/760-gamecube-pocket", "GameCube Pocket")],
            {"/skins/760-gamecube-pocket": [{"downloadURL": GC_URL, "label": "gamecubepocket"}]},
            {GC_URL: OSError("range requests unsupported")},
        )
        assert entries[0]["systems"] == ["mame"]  # listing-category fallback
        assert entries[0]["gameTypeIdentifier"] is None

    def test_delta_identifier_does_not_override_category(self, scrape):
        """A Delta id is a container stand-in for systems Delta can't run (e.g. a
        3DS-layout skin that declares com.rileytestut.delta.game.ds); the listing
        category stays authoritative and the id is still recorded."""
        entries = scrape(
            [_skin("/skins/700-retro-3ds", "Retro New 3DS Pack")],
            {"/skins/700-retro-3ds": [{"downloadURL": ARCADE_URL, "label": "retro"}]},
            {ARCADE_URL: {"gameTypeIdentifier": "com.rileytestut.delta.game.ds"}},
        )
        assert entries[0]["systems"] == ["mame"]  # stub listing category is arcade
        assert entries[0]["gameTypeIdentifier"] == "com.rileytestut.delta.game.ds"

    def test_manic_identifier_overrides_category(self, scrape):
        entries = scrape(
            [_skin("/skins/760-gamecube-pocket", "GameCube Pocket")],
            {"/skins/760-gamecube-pocket": [{"downloadURL": GC_URL, "label": "gamecubepocket"}]},
            {GC_URL: {"gameTypeIdentifier": "public.aoshuang.game.ngc"}},
        )
        assert entries[0]["systems"] == ["gamecube"]

    def test_info_json_beats_filename_token(self, scrape):
        """Per-variant: the identifier wins over a system token in the filename."""
        path = "/skins/764-turbopocket-16"
        urls = [
            "https://deltastyles.com/files/skins/764/turbopocket16.manicskin",
            "https://deltastyles.com/files/skins/764/pocketengine-gba.manicskin",
        ]
        entries = scrape(
            [_skin(path, "TurboPocket-16")],
            {path: [{"downloadURL": u, "label": u.rsplit("/", 1)[1][:-10]} for u in urls]},
            {u: {"gameTypeIdentifier": "public.aoshuang.game.pce"} for u in urls},
        )
        assert [e["systems"] for e in entries] == [["pce"], ["pce"]]
