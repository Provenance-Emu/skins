"""Polite crawling of deltastyles.com (SkinKit#16). The HTTP layer is mocked; nothing here
touches the network."""

import email.message
import io
import json
import sys
import threading
import time
import urllib.error
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import polite_http as ph
import link_health as lh
import crawl_sources as cs
import extract_metadata as em
import generate_thumbnails as gt

DS = "https://deltastyles.com/files/skins/1/a.deltaskin"
DS2 = "https://deltastyles.com/files/skins/2/b.deltaskin"
DS3 = "https://deltastyles.com/files/skins/3/c.deltaskin"
GH = "https://raw.githubusercontent.com/o/r/HEAD/x.deltaskin"


def make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode())
    return buf.getvalue()


SKIN = make_zip({"info.json": json.dumps({"identifier": "x", "name": "X",
                                          "gameTypeIdentifier": "com.rileytestut.delta.game.gba",
                                          "representations": {}}), "p.png": b"png"})


def hdrs(**kw):
    m = email.message.Message()
    for k, v in kw.items():
        m[k.replace("_", "-")] = v
    return m


class Resp:
    def __init__(self, url, status=200, body=b"", **headers):
        self.status, self.headers, self._body, self._url = status, hdrs(**headers), io.BytesIO(body), url

    def read(self, n=-1):
        return self._body.read(n)

    def geturl(self):
        return self._url

    def close(self):
        pass


def http_error(url, code, **headers):
    return urllib.error.HTTPError(url, code, "x", hdrs(**headers), None)


class FakeOpener:
    """Serves queued responses per URL (the last one repeats) and records every request."""

    def __init__(self, routes=None, delay=0.0):
        self.routes = {u: list(v) if isinstance(v, list) else [v] for u, v in (routes or {}).items()}
        self.calls = []                 # (url, method, {lower-case header: value})
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.lock = threading.Lock()

    def __call__(self, req, timeout, follow_redirects=True):
        url = req.full_url
        with self.lock:
            self.calls.append((url, req.get_method(), {k.lower(): v for k, v in req.header_items()}))
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                time.sleep(self.delay)
            queue = self.routes.get(url)
            if queue is None:
                raise http_error(url, 404)
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(item, Exception):
                raise item
            return item(url) if callable(item) else item
        finally:
            with self.lock:
                self.in_flight -= 1

    def urls(self):
        return [c[0] for c in self.calls]


def ok(body=SKIN, **h):
    return lambda url: Resp(url, 200, body, **h)


class Clock:
    """Deterministic time: sleeping advances the clock."""

    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make_client(tmp_path, routes=None, clock=None, **kw):
    clock = clock or Clock()
    opener = FakeOpener(routes)
    kw.setdefault("min_interval", 0)
    client = ph.PoliteClient(cache_dir=tmp_path / "cache", opener=opener, sleep=clock.sleep,
                             clock=clock.now, now=clock.now, **kw)
    return client, opener, clock


# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------

class TestUserAgent:
    def test_names_the_project_and_has_a_contact_url(self):
        assert "Provenance-SkinCatalog" in ph.USER_AGENT
        assert "https://github.com/Provenance-Emu/skins" in ph.USER_AGENT

    def test_sent_on_every_request(self, tmp_path):
        client, opener, _ = make_client(tmp_path, {DS: ok(), GH: ok()})
        client.get_file(DS, component="link-health")
        client.get_file(GH)
        for url, _, h in opener.calls:
            assert "https://github.com/Provenance-Emu/skins" in h["user-agent"]
            assert "python-urllib" not in h["user-agent"].lower()
            assert "mozilla" not in h["user-agent"].lower()
        assert "(link-health)" in opener.calls[0][2]["user-agent"]

    def test_scripts_use_it(self):
        for mod_ua in (lh._UA, cs._UA, em._UA):
            assert "https://github.com/Provenance-Emu/skins" in mod_ua

    def test_thumbnail_mirror_sends_no_browser_agent_or_referer(self, tmp_path, monkeypatch):
        url = "https://deltastyles.com/images/skins/thumbnails/thumb_1.png"
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
        client, opener, _ = make_client(tmp_path, {url: ok(png)})
        monkeypatch.setattr(ph, "_client", client)
        assert gt.fetch_deltastyles_thumbnail(url) == png
        h = opener.calls[0][2]
        assert "https://github.com/Provenance-Emu/skins" in h["user-agent"]
        assert "referer" not in h and "mozilla" not in h["user-agent"].lower()


