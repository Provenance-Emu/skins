#!/usr/bin/env python3
"""
polite_http.py — one HTTP layer for everything that talks to deltastyles.com (SkinKit#16).

deltastyles.com rate-limits, and has 403'd our CI before. For its hosts this
client:

  - sends at most 1-2 requests at a time (`MAX_POLITE_CONCURRENCY`), and starts
    them at least `min_interval` seconds apart;
  - downloads each URL once per run into a cache directory keyed by the sha256
    of the URL, and hands every later caller (health check, thumbnails, repack)
    that same file;
  - sends `If-None-Match` / `If-Modified-Since` when an earlier run left an
    `ETag` / `Last-Modified` next to the cached copy, and reuses the copy on 304;
  - identifies itself with `USER_AGENT`, which carries the repo URL as the
    contact;
  - never evades a block. On 429 (or 503 with `Retry-After`) it waits as the
    server says, up to `max_retries` times, and gives up if the wait is longer
    than `max_retry_wait`. On 403, or when the retries run out, it marks the host
    blocked for the rest of the process and raises `HostBlocked` for every
    later request without touching the network. It does not rotate agents,
    proxies or headers.

Hosts that aren't polite hosts (GitHub, Drive) are not throttled or blocked by
this client, and any HTTP error is raised as the original `urllib.error.HTTPError`.
They still get the shared User-Agent and, through `get_file`, the shared cache.

Environment (read once by `get_client()`):
    SKIN_CACHE_DIR            cache directory (default: a temp dir removed at exit)
    POLITE_CONCURRENCY        1 or 2 (default 2; higher values are clamped to 2)
    POLITE_MIN_INTERVAL       seconds between request starts per polite host (default 1.0)
    POLITE_CACHE_ONLY         "1": polite hosts are served from the cache only, never fetched
                              (a push-triggered thumbnail run that wasn't handed link-health's files)
"""

import atexit
import email.utils
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

CONTACT_URL = "https://github.com/Provenance-Emu/skins"
USER_AGENT = f"Provenance-SkinCatalog/1.0 (+{CONTACT_URL})"

POLITE_HOST_SUFFIXES = ("deltastyles.com",)
MAX_POLITE_CONCURRENCY = 2
DEFAULT_MIN_INTERVAL = 1.0
# A cached copy fetched this recently is reused without asking the server at all.
# It is what lets the thumbnail job use the health check's files without a request each.
DEFAULT_FRESH_SECONDS = 12 * 3600
MAX_BODY_BYTES = 150 * 1024 * 1024
GITHUB_HOSTS = ("github.com", "raw.githubusercontent.com", "objects.githubusercontent.com",
                "api.github.com", "media.githubusercontent.com")


def user_agent(component: str | None = None) -> str:
    """The shared User-Agent, optionally tagged with the calling script."""
    return USER_AGENT if not component else f"{USER_AGENT} ({component})"


class CacheMiss(Exception):
    """cache-only mode: the file isn't in the download cache and this run may not fetch it."""

    def __init__(self, url: str):
        self.url = url
        super().__init__(f"{url} is not in the download cache (this run only reads the cache)")


class HostBlocked(Exception):
    """The host refused us (403/429 that persisted, or repeated errors). Stop asking it."""

    def __init__(self, host: str, status, url: str = "", reason: str = ""):
        self.host, self.status, self.url, self.reason = host, status, url, reason
        super().__init__(f"{host} blocked us (HTTP {status}) at {url or host}"
                         + (f": {reason}" if reason else "") + "; not retrying this run")


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    url: str


@dataclass
class Fetched:
    path: Path
    url: str
    final_url: str
    content_type: str
    size: int
    from_cache: bool            # True: no body was downloaded this call
    status: int = 200


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_opener(req, timeout, follow_redirects=True):
    if follow_redirects:
        return urllib.request.urlopen(req, timeout=timeout)
    return urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout)


