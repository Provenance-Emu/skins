"""The skin editor page (docs/edit.html, SkinKit#73) and its entry points.

The editor's logic is JavaScript: tests/js/editor/*.test.js covers the undo stack, snapping, frame math, patching
and the open → edit → export round trip, and tests/browser/editor.cjs drives the page in Chromium and WebKit.
This file holds what Python can check about the pieces around them: the page's wiring, the links that lead to it,
the build's cache-busting for its modules, and the CI jobs that run its tests.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
PAGE = DOCS / "edit.html"
PAGE_JS = DOCS / "js" / "edit-page.js"
EDITOR = DOCS / "js" / "editor"
WORKFLOWS = ROOT / ".github" / "workflows"


def test_page_ids_the_script_uses_exist():
    html = PAGE.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    js = PAGE_JS.read_text(encoding="utf-8")
    used = set(re.findall(r'\$\("([^"]+)"\)', js))
    assert not used - ids, f"edit-page.js reads ids that edit.html lacks: {sorted(used - ids)}"


def test_page_loads_the_script_and_pinned_jszip_and_has_the_merge_hook():
    html = PAGE.read_text(encoding="utf-8")
    assert re.search(r'<script type="module" src="js/edit-page\.js(\?v=[0-9a-f]{8})?">', html)
    assert "/jszip/3.10.1/" in html
    assert 'id="ed-merge-slot"' in html and "SkinKit#77" in html
    js = PAGE_JS.read_text(encoding="utf-8")
    assert "window.emuskinsEditor = { openSkin }" in js


def test_page_reads_and_writes_archives_through_the_stack():
    js = PAGE_JS.read_text(encoding="utf-8")
    for module in ("zip.js", "source.js", "art.js", "info.js", "validate.js"):
        assert f'./skin/{module}"' in js
    assert "JSZip" not in js, "the page has no zip code of its own"
    assert "pdfjsLib" not in js


def test_editor_modules_import_only_each_other_and_the_skin_stack():
    for path in EDITOR.glob("*.js"):
        for target in re.findall(r'from "([^"]+)"', path.read_text(encoding="utf-8")):
            assert re.fullmatch(r"\./[a-z]+\.js|\.\./skin/[a-z-]+\.js", target), f"{path.name} imports {target}"
            assert (path.parent / target).resolve().is_file(), f"{path.name} imports a file that is not there: {target}"


def test_entry_points_lead_to_the_page():
    modal = (DOCS / "js" / "browse.js").read_text(encoding="utf-8")
    assert "edit.html?skin=${encodeURIComponent(skin.id" in modal
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_skin_pages as skin_pages
    skin = {"id": "0123456789abcdef", "name": "Test Skin", "author": "Someone", "systems": ["snes"],
            "downloadURL": "https://example.com/test.deltaskin", "source": "test"}
    page = skin_pages.generate_skin_page(skin, system_pages=set(), author_pages=set())
    assert 'href="../edit.html?skin=0123456789abcdef"' in page
    assert PAGE.is_file()
    sitemap = (ROOT / "scripts" / "generate_sitemap.py").read_text(encoding="utf-8")
    assert '"edit.html"' in sitemap


def test_editor_reads_input_names_from_the_shared_table():
    assert 'fetch("js/skin/inputs.json")' in PAGE_JS.read_text(encoding="utf-8")
    assert json.loads((DOCS / "js" / "skin" / "inputs.json").read_text(encoding="utf-8"))["gameTypes"]


def test_build_versions_the_editor_modules_with_the_same_skin_hash():
    """A module has one URL or it loads twice, so the editor's imports of docs/js/skin/ carry the skin hash,
    its own files carry a hash of the editor plus the skin hash, and the page's tags are stamped."""
    wf = (WORKFLOWS / "build-catalog.yml").read_text(encoding="utf-8")
    assert "bash scripts/publish_site.sh" in wf
    assert "bash scripts/build_site.sh" in (ROOT / "scripts" / "publish_site.sh").read_text(encoding="utf-8")
    wf = (ROOT / "scripts" / "build_site.sh").read_text(encoding="utf-8")
    assert "EDIT_VER=" in wf and "docs/js/edit-page.js docs/js/editor/*.js" in wf
    assert re.search(r'skin/\[A-Za-z0-9_-\]\+\\\.js\)[^\n]*\?v=\$SKIN_VER[^\n]*docs/js/edit-page\.js docs/js/editor/\*\.js', wf)
    assert re.search(r'editor/[^\n]*\?v=\$EDIT_VER[^\n]*docs/js/edit-page\.js docs/js/editor/\*\.js', wf)
    assert "js/edit-page" in wf and "docs/edit.html" in wf
    assert "?v=" not in PAGE_JS.read_text(encoding="utf-8")
    for path in EDITOR.glob("*.js"):
        assert "?v=" not in path.read_text(encoding="utf-8"), f"{path.name}: the build adds ?v=, the source stays plain"


def test_ci_runs_the_editor_tests():
    test_yml = (WORKFLOWS / "test.yml").read_text(encoding="utf-8")
    assert test_yml.count('"docs/edit.html"') == 2, "both path filters include the page"
    assert "tests/js/editor" in (ROOT / "tests" / "js" / "package.json").read_text(encoding="utf-8") or \
        "editor/*.test.js" in (ROOT / "tests" / "js" / "package.json").read_text(encoding="utf-8")
    assert "editor.cjs" in (ROOT / "tests" / "browser" / "package.json").read_text(encoding="utf-8")
    assert list((ROOT / "tests" / "js" / "editor").glob("*.test.js"))
