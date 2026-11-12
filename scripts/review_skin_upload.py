"""Inspect a staged upload and extract its files for maintainer review."""

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, BadZipFile, ZipFile


MIB = 1024 * 1024


def review_bundle(bundle: Path, output: Path) -> None:
    if bundle.stat().st_size > 16 * MIB:
        raise ValueError("Bundle exceeds 16 MiB.")
    with ZipFile(bundle) as archive:
        members = archive.infolist()
        names = {entry.filename for entry in members}
        if len(members) != len(names) or not 2 <= len(members) <= 6:
            raise ValueError("Expected a manifest and one to five unique skin files.")
        if "submission.json" not in names:
            raise ValueError("Missing submission.json.")
        if any(entry.compress_type != ZIP_STORED for entry in members):
            raise ValueError("Expected an uncompressed outer bundle.")
        if archive.getinfo("submission.json").file_size > 16 * 1024:
            raise ValueError("Manifest exceeds 16 KiB.")
        manifest = json.loads(archive.read("submission.json"))
        if not isinstance(manifest, dict) or manifest.get("permission") is not True:
            raise ValueError("Missing permission to host the skins.")
        author = manifest.get("author")
        if not isinstance(author, str) or not 1 <= len(author.strip()) <= 80:
            raise ValueError("Invalid author name.")
        source = manifest.get("sourceURL", "")
        if not isinstance(source, str) or len(source) > 1024:
            raise ValueError("Invalid source URL.")
        if source:
            url = urlsplit(source)
            if url.scheme != "https" or not url.hostname or url.username is not None:
                raise ValueError("Source URL must use HTTPS without credentials.")

        files = manifest.get("files")
        if not isinstance(files, list) or len(files) != len(members) - 1:
            raise ValueError("Manifest does not match the bundle.")
        paths = []
        for index, entry in enumerate(files, 1):
            path = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(path, str) or not re.fullmatch(
                rf"skin-{index}\.(deltaskin|manicskin)", path
            ):
                raise ValueError("Unexpected skin file path.")
            paths.append(path)
        if set(paths) != names - {"submission.json"}:
            raise ValueError("Manifest does not match the bundle.")
        if sum(archive.getinfo(path).file_size for path in paths) > 15 * MIB:
            raise ValueError("Skin files exceed 15 MiB.")

        # Read and check CRCs before creating any output. Use only known names.
        skins = {path: archive.read(path) for path in paths}
        if any(not data.startswith(b"PK\x03\x04") for data in skins.values()):
            raise ValueError("One or more skin files are not ZIP archives.")
        output.mkdir()
        (output / "submission.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        for path, data in skins.items():
            (output / path).write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path, help="A new directory for review files")
    args = parser.parse_args()
    try:
        review_bundle(args.bundle, args.output)
    except (BadZipFile, OSError, ValueError) as error:
        parser.exit(1, f"Cannot unpack submission: {error}\n")


if __name__ == "__main__":
    main()
