"""Exercise publication against real remotes, including a concurrent force push."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


PUBLISH = Path(__file__).resolve().parents[1] / "scripts/publish_site.sh"


class PublishSiteTests(unittest.TestCase):
    def git(self, cwd, *args):
        return subprocess.check_output(["git", "-C", str(cwd), *args], text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote, self.writer, self.build = (root / p for p in ("remote", "writer", "build"))
        self.git(root, "init", "--bare", str(self.remote))
        self.git(root, "clone", str(self.remote), str(self.writer))
        self.git(self.writer, "checkout", "-b", "main")
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_COMMITTER_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_EMAIL": "test@example.com",
                    "FIXTURE_WRITER": str(self.writer), "FIXTURE_COUNT": str(root / "count")}
        # Git setup also needs a disposable identity; never change the user's global config.
        self.git(self.writer, "config", "user.name", "Test")
        self.git(self.writer, "config", "user.email", "test@example.com")
        (self.writer / "scripts").mkdir()
        (self.writer / "docs/js").mkdir(parents=True)
        (self.writer / "source.txt").write_text("initial\n")
        (self.writer / "docs/js/module.js").write_text("source\n")
        shutil.copyfile(PUBLISH, self.writer / "scripts/publish_site.sh")
        (self.writer / "scripts/build_site.sh").write_text('''#!/usr/bin/env bash
set -euo pipefail
echo attempt >> "$FIXTURE_COUNT"
cp source.txt catalog.json
cp source.txt docs/js/module.js
if [ "${RACE_MODE:-}" != "" ] && { [ "$RACE_MODE" = always ] || [ "$(wc -l < "$FIXTURE_COUNT")" -eq 1 ]; }; then
  echo newer >> "$FIXTURE_WRITER/source.txt"
  git -C "$FIXTURE_WRITER" add source.txt
  git -C "$FIXTURE_WRITER" commit -m concurrent
  if [ "$RACE_MODE" = force ]; then
    tree=$(git -C "$FIXTURE_WRITER" rev-parse 'HEAD^{tree}')
    replacement=$(echo replacement | git -C "$FIXTURE_WRITER" commit-tree "$tree")
    git -C "$FIXTURE_WRITER" reset --hard "$replacement"
  fi
  git -C "$FIXTURE_WRITER" push --force origin HEAD:main
fi
''')
        self.git(self.writer, "add", ".")
        self.git(self.writer, "commit", "-m", "initial")
        self.git(self.writer, "push", "origin", "main")
        self.git(root, "clone", "--branch", "main", str(self.remote), str(self.build))

    def publish(self, race=""):
        return subprocess.run(["bash", "scripts/publish_site.sh"], cwd=self.build,
                              env={**self.env, "RACE_MODE": race}, capture_output=True, text=True)

    def test_publishes_generated_files_and_keeps_transformed_assets_for_deploy(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.remote, "show", "main:catalog.json"), "initial")
        self.assertEqual(self.git(self.remote, "show", "main:docs/js/module.js"), "source")
        self.assertEqual((self.build / "docs/js/module.js").read_text(), "initial\n")

    def test_regenerates_after_concurrent_push(self):
        self.check_race("advance")

    def test_regenerates_after_concurrent_force_push(self):
        self.check_race("force")

    def check_race(self, mode):
        result = self.publish(mode)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git(self.remote, "show", "main:catalog.json"), "initial\nnewer")
        self.assertEqual((self.build / "docs/js/module.js").read_text(), "initial\nnewer\n")
        self.assertEqual(len(Path(self.env["FIXTURE_COUNT"]).read_text().splitlines()), 2)
        self.assertEqual(self.git(self.remote, "show", "main:source.txt"), "initial\nnewer")

    def test_stops_after_three_rejected_pushes(self):
        result = self.publish("always")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(Path(self.env["FIXTURE_COUNT"]).read_text().splitlines()), 3)
        self.assertNotEqual(self.git(self.remote, "show", "main:source.txt"), "initial")
        self.assertNotIn("catalog.json", self.git(self.remote, "ls-tree", "--name-only", "main"))


if __name__ == "__main__":
    unittest.main()
