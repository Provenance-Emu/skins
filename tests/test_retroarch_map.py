"""The site's RetroArch input map is SkinKit's, byte for byte (Provenance-Emu/SkinKit#81).

docs/js/skin/retroarch-input-map.json is what the website converter uses. SkinKitRetroArch ships the same
file (Sources/SkinKitRetroArch/Resources/retroarch-input-map.json); its copy is vendored under
tests/fixtures/retroarch/skinkit/ at the commit in SOURCE, and SkinKit pins the same SHA-256 in its own
tests. So editing either copy alone fails a test: change the map in SkinKit first, then copy it here
(both files) and update PINNED_SHA256 in both repos.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).parent.parent
SITE_MAP = ROOT / "docs" / "js" / "skin" / "retroarch-input-map.json"
SKINKIT_MAP = ROOT / "tests" / "fixtures" / "retroarch" / "skinkit" / "retroarch-input-map.json"

# Same value as SkinKit's Tests/SkinKitRetroArchTests (RetroArchInputMapPinTests.pinnedSHA256).
PINNED_SHA256 = "dc0b9da4826e13c215a3008f4c4e6c5179b4ef5311ebd93b113cb91d7078e613"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_site_map_is_skinkits_copy():
    assert SITE_MAP.read_bytes() == SKINKIT_MAP.read_bytes(), (
        "docs/js/skin/retroarch-input-map.json differs from SkinKit's copy; change the map in SkinKit and "
        "copy it to both places")


def test_map_matches_the_pinned_hash():
    assert sha256(SITE_MAP) == PINNED_SHA256
    assert sha256(SKINKIT_MAP) == PINNED_SHA256
