"""The RetroArch converter page (docs/retroarch.html) and its pure module.

The conversion logic is JavaScript (docs/js/skin/retroarch-convert.js) so the
page can run it in the browser; tests/js/retroarch_convert.test.js exercises it
under Node, and this file runs that suite when node is installed. The rest
checks what Python can: the page's third-party scripts are pinned to exact
versions, the files the page loads exist, and the mapping table is well formed.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
PAGE = DOCS / "retroarch.html"
MODULE = DOCS / "js" / "skin" / "retroarch-convert.js"
PAGE_JS = DOCS / "js" / "retroarch-page.js"
MAP = DOCS / "js" / "skin" / "retroarch-input-map.json"

# RetroArch bind ids from configuration.c input_config_bind_map that skins can target.
RETROARCH_BINDS = {
    "a", "b", "x", "y", "l", "r", "l2", "r2", "l3", "r3", "start", "select",
    "up", "down", "left", "right",
    "l_x_plus", "l_x_minus", "l_y_plus", "l_y_minus", "r_x_plus", "r_x_minus", "r_y_plus", "r_y_minus",
    "analog_left", "analog_right", "overlay_next", "menu_toggle", "toggle_fast_forward", "hold_fast_forward",
    "save_state", "load_state", "screenshot", "rewind", "pause_toggle", "reset",
}


def test_page_pins_every_cdn_script():
    html = PAGE.read_text(encoding="utf-8")
    urls = re.findall(r'https://cdnjs\.cloudflare\.com/[^"\s]+', html)
    urls += re.findall(r'https://cdnjs\.cloudflare\.com/[^"\s]+', PAGE_JS.read_text(encoding="utf-8"))
    assert urls, "the page loads pdf.js and JSZip from cdnjs"
    for url in urls:
        assert re.search(r"/\d+\.\d+\.\d+/", url), f"not pinned to an exact version: {url}"
    # A classic <script> from a CDN carries an integrity hash.
    for tag in re.findall(r"<script [^>]*src=\"https://[^>]+>", html):
        assert 'integrity="sha' in tag, f"missing integrity: {tag}"


def test_page_loads_files_that_exist():
    html = PAGE.read_text(encoding="utf-8")
    for src in re.findall(r'(?:src|href)="((?!https?:)[^"#]+)"', html):
        path = src.split("?", 1)[0]
        assert (DOCS / path).exists(), f"retroarch.html references missing {path}"
    page_js = PAGE_JS.read_text(encoding="utf-8")
    assert 'import * as RA from "./skin/retroarch-convert.js"' in page_js
    assert 'fetch("js/skin/retroarch-input-map.json")' in page_js
    assert MODULE.exists() and MAP.exists()


def test_page_credits_prior_art_and_documents_install():
    html = PAGE.read_text(encoding="utf-8")
    assert "github.com/warmenhoven/skin2overlay" in html
    assert "own implementation" in html
    assert "RetroArch › RetroArch › overlays" in html
    assert "Overlay Preset" in html
    assert "touch" in html.lower(), "lists DS touch as unconvertible"


def test_input_map_is_well_formed():
    data = json.loads(MAP.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert "default" in data["systems"]
    binds = set()
    for token, bind in data["common"].items():
        assert isinstance(token, str)
        if bind is not None:
            binds.add(bind)
        else:
            assert token in data["unconvertibleReasons"], f"{token} is null without a reason"
    for name, sys_entry in data["systems"].items():
        assert "map" in sys_entry, name
        assert "assumes" in sys_entry, name
        binds.update(sys_entry["map"].values())
        for alias, target in sys_entry.get("aliases", {}).items():
            assert target in sys_entry["map"] or target in data["common"], f"{name} alias {alias} -> {target} dangling"
    unknown = binds - RETROARCH_BINDS
    assert not unknown, f"not RetroArch bind ids: {sorted(unknown)}"
    for gt, system in data["gameTypes"].items():
        assert system in data["systems"], f"{gt} -> {system} has no systems entry"


def test_module_has_no_browser_or_network_code():
    src = MODULE.read_text(encoding="utf-8")
    for forbidden in ("document.", "window.", "fetch(", "XMLHttpRequest", "localStorage"):
        assert forbidden not in src, f"pure module uses {forbidden}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_node_suite_passes():
    """The real conversion checks live in tests/js/; run them under Node's test runner."""
    result = subprocess.run(
        ["node", "--test", *sorted(str(p) for p in (ROOT / "tests" / "js").glob("*.test.js"))],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    sys.stdout.write(result.stdout[-4000:])
    sys.stderr.write(result.stderr[-4000:])
    assert result.returncode == 0, "node --test tests/js failed"


def test_skin_pages_link_the_converter():
    """SkinKit#23: every skin page offers the RetroArch conversion, and DS/3DS
    pages say the touch screen is not converted."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_skin_pages as skin_pages
    base = {"id": "0123456789abcdef", "name": "Test Skin", "author": "Someone",
            "downloadURL": "https://example.com/test.deltaskin", "source": "test"}
    snes = skin_pages.generate_skin_page(dict(base, systems=["snes"]), system_pages=set(), author_pages=set())
    assert 'href="../retroarch.html?skin=0123456789abcdef"' in snes
    assert (ROOT / "docs" / "retroarch.html").is_file(), "the link from docs/s/ must reach a real page"
    assert "touch-screen input" not in snes
    for code in ("nds", "threeDS"):
        page = skin_pages.generate_skin_page(dict(base, systems=[code]), system_pages=set(), author_pages=set())
        assert 'retroarch.html?skin=0123456789abcdef' in page
        assert "touch-screen input from the screen itself" in page


def test_browse_modal_links_the_converter():
    src = (ROOT / "docs" / "js" / "browse.js").read_text(encoding="utf-8")
    assert "retroarch.html?skin=${encodeURIComponent(skin.id" in src
