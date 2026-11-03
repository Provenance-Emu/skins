"""Tests for validate_skin.py — self-hosted URLs are checked against the tree."""

import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import validate_skin
from validate_skin import check_url_reachable, self_hosted_path

RAW = "https://raw.githubusercontent.com/Provenance-Emu/skins/main/"


class TestSelfHostedPath:
    def test_maps_to_working_tree(self, tmp_path):
        assert self_hosted_path(RAW + "fixtures/a/b.deltaskin", tmp_path) == \
            (tmp_path / "fixtures/a/b.deltaskin").resolve()

    def test_owner_and_repo_case_insensitive(self, tmp_path):
        url = "https://raw.githubusercontent.com/provenance-emu/Skins/main/x.deltaskin"
        assert self_hosted_path(url, tmp_path) is not None

    def test_percent_encoding_decoded(self, tmp_path):
        got = self_hosted_path(RAW + "fixtures/a%20b.deltaskin", tmp_path)
        assert got == (tmp_path / "fixtures/a b.deltaskin").resolve()

    def test_other_repo_not_self_hosted(self, tmp_path):
        url = "https://raw.githubusercontent.com/Someone/else/main/x.deltaskin"
        assert self_hosted_path(url, tmp_path) is None

    def test_other_branch_not_self_hosted(self, tmp_path):
        url = "https://raw.githubusercontent.com/Provenance-Emu/skins/dev/x.deltaskin"
        assert self_hosted_path(url, tmp_path) is None

    def test_other_host_not_self_hosted(self, tmp_path):
        assert self_hosted_path("https://deltastyles.com/files/x.deltaskin", tmp_path) is None

    def test_traversal_never_exists(self, tmp_path):
        (tmp_path.parent / "secret.deltaskin").write_bytes(b"x")
        got = self_hosted_path(RAW + "../secret.deltaskin", tmp_path)
        assert got is not None and not got.exists()
        got = self_hosted_path(RAW + "%2e%2e/secret.deltaskin", tmp_path)
        assert got is not None and not got.exists()


class TestCheckUrlReachable:
    def test_existing_tree_file_is_reachable_without_network(self, tmp_path):
        f = tmp_path / "fixtures" / "ok.deltaskin"
        f.parent.mkdir()
        f.write_bytes(b"x")
        with mock.patch.object(validate_skin, "REPO_ROOT", tmp_path), \
                mock.patch.object(validate_skin.urllib.request, "urlopen",
                                  side_effect=AssertionError("network used")):
            assert check_url_reachable(RAW + "fixtures/ok.deltaskin") is True
            assert check_url_reachable(RAW + "fixtures/missing.deltaskin") is False

    def test_other_urls_still_hit_the_network(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value.status = 200
        with mock.patch.object(validate_skin.urllib.request, "urlopen",
                               return_value=resp) as opened:
            assert check_url_reachable("https://deltastyles.com/x.deltaskin") is True
        opened.assert_called_once()