# ---------------------------------------------------------------------------
# One download per URL per run
# ---------------------------------------------------------------------------

class TestDownloadOnce:
    def test_second_call_reuses_the_file(self, tmp_path):
        client, opener, _ = make_client(tmp_path, {DS: ok()})
        a = client.get_file(DS)
        b = client.get_file(DS)
        assert a.path == b.path and a.path.read_bytes() == SKIN
        assert opener.urls() == [DS]

    def test_equivalent_spellings_share_one_download(self, tmp_path):
        spaced = "https://deltastyles.com/files/skins/1/My Skin.deltaskin"
        encoded = "https://deltastyles.com/files/skins/1/My%20Skin.deltaskin"
        client, opener, _ = make_client(tmp_path, {encoded: ok()})
        client.get_file(spaced)
        client.get_file(encoded)
        assert len(opener.calls) == 1

    def test_concurrent_callers_download_once(self, tmp_path):
        client, opener, _ = make_client(tmp_path, {DS: ok()})
        opener.delay = 0.05
        threads = [threading.Thread(target=client.get_file, args=(DS,)) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len(opener.calls) == 1

    def test_health_check_then_info_json_then_thumbnail_asset_is_one_download(self, tmp_path, monkeypatch):
        """link_health's check, the info.json read and the thumbnail's asset
        extraction all see the same single GET."""
        zip_bytes = make_zip({"info.json": json.dumps({"identifier": "x", "name": "X",
                              "gameTypeIdentifier": "g", "representations": {}}), "p.png": b"PNGDATA"})
        client, opener, _ = make_client(tmp_path, {DS: ok(zip_bytes)})
        monkeypatch.setattr(ph, "_client", client)
        assert lh.check_url(DS)["result"] == "ok"
        assert em.stream_extract_info_json(DS)["name"] == "X"
        assert gt.extract_asset_from_url(DS, "p.png") == b"PNGDATA"
        assert gt.extract_asset_from_url(DS, "p.png") == b"PNGDATA"
        assert opener.urls() == [DS]
        assert all(m == "GET" for _, m, _ in opener.calls)       # no HEAD, no range probing
        assert "range" not in opener.calls[0][2]

    def test_non_polite_host_still_uses_the_cache_for_get_file(self, tmp_path):
        client, opener, _ = make_client(tmp_path, {GH: ok()})
        client.get_file(GH)
        client.get_file(GH)
        assert len(opener.calls) == 1


# ---------------------------------------------------------------------------
# Concurrency cap and pacing
# ---------------------------------------------------------------------------

class TestConcurrency:
    def run_many(self, client, urls):
        threads = [threading.Thread(target=client.get_file, args=(u,)) for u in urls]
        [t.start() for t in threads]
        [t.join() for t in threads]

    def test_never_more_than_two_deltastyles_requests_at_once(self, tmp_path):
        urls = [f"https://deltastyles.com/files/skins/{i}/s.deltaskin" for i in range(12)]
        client, opener, _ = make_client(tmp_path, {u: ok() for u in urls}, concurrency=10)
        assert client.concurrency == 2          # asked for 10, clamped
        opener.delay = 0.02
        self.run_many(client, urls)
        assert len(opener.calls) == 12
        assert opener.max_in_flight <= 2

    def test_concurrency_one(self, tmp_path):
        urls = [f"https://deltastyles.com/files/skins/{i}/s.deltaskin" for i in range(6)]
        client, opener, _ = make_client(tmp_path, {u: ok() for u in urls}, concurrency=1)
        opener.delay = 0.02
        self.run_many(client, urls)
        assert opener.max_in_flight == 1

    def test_other_hosts_are_not_capped(self, tmp_path):
        urls = [f"https://raw.githubusercontent.com/o/r/HEAD/{i}.deltaskin" for i in range(8)]
        client, opener, _ = make_client(tmp_path, {u: ok() for u in urls})
        opener.delay = 0.05
        self.run_many(client, urls)
        assert opener.max_in_flight > 2

    def test_link_health_pool_for_deltastyles_is_capped(self, tmp_path, monkeypatch):
        skins = [{"id": f"{i:016x}", "downloadURL": f"https://deltastyles.com/files/skins/{i}/s.deltaskin"}
                 for i in range(10)]
        client, opener, _ = make_client(tmp_path, {s["downloadURL"]: ok() for s in skins})
        opener.delay = 0.02
        monkeypatch.setattr(ph, "_client", client)
        results = lh.check_all(skins, workers=8, client=client)
        assert {r["result"] for r in results.values()} == {"ok"}
        assert opener.max_in_flight <= 2

    def test_requests_to_one_host_are_spaced(self, tmp_path):
        urls = [f"https://deltastyles.com/files/skins/{i}/s.deltaskin" for i in range(4)]
        client, opener, clock = make_client(tmp_path, {u: ok() for u in urls}, min_interval=1.0)
        starts = []
        real = opener.__call__
        opener2 = lambda req, timeout, follow_redirects=True: (starts.append(clock.now()), real(req, timeout, follow_redirects))[1]
        client._opener = opener2
        for u in urls:
            client.get_file(u)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        assert all(g >= 1.0 - 1e-9 for g in gaps)


# ---------------------------------------------------------------------------
# Blocks: back off, then stop. Never evade.
# ---------------------------------------------------------------------------

class TestBlocks:
    def test_429_honours_retry_after_then_succeeds(self, tmp_path):
        client, opener, clock = make_client(tmp_path, {DS: [http_error(DS, 429, Retry_After="7"), ok()]})
        f = client.get_file(DS)
        assert f.path.read_bytes() == SKIN
        assert 7.0 in clock.slept
        assert not client.is_blocked(DS)

    def test_429_without_retry_after_backs_off_exponentially(self, tmp_path):
        client, opener, clock = make_client(
            tmp_path, {DS: [http_error(DS, 429), http_error(DS, 429), ok()]}, backoff_base=5.0)
        client.get_file(DS)
        assert clock.slept == [5.0, 20.0]

    def test_persistent_429_blocks_the_host_and_stops_asking(self, tmp_path):
        client, opener, clock = make_client(tmp_path, {DS: http_error(DS, 429), DS2: ok()}, max_retries=2)
        with pytest.raises(ph.HostBlocked) as e:
            client.get_file(DS)
        assert e.value.status == 429 and e.value.host == "deltastyles.com"
        sent = len(opener.calls)
        assert sent == 3                                   # first try + 2 retries
        with pytest.raises(ph.HostBlocked):
            client.get_file(DS2)                           # a different URL on the same host
        with pytest.raises(ph.HostBlocked):
            client.request(DS3)
        assert len(opener.calls) == sent                   # nothing more went out
        assert client.is_blocked(DS3)

    def test_403_blocks_immediately_without_retrying(self, tmp_path):
        client, opener, clock = make_client(tmp_path, {DS: http_error(DS, 403), DS2: ok()})
        with pytest.raises(ph.HostBlocked) as e:
            client.get_file(DS)
        assert e.value.status == 403
        assert len(opener.calls) == 1 and clock.slept == []
        with pytest.raises(ph.HostBlocked):
            client.get_file(DS2)
        assert len(opener.calls) == 1

    def test_long_retry_after_is_not_waited_out(self, tmp_path):
        client, opener, clock = make_client(tmp_path, {DS: http_error(DS, 429, Retry_After="3600")},
                                            max_retry_wait=120)
        with pytest.raises(ph.HostBlocked):
            client.get_file(DS)
        assert clock.slept == [] and len(opener.calls) == 1

    def test_block_does_not_affect_other_hosts(self, tmp_path):
        client, opener, _ = make_client(tmp_path, {DS: http_error(DS, 403), GH: ok()})
        with pytest.raises(ph.HostBlocked):
            client.get_file(DS)
        assert client.get_file(GH).path.read_bytes() == SKIN

    def test_repeated_server_errors_stop_the_host(self, tmp_path):
        urls = [f"https://deltastyles.com/files/skins/{i}/s.deltaskin" for i in range(8)]
        client, opener, _ = make_client(tmp_path, {u: http_error(u, 503) for u in urls},
                                        max_consecutive_errors=3)
        raised = []
        for u in urls:
            try:
                client.get_file(u)
            except ph.HostBlocked:
                raised.append("blocked")
            except urllib.error.HTTPError:
                raised.append("http")
        assert raised[:3] == ["http", "http", "blocked"]
        assert len(opener.calls) == 3

    def test_404_is_not_a_block(self, tmp_path):
        client, opener, _ = make_client(tmp_path, {DS: http_error(DS, 404), DS2: ok()})
        with pytest.raises(urllib.error.HTTPError) as e:
            client.get_file(DS)
        assert e.value.code == 404
        assert client.get_file(DS2)

    def test_nothing_is_rotated(self, tmp_path):
        """Same User-Agent and no extra identity headers on the retry after a 429."""
        client, opener, _ = make_client(tmp_path, {DS: [http_error(DS, 429, Retry_After="1"), ok()]})
        client.get_file(DS)
        first, second = opener.calls[0][2], opener.calls[1][2]
        assert first == second

    def test_link_health_skips_blocked_skins_and_keeps_their_records(self, tmp_path, monkeypatch, capsys):
        skins = tmp_path / "skins" / "gba"
        skins.mkdir(parents=True)
        entries = []
        for i in (1, 2, 3):
            e = {"id": f"{i:016x}", "name": f"S{i}", "systems": ["gba"],
                 "downloadURL": f"https://deltastyles.com/files/skins/{i}/s.deltaskin", "source": "deltastyles.com"}
            (skins / f"s{i}.json").write_text(json.dumps(e))
            entries.append(e)
        # 1 is fine, 2 is where the host says no, 3 never gets asked about
        client, opener, _ = make_client(tmp_path, {
            entries[0]["downloadURL"]: ok(),
            entries[1]["downloadURL"]: http_error(entries[1]["downloadURL"], 403),
            entries[2]["downloadURL"]: ok()}, concurrency=1)
        monkeypatch.setattr(ph, "_client", client)
        monkeypatch.setattr(lh.random, "shuffle", lambda x: None)    # keep skin order for this test
        health = tmp_path / "health.json"
        old = {"lastRun": "2026-10-01", "partialArtwork": {},
               "skins": {entries[2]["id"]: {"url": entries[2]["downloadURL"], "result": "http_404",
                                            "failures": 1, "firstFailedAt": "2026-10-01",
                                            "lastCheckedAt": "2026-10-01"}}}
        health.write_text(json.dumps(old))
        # Other output files (variants.json since #31) default to a path relative to the
        # working directory; keep them out of the repo checkout this test runs from.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["link_health.py", "--skins-dir", str(tmp_path / "skins"),
                                          "--health-file", str(health)])
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        with pytest.raises(SystemExit) as exit_:
            lh.main()
        assert exit_.value.code == 0
        assert len(opener.calls) == 2                        # skin 3 was never requested
        written = json.loads(health.read_text())
        assert written["skins"] == old["skins"]              # blocked skins aren't marked failed or dropped
        assert "blocked_hosts=deltastyles.com" in out.read_text()
        assert "first at https://deltastyles.com/files/skins/2/s.deltaskin" in capsys.readouterr().out

    def test_check_url_reports_host_blocked(self, tmp_path, monkeypatch):
        client, opener, _ = make_client(tmp_path, {DS: http_error(DS, 429)}, max_retries=0)
        monkeypatch.setattr(ph, "_client", client)
        r = lh.check_url(DS)
        assert r["result"] == lh.HOST_BLOCKED and r["host"] == "deltastyles.com"
        assert lh.HOST_BLOCKED not in lh.PERMANENT


