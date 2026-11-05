"""The website's RetroArch converter matches SkinKitRetroArch byte for byte (Provenance-Emu/SkinKit#81).

tests/fixtures/retroarch/skinkit/ is SkinKit's Tests/SkinKitRetroArchTests/Fixtures, vendored at the commit in
its SOURCE file: the cases, their info.json files and the .cfg and README SkinKit's tests expect.
scripts/retroarch_cfg.mjs runs docs/js/skin/retroarch-convert.js, with the site's input map, over every case.
Each case must produce exactly SkinKit's expected text. When the converter changes on purpose, regenerate
SkinKit's expected files (scripts/gen-retroarch-expected.mjs there), land that, and re-vendor them here.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "retroarch" / "skinkit"
CASES = [c["id"] for c in json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))]


@pytest.fixture(scope="module")
def site_output():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        ["node", str(ROOT / "scripts" / "retroarch_cfg.mjs"), str(FIXTURES)],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_fixture_set_is_complete():
    assert len(CASES) >= 20 and len(set(CASES)) == len(CASES)
    for case in CASES:
        assert (FIXTURES / "expected" / f"{case}.cfg").is_file(), case
        assert (FIXTURES / "expected" / f"{case}.README.txt").is_file(), case
    assert (FIXTURES / "SOURCE").read_text(encoding="utf-8").startswith("Provenance-Emu/SkinKit ")


@pytest.mark.parametrize("case", CASES)
def test_cfg_matches_skinkit(site_output, case):
    expected = (FIXTURES / "expected" / f"{case}.cfg").read_text(encoding="utf-8")
    assert site_output[case]["cfg"] == expected


@pytest.mark.parametrize("case", CASES)
def test_readme_matches_skinkit(site_output, case):
    expected = (FIXTURES / "expected" / f"{case}.README.txt").read_text(encoding="utf-8")
    assert site_output[case]["readme"] == expected
