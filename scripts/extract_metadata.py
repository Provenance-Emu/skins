#!/usr/bin/env python3
"""
extract_metadata.py — Stream-extract info.json from a .deltaskin / .manicskin URL
without downloading the full archive. Makes at most 4 HTTP range requests.

Falls back to full download if the server doesn't support range requests.
"""

import io
import json
import struct
import sys
import urllib.request
import urllib.error
import zlib
from typing import Optional

EOCD_SIG = b"PK\x05\x06"
EOCD64_SIG = b"PK\x06\x06"
CD_SIG = b"PK\x01\x02"
LH_SIG = b"PK\x03\x04"


def _http_get(url: str, headers: dict = None, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _range_get(url: str, start: int, length: int, token: str = "") -> bytes:
    headers = {"Range": f"bytes={start}-{start + length - 1}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _http_get(url, headers)


def _get_file_size(url: str, token: str = "") -> Optional[int]:
    headers = {"User-Agent": "Provenance-SkinCatalog/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method="HEAD", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            cl = r.headers.get("Content-Length")
            ar = r.headers.get("Accept-Ranges", "")
            if cl and ar.lower() != "none":
                return int(cl)
    except Exception:
        pass
    return None


def _find_eocd(data: bytes) -> int:
    """Scan backwards for End of Central Directory signature."""
    for i in range(len(data) - 22, max(len(data) - 65536 - 22, -1), -1):
        if data[i : i + 4] == EOCD_SIG:
            return i
    raise ValueError("EOCD signature not found — not a valid ZIP")


def stream_extract_info_json(url: str, token: str = "") -> Optional[dict]:
    """
    Extract info.json from a ZIP-based skin file using range requests.
    Returns the parsed dict, or None if info.json isn't found.
    """
    file_size = _get_file_size(url, token)

    if file_size is None:
        # Server doesn't support range requests — full download
        return _full_download_extract(url, token)

    # Fetch tail (EOCD + central directory usually fits in 64KB)
    tail_size = min(65536, file_size)
    tail_start = file_size - tail_size
    tail = _range_get(url, tail_start, tail_size, token)

    # Find EOCD
    eocd_pos = _find_eocd(tail)
    eocd = tail[eocd_pos : eocd_pos + 22]
    (_, disk_num, cd_disk, disk_entries, total_entries,
     cd_size, cd_offset, comment_len) = struct.unpack("<4sHHHHIIH", eocd)

    # ZIP64 check
    if cd_offset == 0xFFFFFFFF or total_entries == 0xFFFF:
        return _full_download_extract(url, token)  # punt on ZIP64

    # Fetch central directory (may already be buffered in tail)
    abs_cd_start = cd_offset
    tail_buffer_start = tail_start
    if abs_cd_start >= tail_buffer_start:
        cd_in_tail = abs_cd_start - tail_buffer_start
        cd_data = tail[cd_in_tail : cd_in_tail + cd_size]
    else:
        cd_data = _range_get(url, abs_cd_start, cd_size, token)

    # Scan central directory for info.json
    entry = _find_cd_entry(cd_data, "info.json")
    if not entry:
        return None

    # Fetch local file header to get data offset
    lh_raw = _range_get(url, entry["lh_offset"], 30, token)
    if lh_raw[:4] != LH_SIG:
        return None
    (_, _, _, comp, _, _, _, _, _, fname_len, extra_len) = struct.unpack("<4sHHHHHIIIHH", lh_raw)
    data_offset = entry["lh_offset"] + 30 + fname_len + extra_len

    comp_data = _range_get(url, data_offset, entry["comp_size"], token)
    return _decompress_entry(comp_data, comp, entry["uncomp_size"])


def _find_cd_entry(cd_data: bytes, target: str) -> Optional[dict]:
    pos = 0
    while pos < len(cd_data) - 4:
        if cd_data[pos : pos + 4] != CD_SIG:
            break
        if len(cd_data) < pos + 46:
            break
        header = cd_data[pos : pos + 46]
        (_, _, _, _, comp, _, _, _, comp_size, uncomp_size,
         fname_len, extra_len, comment_len, _, _, _,
         lh_offset) = struct.unpack("<4sHHHHHHIIIHHHHHII", header)
        fname = cd_data[pos + 46 : pos + 46 + fname_len].decode("utf-8", errors="replace")
        if fname.lower().lstrip("./") == target.lower():
            return {
                "compression": comp,
                "comp_size": comp_size,
                "uncomp_size": uncomp_size,
                "lh_offset": lh_offset,
            }
        pos += 46 + fname_len + extra_len + comment_len
    return None


def _decompress_entry(data: bytes, method: int, expected_size: int) -> Optional[dict]:
    try:
        if method == 0:
            raw = data
        elif method == 8:
            raw = zlib.decompress(data, -15)
        else:
            return None
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _full_download_extract(url: str, token: str = "") -> Optional[dict]:
    """Fallback: download full file and extract info.json using zipfile module."""
    import zipfile

    headers = {"User-Agent": "Provenance-SkinCatalog/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = _http_get(url, headers)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            for name in names:
                if name.lower().lstrip("./") == "info.json":
                    return json.loads(zf.read(name).decode("utf-8"))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: extract_metadata.py <url> [--token TOKEN]", file=sys.stderr)
        sys.exit(1)
    url = sys.argv[1]
    token = ""
    if "--token" in sys.argv:
        token = sys.argv[sys.argv.index("--token") + 1]
    result = stream_extract_info_json(url, token)
    if result:
        print(json.dumps(result, indent=2))
    else:
        print("info.json not found in skin archive", file=sys.stderr)
        sys.exit(1)