# ---------------------------------------------------------------------------
# Conditional requests and reuse
# ---------------------------------------------------------------------------

class TestConditional:
    def test_validators_are_sent_next_run_and_304_reuses_the_file(self, tmp_path):
        client1, op1, clock = make_client(tmp_path, {DS: ok(ETag='"abc"', Last_Modified="Wed, 01 Oct 2026 00:00:00 GMT")})
        first = client1.get_file(DS)
        assert "if-none-match" not in op1.calls[0][2]

        clock.t += 7 * 24 * 3600                      # a week later, new process, same cache dir
        client2, op2, _ = make_client(tmp_path, {DS: http_error(DS, 304)}, clock=clock)
        second = client2.get_file(DS)
        h = op2.calls[0][2]
        assert h["if-none-match"] == '"abc"'
        assert h["if-modified-since"] == "Wed, 01 Oct 2026 00:00:00 GMT"
        assert second.from_cache and second.status == 304
        assert second.path.read_bytes() == SKIN == first.path.read_bytes()

    def test_changed_file_is_replaced(self, tmp_path):
        client1, _, clock = make_client(tmp_path, {DS: ok(ETag='"v1"')})
        client1.get_file(DS)
        clock.t += 7 * 24 * 3600
        new = make_zip({"info.json": "{}"})
        client2, op2, _ = make_client(tmp_path, {DS: ok(new, ETag='"v2"')}, clock=clock)
        f = client2.get_file(DS)
        assert not f.from_cache and f.path.read_bytes() == new
        assert op2.calls[0][2]["if-none-match"] == '"v1"'

    def test_no_validators_means_plain_request(self, tmp_path):
        client1, _, clock = make_client(tmp_path, {DS: ok()})
        client1.get_file(DS)
        clock.t += 7 * 24 * 3600
        client2, op2, _ = make_client(tmp_path, {DS: ok()}, clock=clock)
        client2.get_file(DS)
        assert "if-none-match" not in op2.calls[0][2] and "if-modified-since" not in op2.calls[0][2]

    def test_fresh_copy_needs_no_request(self, tmp_path):
        client1, _, clock = make_client(tmp_path, {DS: ok(ETag='"a"')})
        client1.get_file(DS)
        client2, op2, _ = make_client(tmp_path, {}, clock=clock)    # an hour later, nothing routed
        clock.t += 3600
        f = client2.get_file(DS)
        assert f.from_cache and op2.calls == []

    def test_thumbnail_job_reuses_the_exported_copy_without_a_request(self, tmp_path, monkeypatch):
        """link-health exports the archives of skins missing thumbnails; the other
        job points its cache at that directory and never asks deltastyles again."""
        health_client, _, clock = make_client(tmp_path / "a", {DS: ok(ETag='"a"')})
        health_client.get_file(DS)
        export = tmp_path / "export"
        assert health_client.export([DS, DS2], export) == 1          # DS2 was never downloaded

        thumb_client = ph.PoliteClient(cache_dir=export, opener=FakeOpener({}), sleep=clock.sleep,
                                       clock=clock.now, now=clock.now)
        monkeypatch.setattr(ph, "_client", thumb_client)
        assert gt.extract_asset_from_url(DS, "p.png") == b"png"
        assert thumb_client._opener.calls == []

    def test_prune_drops_oldest_first(self, tmp_path):
        urls = [f"https://deltastyles.com/files/skins/{i}/s.deltaskin" for i in range(3)]
        client, _, clock = make_client(tmp_path, {u: ok(b"x" * 1000) for u in urls})
        import os
        for i, u in enumerate(urls):
            client.get_file(u)
            _, meta = client._paths(u)
            os.utime(meta, (1000 + i, 1000 + i))
        assert client.prune(2000) == 1
        assert not client._paths(urls[0])[0].exists()
        assert client._paths(urls[2])[0].exists()


