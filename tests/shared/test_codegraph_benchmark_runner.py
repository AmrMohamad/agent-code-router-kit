from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class CodeGraphBenchmarkRunnerTests(unittest.TestCase):
    def run_script(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(argv),
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_benchmark_runner_prepares_route_isolation_assets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out_dir = Path(raw) / "out"
            result = self.run_script(
                "python3",
                "scripts/benchmarks/run_codegraph_router_benchmark.py",
                "--agent",
                "codex",
                "--repo-root",
                str(ROOT),
                "--out",
                str(out_dir),
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "prepared")
            for arm in ("CG-A-control", "CG-D-bounded-router"):
                route = json.loads((out_dir / arm / "route-isolation.json").read_text(encoding="utf-8"))
                shim = Path(route["blocked_tool_path"])
                self.assertTrue(shim.exists())
                self.assertTrue(shim.read_text(encoding="utf-8"))

    def test_optional_raw_arm_uses_passthrough_shim(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study = Path(raw) / "study.yaml"
            study.write_text(
                "study_id: codegraph-router-v1\n"
                "arms: CG-A-control,CG-B-policy-only,CG-C-capability-only,CG-D-bounded-router,CG-X-raw-codegraph\n",
                encoding="utf-8",
            )
            out_dir = Path(raw) / "out"
            result = self.run_script(
                "python3",
                "scripts/benchmarks/run_codegraph_router_benchmark.py",
                "--study-plan",
                str(study),
                "--agent",
                "codex",
                "--repo-root",
                str(ROOT),
                "--out",
                str(out_dir),
                "--json",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            route = json.loads((out_dir / "CG-X-raw-codegraph" / "route-isolation.json").read_text(encoding="utf-8"))
            shim = Path(route["blocked_tool_path"])
            self.assertFalse(route["raw_codegraph_bypass_blocked"])
            self.assertTrue(route["raw_codegraph_passthrough"])
            self.assertIn('exec "$ACR_CODEGRAPH_BIN" "$@"', shim.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
