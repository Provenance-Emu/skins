"""The shared client-side skin stack (docs/js/skin/): link_health.py is the reference for validate.js.

tests/fixtures/skin-stack/validate-cases.json holds the expected verdicts for a set of synthetic
broken skins, fixtures/variants/ and the members of fixtures/merge/. This file checks that
link_health.classify_archive produces them; tests/js/skin-stack/validate.test.js checks that
docs/js/skin/validate.js produces the same, so the two stay equal without running one from the other.
The Node suites run here too when node and `npm ci` in tests/js are available (CI's `skin-stack` job always runs them).
"""

import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import link_health  # noqa: E402

SKIN_JS = ROOT / "docs" / "js" / "skin"
EDITOR_JS = ROOT / "docs" / "js" / "editor"
CASES = json.loads((ROOT / "tests" / "fixtures" / "skin-stack" / "validate-cases.json").read_text(encoding="utf-8"))


def build_zip(files: dict) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            if path.endswith("/"):
                zf.writestr(zipfile.ZipInfo(path), b"")
                continue
            if isinstance(content, dict):
                content = json.dumps(content["json"])
            zf.writestr(path, content.encode("utf-8"))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def zip_dir(folder: Path) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(folder).as_posix())
    buf.seek(0)
    return zipfile.ZipFile(buf)


def verdict(zf: zipfile.ZipFile) -> dict:
    result = link_health.classify_archive(zf)
    result.pop("error", None)  # parser wording differs between languages; the verdict is what is compared
    return result


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_synthetic_case_verdict(case):
    assert verdict(build_zip(case["files"])) == case["expected"]


@pytest.mark.parametrize("fixture", CASES["fixtures"], ids=lambda f: f["path"])
def test_fixture_verdict(fixture):
    path = ROOT / fixture["path"]
    zf = zip_dir(path) if fixture.get("zipDir") else zipfile.ZipFile(path)
    assert verdict(zf) == fixture["expected"]


def test_cases_cover_every_fixture_archive():
    listed = {f["path"] for f in CASES["fixtures"]}
    found = {p.relative_to(ROOT).as_posix() for ext in ("*.deltaskin", "*.manicskin")
             for p in (ROOT / "fixtures" / "variants").rglob(ext)}
    found |= {p.relative_to(ROOT).as_posix() for p in (ROOT / "fixtures" / "merge").glob("*/members/*") if p.is_dir()}
    assert found - listed == set(), "add new fixtures to validate-cases.json (see its note)"


def test_cases_exercise_every_verdict():
    seen = {c["expected"]["result"] for c in CASES["cases"]}
    assert {"ok", "no_info_json", "nested_folder", "pack", "bad_info_json", "info_missing_keys", "missing_artwork"} <= seen
    assert any("partialArtwork" in c["expected"] for c in CASES["cases"])


# ---------------------------------------------------------------------------
# The files themselves
# ---------------------------------------------------------------------------

def test_pure_modules_have_no_browser_or_network_code():
    pure = [SKIN_JS / n for n in ("info.js", "validate.js", "zip.js", "retroarch-convert.js")]
    pure += [p for p in EDITOR_JS.glob("*.js") if p.name not in ("surface.js", "draft.js")]  # surface: DOM; draft: IndexedDB
    for path in pure:
        name = path.name
        src = path.read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", src, flags=re.S)  # the header comments mention the DOM
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
        for forbidden in ("document.", "window.", "fetch(", "XMLHttpRequest", "localStorage", "import("):
            assert forbidden not in code, f"{name} uses {forbidden}"


def test_every_cdn_url_in_the_skin_stack_is_pinned():
    files = list(SKIN_JS.glob("*.js")) + list(EDITOR_JS.glob("*.js")) + [ROOT / "docs" / "js" / "retroarch-page.js", ROOT / "docs" / "js" / "submit.js", ROOT / "docs" / "js" / "edit-page.js"]
    urls = []
    for f in files:
        urls += re.findall(r"https://(?:cdnjs\.cloudflare\.com|cdn\.jsdelivr\.net|unpkg\.com)/[^\"'`\s)]+", f.read_text(encoding="utf-8"))
    assert any("pdf.js" in u for u in urls), "art.js loads pdf.js"
    for url in urls:
        assert re.search(r"[/@]\d+\.\d+\.\d+(?:/|$)", url), f"not pinned to an exact version: {url}"


