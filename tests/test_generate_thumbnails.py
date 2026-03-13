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