def canonical_url(url: str) -> str:
    """Percent-encode the path the way the catalog stores download URLs, drop the
    fragment, so `My Skin.deltaskin` and `My%20Skin.deltaskin` share one cache entry."""
    p = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(urllib.parse.unquote(p.path), safe="/")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, p.query, ""))


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _lower(headers) -> dict:
    return {k.lower(): v for k, v in headers.items()} if headers is not None else {}


def _retry_after_seconds(value) -> float | None:
    if not value:
        return None
    value = str(value).strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, when.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


class PoliteClient:
    def __init__(self, cache_dir=None, concurrency: int = MAX_POLITE_CONCURRENCY,
                 min_interval: float = DEFAULT_MIN_INTERVAL, max_retries: int = 2,
                 max_retry_wait: float = 120.0, backoff_base: float = 5.0,
                 max_consecutive_errors: int = 5, fresh_seconds: float = DEFAULT_FRESH_SECONDS,
                 timeout: float = 60.0, polite_suffixes=POLITE_HOST_SUFFIXES, cache_only: bool = False,
                 opener=_default_opener, sleep=time.sleep, clock=time.monotonic, now=time.time):
        self.concurrency = max(1, min(int(concurrency), MAX_POLITE_CONCURRENCY))
        self.min_interval = float(min_interval)
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self.backoff_base = backoff_base
        self.max_consecutive_errors = max_consecutive_errors
        self.fresh_seconds = fresh_seconds
        self.timeout = timeout
        self.polite_suffixes = tuple(polite_suffixes)
        self.cache_only = cache_only
        self._opener, self._sleep, self._clock, self._now = opener, sleep, clock, now

        if cache_dir:
            self.cache_dir = Path(cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.cache_dir = Path(tempfile.mkdtemp(prefix="skin-cache-"))
            atexit.register(shutil.rmtree, self.cache_dir, ignore_errors=True)

        self._lock = threading.Lock()
        self._sems: dict[str, threading.BoundedSemaphore] = {}
        self._next_start: dict[str, float] = {}
        self._blocked: dict[str, HostBlocked] = {}
        self._errors: dict[str, int] = {}
        self._memo: dict[str, Fetched] = {}
        self._url_locks: dict[str, threading.Lock] = {}
        self.request_count = 0          # network requests actually sent
        self.requests_by_host: dict[str, int] = {}

    # -- host policy --------------------------------------------------------

    def is_polite(self, url: str) -> bool:
        host = _host(url)
        return any(host == s or host.endswith("." + s) for s in self.polite_suffixes)

    def is_blocked(self, url_or_host: str) -> bool:
        host = _host(url_or_host) if "//" in url_or_host else url_or_host.lower()
        return host in self._blocked

    def unavailable(self, url: str) -> bool:
        """True if a polite-host `url` can't be had this run: the host has refused
        us, or this client is cache-only and has no copy."""
        if not self.is_polite(url):
            return False
        if self.is_blocked(url):
            return True
        return self.cache_only and not all(p.exists() for p in self._paths(url))

    def blocked_hosts(self) -> dict[str, HostBlocked]:
        return dict(self._blocked)

    def _block(self, host: str, status, url: str, reason: str = "") -> HostBlocked:
        with self._lock:
            err = self._blocked.get(host) or HostBlocked(host, status, url, reason)
            self._blocked[host] = err
        return err

    def _sem(self, host: str) -> threading.BoundedSemaphore:
        with self._lock:
            return self._sems.setdefault(host, threading.BoundedSemaphore(self.concurrency))

    def _pace(self, host: str):
        """Space request starts at least `min_interval` apart for one host."""
        with self._lock:
            now = self._clock()
            start = max(now, self._next_start.get(host, 0.0))
            self._next_start[host] = start + self.min_interval
        if start > now:
            self._sleep(start - now)

    # -- low-level request --------------------------------------------------

    def request(self, url: str, *, headers: dict | None = None, follow_redirects: bool = True,
                token: str = "", method: str = "GET", max_bytes: int = MAX_BODY_BYTES,
                dest: Path | None = None, component: str | None = None) -> Response:
        """One request with this client's policy. Returns the response for 2xx and
        (when `follow_redirects` is False) 3xx; raises `HTTPError` for other
        statuses and `HostBlocked` when a polite host has refused us.

        With `dest`, the body is streamed there instead of held in memory and
        `Response.body` is empty.
        """
        host = _host(url)
        polite = self.is_polite(url)
        hdrs = {"User-Agent": user_agent(component), **(headers or {})}
        if token and host in GITHUB_HOSTS:
            hdrs["Authorization"] = f"Bearer {token}"

        if polite:
            if host in self._blocked:
                raise self._blocked[host]
            sem = self._sem(host)
            sem.acquire()
        try:
            attempt = 0
            while True:
                if polite:
                    if host in self._blocked:
                        raise self._blocked[host]
                    self._pace(host)
                req = urllib.request.Request(url, headers=hdrs, method=method)
                with self._lock:
                    self.request_count += 1
                    self.requests_by_host[host] = self.requests_by_host.get(host, 0) + 1
                try:
                    resp = self._opener(req, self.timeout, follow_redirects)
                    status, rheaders, final = resp.status, resp.headers, resp.geturl()
                    try:
                        body = self._read(resp, max_bytes, dest)
                    finally:
                        resp.close()
                    if polite:
                        self._errors[host] = 0
                    return Response(status, _lower(rheaders), body, final)
                except urllib.error.HTTPError as e:
                    code = e.code
                    if not follow_redirects and 300 <= code < 400:
                        return Response(code, _lower(e.headers), b"", url)
                    if code == 304:
                        return Response(304, _lower(e.headers), b"", url)
                    if not polite:
                        raise
                    wait = _retry_after_seconds(e.headers.get("Retry-After")) if e.headers else None
                    if code == 403:
                        raise self._block(host, 403, url, "forbidden")
                    if code == 429 or (code == 503 and wait is not None):
                        if attempt >= self.max_retries:
                            raise self._block(host, code, url, "still limited after retries")
                        pause = wait if wait is not None else self.backoff_base * (4 ** attempt)
                        if pause > self.max_retry_wait:
                            raise self._block(host, code, url, f"asked us to wait {pause:.0f}s")
                        print(f"  {host}: HTTP {code}, waiting {pause:.0f}s "
                              f"(retry {attempt + 1}/{self.max_retries})")
                        self._sleep(pause)
                        attempt += 1
                        continue
                    if code >= 500:
                        n = self._errors[host] = self._errors.get(host, 0) + 1
                        if n >= self.max_consecutive_errors:
                            raise self._block(host, code, url, f"{n} server errors in a row")
                    raise
        finally:
            if polite:
                sem.release()

    @staticmethod
    def _read(resp, max_bytes: int, dest: Path | None) -> bytes:
        if dest is None:
            return resp.read(max_bytes)
        total = 0
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise ValueError(f"response larger than {max_bytes} bytes")
                f.write(chunk)
        os.replace(tmp, dest)
        return b""

    # -- cached downloads ---------------------------------------------------

    def _paths(self, url: str) -> tuple[Path, Path]:
        sha = hashlib.sha256(canonical_url(url).encode()).hexdigest()
        d = self.cache_dir / sha[:2]
        return d / f"{sha}.bin", d / f"{sha}.json"

    def _url_lock(self, url: str) -> threading.Lock:
        with self._lock:
            return self._url_locks.setdefault(url, threading.Lock())

    def get_file(self, url: str, *, token: str = "", headers: dict | None = None,
                 max_bytes: int = MAX_BODY_BYTES, component: str | None = None) -> Fetched:
        """The body of `url` as a file in the cache. Downloaded at most once per
        run, and not at all when a copy newer than `fresh_seconds` is cached.
        Raises `HTTPError` (non-2xx) or `HostBlocked`."""
        url = canonical_url(url)
        with self._url_lock(url):
            hit = self._memo.get(url)
            if hit:
                return hit
            body, meta_path = self._paths(url)
            body.parent.mkdir(parents=True, exist_ok=True)
            meta = {}
            if body.exists() and meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except (OSError, json.JSONDecodeError):
                    meta = {}
            if meta and (self._now() - meta.get("fetchedAt", 0) < self.fresh_seconds
                         or (self.cache_only and self.is_polite(url))):
                return self._remember(url, self._fetched(url, body, meta, True))
            if self.cache_only and self.is_polite(url):
                raise CacheMiss(url)

            cond = dict(headers or {})
            if meta.get("etag"):
                cond["If-None-Match"] = meta["etag"]
            if meta.get("lastModified"):
                cond["If-Modified-Since"] = meta["lastModified"]
            resp = self.request(url, headers=cond, token=token, max_bytes=max_bytes,
                                dest=body, component=component)
            if resp.status == 304 and meta:
                meta["fetchedAt"] = self._now()
                meta_path.write_text(json.dumps(meta))
                return self._remember(url, self._fetched(url, body, meta, True, 304))
            h = {k.lower(): v for k, v in resp.headers.items()}
            meta = {"url": url, "finalURL": resp.url, "etag": h.get("etag"),
                    "lastModified": h.get("last-modified"), "contentType": h.get("content-type", ""),
                    "size": body.stat().st_size, "fetchedAt": self._now()}
            meta_path.write_text(json.dumps(meta))
            return self._remember(url, self._fetched(url, body, meta, False))

    def _fetched(self, url, body, meta, from_cache, status=200) -> Fetched:
        return Fetched(body, url, meta.get("finalURL") or url, meta.get("contentType", ""),
                       meta.get("size") or body.stat().st_size, from_cache, status)

    def _remember(self, url: str, fetched: Fetched) -> Fetched:
        self._memo[url] = fetched
        return fetched

    def get_bytes(self, url: str, **kw) -> bytes:
        """Like `get_file`, for pages and small files."""
        return self.get_file(url, **kw).path.read_bytes()

    # -- housekeeping -------------------------------------------------------

    def export(self, urls, dest) -> int:
        """Copy the cached files for `urls` into `dest` (same layout, so another
        run can use `dest` as its cache). Returns how many were copied."""
        dest = Path(dest)
        copied = 0
        for url in urls:
            body, meta = self._paths(url)
            if body.exists() and meta.exists():
                target = dest / body.parent.name
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(body, target / body.name)
                shutil.copy2(meta, target / meta.name)
                copied += 1
        return copied

    def prune(self, max_bytes: int) -> int:
        """Delete the least recently fetched cache entries until under `max_bytes`.
        Returns the number of entries removed."""
        entries = []
        for meta in self.cache_dir.glob("*/*.json"):
            body = meta.with_suffix(".bin")
            if body.exists():
                entries.append((meta.stat().st_mtime, body, meta, body.stat().st_size))
        total = sum(e[3] for e in entries)
        removed = 0
        for _, body, meta, size in sorted(entries, key=lambda e: e[0]):
            if total <= max_bytes:
                break
            body.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            total -= size
            removed += 1
        return removed

    def summary(self) -> str:
        lines = [f"{self.request_count} network request(s): "
                 + ", ".join(f"{h} {n}" for h, n in sorted(self.requests_by_host.items()))]
        for host, err in self._blocked.items():
            lines.append(f"{host} blocked us (HTTP {err.status}); stopped asking it for this run")
        return "; ".join(lines)


# ---------------------------------------------------------------------------
# Process-wide client
# ---------------------------------------------------------------------------

_client: PoliteClient | None = None
_client_lock = threading.Lock()


def get_client() -> PoliteClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = PoliteClient(
                cache_dir=os.environ.get("SKIN_CACHE_DIR") or None,
                concurrency=int(os.environ.get("POLITE_CONCURRENCY", MAX_POLITE_CONCURRENCY)),
                min_interval=float(os.environ.get("POLITE_MIN_INTERVAL", DEFAULT_MIN_INTERVAL)),
                cache_only=os.environ.get("POLITE_CACHE_ONLY", "") == "1",
            )
        return _client


def set_client(client: PoliteClient | None) -> None:
    """Install (or, with None, drop) the process-wide client. For CLIs and tests."""
    global _client
    with _client_lock:
        _client = client
