from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = ROOT / "scripts" / "benchmarks" / "shared" / "output_budget.py"
spec = importlib.util.spec_from_file_location("output_budget", HELPER_PATH)
assert spec and spec.loader
budget = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = budget
spec.loader.exec_module(budget)


class OutputBudgetTests(unittest.TestCase):
    def test_evaluate_output_size_warns_and_fails(self) -> None:
        self.assertEqual(budget.evaluate_output_size(10, warn_bytes=20, fail_bytes=30)["status"], "pass")
        self.assertEqual(budget.evaluate_output_size(25, warn_bytes=20, fail_bytes=30)["status"], "warn")
        self.assertEqual(budget.evaluate_output_size(40, warn_bytes=20, fail_bytes=30)["status"], "fail")
        self.assertEqual(
            budget.evaluate_output_size(40, warn_bytes=20, fail_bytes=30, baseline=True)["status"],
            "warn",
        )

    def test_android_module_and_package_grouping(self) -> None:
        path = "app-core/src/main/java/com/app/core/usecases/FooUseCase.kt"
        self.assertEqual(budget.android_module_from_path(path), "app-core")
        self.assertEqual(budget.android_package_from_path(path), "com.app.core.usecases")

    def test_top_group_counts_sums_counts(self) -> None:
        rows = [
            ("app/src/main/java/com/app/Foo.kt", 2),
            ("app/src/main/java/com/app/Bar.kt", 3),
            ("feature/src/main/java/com/app/Baz.kt", 5),
        ]
        grouped = budget.top_group_counts(rows, budget.android_module_from_path, limit=2)
        self.assertEqual(grouped[0], {"key": "app", "matches": 5})
        self.assertEqual(grouped[1], {"key": "feature", "matches": 5})


if __name__ == "__main__":
    unittest.main()
