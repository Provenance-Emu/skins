"""Check that a format 2 archive carries the TypeScript baker's classic metadata."""

import base64
import json
from pathlib import Path
import subprocess
import zipfile

VERIFIER = Path(__file__).resolve().parents[1] / "tools" / "skin2" / "verify-bake.mjs"
SOURCE_LIMIT = 512 * 1024
INFO_LIMIT = 4 * 1024 * 1024


def verify_format2(archive: zipfile.ZipFile, info: dict) -> dict:
    """Return a verdict, keeping invalid archives separate from checker failures."""
    metadata = info.get("format2")
    if not isinstance(metadata, dict):
        return {"ok": False, "error": "format2 must be an object"}
    source = metadata.get("source", "skin.json")
    if source != "skin.json":
        return {"ok": False, "error": "The canonical bake must use skin.json at the archive root"}
    try:
        info_entry = archive.getinfo("info.json")
        source_entry = archive.getinfo(source)
        if info_entry.file_size > INFO_LIMIT or source_entry.file_size > SOURCE_LIMIT:
            return {"ok": False, "error": "Format 2 metadata exceeds the size limit"}
        payload = {
            "info": base64.b64encode(archive.read(info_entry)).decode("ascii"),
            "source": base64.b64encode(archive.read(source_entry)).decode("ascii"),
            "files": archive.namelist(),
        }
    except (KeyError, zipfile.BadZipFile, RuntimeError) as exc:
        return {"ok": False, "error": f"Cannot read format 2 metadata: {exc}"}
    try:
        result = subprocess.run(
            ["node", str(VERIFIER)], input=json.dumps(payload), text=True,
            capture_output=True, timeout=30, check=True,
        )
        verdict = json.loads(result.stdout)
        if not isinstance(verdict, dict) or type(verdict.get("ok")) is not bool:
            raise ValueError("Unexpected verifier result")
        return verdict
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"ok": False, "unavailable": True, "error": str(exc)[:200]}