@pytest.mark.parametrize("page", ["submit.html", "retroarch.html", "edit.html"])
def test_pages_load_jszip_pinned_with_integrity(page):
    html = (ROOT / "docs" / page).read_text(encoding="utf-8")
    tags = re.findall(r"<script [^>]*jszip[^>]*>", html, flags=re.S)
    assert len(tags) == 1
    assert "/jszip/3.10.1/" in tags[0]
    assert 'integrity="sha512-' in tags[0]


def test_submit_page_reads_archives_through_zip_js():
    js = (ROOT / "docs" / "js" / "submit.js").read_text(encoding="utf-8")
    assert 'from "./skin/zip.js"' in js
    assert "JSZip" not in js, "submit.js has no JSZip code of its own"
    html = (ROOT / "docs" / "submit.html").read_text(encoding="utf-8")
    # The catalog build appends `?v=<hash>` to the src, so allow it.
    assert re.search(r'<script type="module" src="js/submit\.js(\?v=[0-9a-f]{8})?">', html)


def test_converter_page_reads_archives_through_the_stack():
    js = (ROOT / "docs" / "js" / "retroarch-page.js").read_text(encoding="utf-8")
    for module in ("zip.js", "source.js", "art.js"):
        assert f'./skin/{module}"' in js
    assert "JSZip.loadAsync" not in js and "pdfjsLib" not in js


def test_inputs_table_is_well_formed():
    table = json.loads((SKIN_JS / "inputs.json").read_text(encoding="utf-8"))
    assert table["version"] == 1
    for key in ("directions", "startSelect", "frontend", "sticks", "default"):
        assert table[key] and all(isinstance(x, str) for x in table[key])
    assert "toggleAltRepresentations" in table["frontend"]
    ra = json.loads((SKIN_JS / "retroarch-input-map.json").read_text(encoding="utf-8"))
    for gt, entry in table["gameTypes"].items():
        assert re.match(r"(com\.rileytestut\.delta|public\.aoshuang)\.game\.\w+$", gt), gt
        if entry["system"] is None:
            assert entry["buttons"] is None, gt
        else:
            system = ra["systems"][entry["system"]]
            assert set(entry["buttons"]) == set(system["map"]) | set(system.get("aliases", {})), gt


@pytest.mark.skipif(shutil.which("node") is None or not (ROOT / "tests" / "js" / "node_modules" / "jszip").is_dir(),
                    reason="needs node and `npm ci` in tests/js")
def test_node_skin_stack_suite_passes():
    result = subprocess.run(["node", "--test", *sorted(str(p) for d in ("skin-stack", "editor") for p in (ROOT / "tests" / "js" / d).glob("*.test.js"))],
                            cwd=ROOT, capture_output=True, text=True, timeout=180)
    sys.stdout.write(result.stdout[-4000:])
    sys.stderr.write(result.stderr[-4000:])
    assert result.returncode == 0, "node --test tests/js/skin-stack tests/js/editor failed"


def test_build_workflow_versions_every_skin_module_import():
    """Imports in the committed source carry no ?v=; the build adds one hash to all of them (and to the
    pages' script tags) so a change to any docs/js/skin/ file busts every cached copy."""
    wf = (ROOT / ".github" / "workflows" / "build-catalog.yml").read_text(encoding="utf-8")
    assert "docs/js/skin/*.js docs/js/skin/*.json" in wf, "SKIN_VER hashes every skin module and table"
    for target in ("docs/js/retroarch-page.js docs/js/submit.js docs/js/skin/*.js", "js/submit", "js/retroarch-page"):
        assert target in wf, target
    for f in [ROOT / "docs" / "js" / "retroarch-page.js", ROOT / "docs" / "js" / "submit.js", ROOT / "docs" / "js" / "edit-page.js",
              *SKIN_JS.glob("*.js"), *EDITOR_JS.glob("*.js")]:
        assert "?v=" not in f.read_text(encoding="utf-8"), f"{f.name}: the build adds ?v=, the source stays plain"
