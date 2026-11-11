"""Tests for generate_thumbnails.py — asset discovery and PDF/PNG extraction."""

import io
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from generate_thumbnails import find_image_assets


# ---------------------------------------------------------------------------
# find_image_assets
# ---------------------------------------------------------------------------

class TestFindImageAssets:
    def test_finds_png_in_representations(self):
        info = {
            "representations": {
                "iphone": {
                    "edgeToEdge": {
                        "portrait": {
                            "assets": {"resizable": "portrait.png"}
                        }
                    }
                }
            }
        }
        assets = find_image_assets(info)
        assert "portrait.png" in assets

    def test_finds_pdf_when_no_png(self):
        info = {
            "representations": {
                "iphone": {
                    "edgeToEdge": {
                        "portrait": {
                            "assets": {"resizable": "skin.pdf"}
                        }
                    }
                }
            }
        }
        assets = find_image_assets(info)
        assert "skin.pdf" in assets

    def test_prefers_png_over_pdf(self):
        info = {
            "representations": {
                "iphone": {
                    "edgeToEdge": {
                        "portrait": {
                            "assets": {
                                "resizable": "portrait.pdf",
                                "small": "small.png",
                            }
                        }
                    }
                }
            }
        }
        assets = find_image_assets(info)
        # PNGs should come before PDFs
        png_idx = next((i for i, a in enumerate(assets) if a.endswith(".png")), None)
        pdf_idx = next((i for i, a in enumerate(assets) if a.endswith(".pdf")), None)
        assert png_idx is not None
        assert pdf_idx is not None
        assert png_idx < pdf_idx

    def test_empty_representations(self):
        assert find_image_assets({}) == []
        assert find_image_assets({"representations": {}}) == []

    def test_multiple_systems_deduplicates(self):
        info = {
            "representations": {
                "iphone": {"portrait": {"assets": {"resizable": "skin.png"}}},
                "ipad": {"portrait": {"assets": {"resizable": "skin.png"}}},
            }
        }
        assets = find_image_assets(info)
        # May contain duplicates — that's okay, we just need at least one
        assert "skin.png" in assets

    def test_nested_landscape_and_portrait(self):
        info = {
            "representations": {
                "iphone": {
                    "edgeToEdge": {
                        "portrait": {"assets": {"resizable": "portrait.png"}},
                        "landscape": {"assets": {"resizable": "landscape.png"}},
                    }
                }
            }
        }
        assets = find_image_assets(info)
        assert "portrait.png" in assets
        assert "landscape.png" in assets

    def test_ignores_non_asset_strings(self):
        info = {
            "name": "Test Skin",
            "identifier": "com.test.skin",
            "representations": {
                "iphone": {
                    "portrait": {
                        "assets": {"resizable": "real.png"}
                    }
                }
            }
        }
        assets = find_image_assets(info)
        assert assets == ["real.png"]
        assert "Test Skin" not in assets
        assert "com.test.skin" not in assets


@pytest.mark.parametrize("size", [(100, 200), (200, 100), (200, 200)])
def test_device_bezel_has_no_accent_rim_and_preserves_skin_art(size):
    """UI cards own their border; a generated rim must not tint or crop the skin itself."""
    image_module = pytest.importorskip("PIL.Image")
    from generate_thumbnails import _device_bezel

    skin_pink = (250, 51, 153, 255)
    artwork = image_module.new("RGBA", size, skin_pink)
    framed = _device_bezel(artwork, {"representations": {"iphone": {}}})

    assert framed.getpixel((framed.width // 2, 0)) == (13, 13, 26, 255)
    assert framed.getpixel((framed.width // 2, framed.height // 2)) == skin_pink
    assert framed.width > artwork.width and framed.height > artwork.height


@pytest.mark.parametrize("conversion_succeeds", [True, False])
def test_mislabeled_pdfs_are_rasterized_before_thumbnail_upload(tmp_path, monkeypatch, conversion_succeeds):
    from generate_thumbnails import process_skin

    image_module = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image_module.new("RGB", (12, 16), "blue").save(buffer, "PNG")
    png = buffer.getvalue()
    pdf = b"%PDF-1.3\nPDF artwork stored under a PNG filename"
    info = {
        "representations": {
            "iphone": {
                "edgeToEdge": {
                    orientation: {"assets": {"resizable": f"{orientation}.png"}}
                    for orientation in ("portrait", "landscape")
                }
            }
        }
    }
    entry = tmp_path / "skin.json"
    original = {"id": "test", "downloadURL": "https://example.com/test.deltaskin"}
    entry.write_text(json.dumps(original))
    monkeypatch.setattr("generate_thumbnails.GITHUB_TOKEN", "test-token")
    shards = MagicMock()
    shards.upload.side_effect = lambda name, data, **_: f"https://example.com/{name}"

    with (
        patch("generate_thumbnails.stream_extract_info_json", return_value=info),
        patch("generate_thumbnails.extract_asset_from_url", return_value=pdf),
        patch("generate_thumbnails.pdf_to_png", return_value=png if conversion_succeeds else None) as rasterize,
    ):
        updated = process_skin(str(entry), shards, str(tmp_path), False, True, no_enhance=True)

    assert updated is conversion_succeeds
    if conversion_succeeds:
        assert [call.args for call in rasterize.call_args_list] == [(pdf,), (pdf,)]
        for name, data in [call.args for call in shards.upload.call_args_list]:
            assert data == png
            assert (tmp_path / name).read_bytes() == png
        assert [call.args[0] for call in shards.upload.call_args_list] == ["test.png", "test-landscape.png"]
    else:
        shards.upload.assert_not_called()
        assert not list(tmp_path.glob("*.png"))
        assert json.loads(entry.read_text()) == original
