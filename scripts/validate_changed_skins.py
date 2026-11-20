"""Validate a PR diff without putting thousands of paths into process arguments."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit, unquote, quote

from skin_schema import validate_entry
from thumbnail_shards import http_get_json, list_release_assets
from validate_skin import check_url_reachable


def changed_files(base):
    raw = subprocess.check_output(['git', 'diff', '--no-renames', '--name-only', '-z',
                                   '--diff-filter=AM', base + '...HEAD', '--', 'skins/**/*.json'])
    return [p for p in raw.decode().split('\0') if p]


def validate(base, paths, check=check_url_reachable):
    releases = {}
    token = os.environ.get('GITHUB_TOKEN', '')
    errors = []
    checked = set()
    for name in paths:
        entry = json.loads(Path(name).read_text())
        errors.extend(f'{name}: {error}' for error in validate_entry(entry))
        old = subprocess.run(['git', 'show', f'{base}:{name}'], capture_output=True, text=True)
        previous = json.loads(old.stdout) if old.returncode == 0 else {}
        url = entry.get('downloadURL')
        if not url or url == previous.get('downloadURL') or url in checked:
            continue
        checked.add(url)
        parsed = urlsplit(url)
        prefix = '/Provenance-Emu/skins/releases/download/'
        if parsed.scheme == 'https' and parsed.netloc == 'github.com' and parsed.path.startswith(prefix):
            tag, asset = parsed.path[len(prefix):].split('/', 1)
            if tag not in releases:
                release = http_get_json('https://api.github.com/repos/Provenance-Emu/skins/releases/tags/' + quote(unquote(tag), safe=''), token)
                if release.get('draft'):
                    raise ValueError('Download release is a draft')
                releases[tag] = {a['name'] for a in list_release_assets(
                    release, lambda u: http_get_json(u, token)) if a.get('state') == 'uploaded' and a.get('size', 0) > 0}
            reachable = unquote(asset) in releases[tag]
        else:
            reachable = check(url)
        if not reachable:
            errors.append(f'{name}: downloadURL is not reachable: {url}')
    for error in errors:
        print(error)
    print(f'Validated {len(paths)} changed skins and {len(checked)} changed download URLs; {len(errors)} errors.')
    return not errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()
    raise SystemExit(0 if validate(args.base, changed_files(args.base)) else 1)


if __name__ == '__main__':
    main()
