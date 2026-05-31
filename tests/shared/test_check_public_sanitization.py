from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "shared" / "check_public_sanitization.py"
spec = importlib.util.spec_from_file_location("check_public_sanitization", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class PublicSanitizationTests(unittest.TestCase):
    def init_repo(self, root: Path) -> None:
        subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE)

    def test_detects_private_identifier_in_public_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.init_repo(root)
            token = probe.banned_tokens()[0].token
            (root / "README.md").write_text(f"private={token}\n")
            violations = probe.scan(root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0]["where"], "line 1")

    def test_detects_private_identifier_in_public_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.init_repo(root)
            token = probe.banned_tokens()[1].token
            path = root / f"{token}.md"
            path.write_text("sample\n")
            violations = probe.scan(root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0]["where"], "path")

    def test_ignores_local_results(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.init_repo(root)
            token = probe.banned_tokens()[2].token
            results = root / "results"
            results.mkdir()
            (results / "private.md").write_text(token)
            self.assertEqual(probe.scan(root), [])


if __name__ == "__main__":
    unittest.main()