# ---------------------------------------------------------------------------
# crawl_sources: stop scraping when blocked
# ---------------------------------------------------------------------------

class TestCrawl:
    def test_scrape_stops_after_a_block_and_keeps_earlier_results(self, tmp_path, monkeypatch):
        listing = "https://deltastyles.com/systems/gba"
        detail = "https://deltastyles.com/skins/1-a"
        client, opener, _ = make_client(tmp_path, {
            "https://deltastyles.com/systems/arcade": ok(b"<html>listing</html>"),
            detail: http_error(detail, 403),
            listing: ok(b"<html></html>")})
        monkeypatch.setattr(ph, "_client", client)
        monkeypatch.setattr(cs.time, "sleep", lambda *_: None)
        monkeypatch.setattr(cs.random, "shuffle", lambda x: None)
        monkeypatch.setattr(cs, "_deltastyles_parse_listing",
                            lambda html: [{"_detail_path": "/skins/1-a", "name": "A"}])
        entries = cs.scrape_deltastyles(["arcade", "gba", "nes"], set(), scrape_all=True)
        assert entries == []
        assert opener.urls() == ["https://deltastyles.com/systems/arcade", detail]   # then it stopped
        assert client.is_blocked("deltastyles.com")

    def test_landing_redirect_is_read_without_following_it(self, tmp_path, monkeypatch):
        detail = "https://deltastyles.com/skins/5-x"
        landing = "https://deltastyles.com/download-files.php?id=9"
        target = "https://deltastyles.com/files/skins/5/x.deltaskin"
        client, opener, _ = make_client(tmp_path, {
            detail: ok(b'<a href="/download.php?id=9">dl</a>'),
            landing: http_error(landing, 302, Location=target)})
        monkeypatch.setattr(ph, "_client", client)
        assert cs._deltastyles_resolve_variants("/skins/5-x") == [{"downloadURL": target, "label": "x"}]
        assert opener.urls() == [detail, landing]

    def test_info_json_of_a_new_skin_is_one_full_get(self, tmp_path, monkeypatch):
        client, opener, _ = make_client(tmp_path, {DS: ok()})
        monkeypatch.setattr(ph, "_client", client)
        code, gti = cs._deltastyles_system_from_info(DS)
        assert gti == "com.rileytestut.delta.game.gba"
        assert [m for _, m, _ in opener.calls] == ["GET"]

    def test_blocked_host_propagates_from_info_read(self, tmp_path, monkeypatch):
        client, opener, _ = make_client(tmp_path, {DS: http_error(DS, 403)})
        monkeypatch.setattr(ph, "_client", client)
        with pytest.raises(ph.HostBlocked):
            cs._deltastyles_system_from_info(DS)


