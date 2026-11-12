import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.review_skin_upload import review_bundle


def make_bundle(path, *, entry="skin-1.deltaskin", permission=True, compression=0):
    skin = io.BytesIO()
    with ZipFile(skin, "w") as archive:
        archive.writestr("info.json", "{}")
    with ZipFile(path, "w", compression=compression) as archive:
        archive.writestr("submission.json", json.dumps({
            "author": "Pilot Creator",
            "sourceURL": "https://example.com/creator",
            "permission": permission,
            "files": [{"path": entry, "name": "Original.deltaskin"}],
        }))
        archive.writestr(entry, skin.getvalue())
    return skin.getvalue()


def test_extract_for_review(tmp_path):
    bundle, out = tmp_path / "bundle.zip", tmp_path / "review"
    skin = make_bundle(bundle)
    review_bundle(bundle, out)
    assert (out / "skin-1.deltaskin").read_bytes() == skin
    assert json.loads((out / "submission.json").read_text())["author"] == "Pilot Creator"


@pytest.mark.parametrize("kwargs", [
    {"entry": "../escaped.deltaskin"},
    {"permission": False},
    {"compression": ZIP_DEFLATED},
])
def test_reject_before_writing(tmp_path, kwargs):
    bundle, out = tmp_path / "bundle.zip", tmp_path / "review"
    make_bundle(bundle, **kwargs)
    with pytest.raises(ValueError):
        review_bundle(bundle, out)
    assert not out.exists()
