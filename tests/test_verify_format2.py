"""The catalog accepts canonical format 2 metadata and hides changed classic bakes."""

import io
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

import link_health
from variants_sidecar import merge_variants, update_from_results, validate_store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def baked():
    if not shutil.which("node"):
        pytest.skip("the format 2 verifier requires Node")
    result = subprocess.run(
        ["node", "--input-type=module", "-e", """
import { readFile } from "node:fs/promises";
import { bakeClassic } from "./docs/js/skin2/bake.js";
import { nativeSize } from "./tools/skin2/native-size.mjs";
const source = await readFile("fixtures/format2/gamecube-icube/skin.json");
const empty = async () => new Uint8Array();
const [bundle] = await bakeClassic(source, new Map(), { nativeSize, pdf: empty, preview: empty });
process.stdout.write(JSON.stringify([...bundle.files].map(([name, data]) => [name, Buffer.from(data).toString("utf8")])));
"""],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return dict(json.loads(result.stdout))


def classify(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    data.seek(0)
    with zipfile.ZipFile(data) as archive:
        return link_health.classify_archive(archive)


def test_canonical_bake_becomes_responsive_catalog_entry(baked):
    verdict = classify(baked)
    assert verdict["result"] == "ok"
    assert verdict["format2"] is True
    entry = {"id": "cube", "downloadURL": "https://example.invalid/cube.deltaskin"}
    store = {}
    update_from_results(store, [entry], {"cube": verdict}, link_health.PERMANENT)
    assert validate_store(store) == []
    merge_variants([entry], store)
    assert entry["format2"] is True
    stale = {"id": "cube", "downloadURL": "https://example.invalid/other.deltaskin"}
    merge_variants([stale], store)
    assert "format2" not in stale


def test_tampered_bake_is_hidden_after_repeated_health_failures(baked):
    info = json.loads(baked["info.json"])
    info["representations"]["iphone"]["edgeToEdge"]["portrait"]["items"][0]["frame"]["x"] += 1
    verdict = classify({**baked, "info.json": json.dumps(info)})
    assert verdict["result"] == "invalid_format2"
    assert "format2" not in verdict
    entry = {"id": "cube", "downloadURL": "https://example.invalid/cube.deltaskin"}
    results = {"cube": verdict}
    first = link_health.update_health({}, [entry], results, "2026-01-01")
    second = link_health.update_health(first, [entry], results, "2026-01-08")
    assert link_health.is_hidden(second["skins"]["cube"], entry["downloadURL"])


def test_missing_baked_knob_fails_validation(baked):
    name = next(path for path in baked if "-knob-" in path)
    verdict = classify({path: data for path, data in baked.items() if path != name})
    assert verdict["result"] == "invalid_format2"
    assert name in verdict["error"]