# ---------------------------------------------------------------------------
# generate_thumbnails
# ---------------------------------------------------------------------------

class TestThumbnails:
    def test_skin_on_a_blocked_host_is_skipped_without_a_request(self, tmp_path, monkeypatch, capsys):
        client, opener, _ = make_client(tmp_path, {DS: http_error(DS, 403)})
        monkeypatch.setattr(ph, "_client", client)
        with pytest.raises(ph.HostBlocked):
            client.get_file(DS)
        entry = tmp_path / "s.json"
        entry.write_text(json.dumps({"id": "a" * 16, "name": "S", "downloadURL": DS2, "thumbnailURL": None}))
        assert gt.process_skin(str(entry), None, str(tmp_path / "t"), False, False) is False
        assert "refused us" in capsys.readouterr().out
        assert len(opener.calls) == 1

    def test_deltastyles_file_is_no_longer_skipped_outright(self, tmp_path, monkeypatch, capsys):
        """It used to be skipped as 'blocked (403)'; now it goes through the cache."""
        client, opener, _ = make_client(tmp_path, {DS: ok()})
        monkeypatch.setattr(ph, "_client", client)
        monkeypatch.setattr(gt, "stream_extract_info_json", lambda *a, **k: None)
        entry = tmp_path / "s.json"
        entry.write_text(json.dumps({"id": "a" * 16, "name": "S", "downloadURL": DS, "thumbnailURL": None}))
        gt.process_skin(str(entry), None, str(tmp_path / "t"), True, False)
        out = capsys.readouterr().out
        assert "Processing: S" in out and "Could not extract info.json" in out   # got past the old early return
        assert "blocked" not in out


# ---------------------------------------------------------------------------
# Rotation and cache-only mode
# ---------------------------------------------------------------------------

class TestRotationAndCacheOnly:
    def test_polite_host_order_is_shuffled(self, tmp_path, monkeypatch):
        skins = [{"id": f"{i:016x}", "downloadURL": f"https://deltastyles.com/files/skins/{i}/s.deltaskin"}
                 for i in range(6)]
        client, opener, _ = make_client(tmp_path, {s["downloadURL"]: ok() for s in skins}, concurrency=1)
        seen = []
        monkeypatch.setattr(lh.random, "shuffle", lambda x: (x.reverse(), seen.append(True)))
        monkeypatch.setattr(ph, "_client", client)
        lh.check_all(skins, client=client)
        assert seen and opener.urls() == [s["downloadURL"] for s in reversed(skins)]

    def test_cache_only_never_fetches_polite_hosts(self, tmp_path):
        client, opener, _ = make_client(tmp_path, {DS: ok(), GH: ok()}, cache_only=True)
        with pytest.raises(ph.CacheMiss):
            client.get_file(DS)
        assert opener.calls == []
        assert client.unavailable(DS) and not client.unavailable(GH)
        client.get_file(GH)                                    # other hosts are unaffected
        assert len(opener.calls) == 1

    def test_cache_only_serves_a_cached_copy_without_revalidating(self, tmp_path):
        warm, _, clock = make_client(tmp_path, {DS: ok()})
        warm.get_file(DS)
        clock.t += 30 * 24 * 3600                              # long past the freshness window
        cold, opener, _ = make_client(tmp_path, {}, clock=clock, cache_only=True)
        assert not cold.unavailable(DS)
        assert cold.get_file(DS).path.read_bytes() == SKIN
        assert opener.calls == []

    def test_thumbnail_run_without_handoff_skips_deltastyles_archives(self, tmp_path, monkeypatch, capsys):
        client, opener, _ = make_client(tmp_path, {DS: ok()}, cache_only=True)
        monkeypatch.setattr(ph, "_client", client)
        entry = tmp_path / "s.json"
        entry.write_text(json.dumps({"id": "a" * 16, "name": "S", "downloadURL": DS, "thumbnailURL": None}))
        assert gt.process_skin(str(entry), None, str(tmp_path / "t"), False, False) is False
        assert "retry next run" in capsys.readouterr().out
        assert opener.calls == []

    def test_env_flag(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ph, "_client", None)
        monkeypatch.setenv("SKIN_CACHE_DIR", str(tmp_path / "c"))
        monkeypatch.setenv("POLITE_CACHE_ONLY", "1")
        assert ph.get_client().cache_only
        monkeypatch.setattr(ph, "_client", None)
        monkeypatch.setenv("POLITE_CACHE_ONLY", "0")
        assert not ph.get_client().cache_only
        monkeypatch.setattr(ph, "_client", None)
