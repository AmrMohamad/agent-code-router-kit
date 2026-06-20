from __future__ import annotations

import random
import subprocess
import unittest
from unittest import mock

from scripts.lib.dynamic_task_prompts import (
    discover_code_symbol_targets,
    materialize_task_for_symbol,
    select_code_symbol_target,
)
from scripts.lib.agent_session import TaskSpec


class DynamicTaskPromptTests(unittest.TestCase):
    def test_discovers_kotlin_and_java_declarations(self) -> None:
        result = subprocess.CompletedProcess(
            args=["rg"],
            returncode=0,
            stdout=(
                "./app/src/main/java/com/example/FirstViewModel.kt:3:class FirstViewModel\n"
                "./app/build/generated/Generated.kt:1:class GeneratedIgnored\n"
                "./feature/src/main/java/com/example/SecondPresenter.java:8:public class SecondPresenter {\n"
            ),
            stderr="",
        )
        with mock.patch("scripts.lib.dynamic_task_prompts.subprocess.run", return_value=result):
            targets = discover_code_symbol_targets("/repo")

        self.assertEqual([target.symbol for target in targets], ["FirstViewModel", "SecondPresenter"])
        self.assertEqual(targets[0].language, "kotlin")
        self.assertEqual(targets[1].language, "java")

    def test_select_is_seeded_and_reproducible(self) -> None:
        result = subprocess.CompletedProcess(
            args=["rg"],
            returncode=0,
            stdout=(
                "./app/A.kt:1:class AlphaViewModel\n"
                "./app/B.kt:1:class BetaViewModel\n"
                "./app/C.kt:1:class GammaViewModel\n"
            ),
            stderr="",
        )
        with mock.patch("scripts.lib.dynamic_task_prompts.subprocess.run", return_value=result):
            first = select_code_symbol_target("/repo", rng=random.Random("stable"))
        with mock.patch("scripts.lib.dynamic_task_prompts.subprocess.run", return_value=result):
            second = select_code_symbol_target("/repo", rng=random.Random("stable"))

        self.assertIsNotNone(first)
        self.assertEqual(first, second)

    def test_select_prefers_unique_symbol_names(self) -> None:
        result = subprocess.CompletedProcess(
            args=["rg"],
            returncode=0,
            stdout=(
                "./app/A.kt:1:class DuplicateState\n"
                "./app/B.kt:1:class DuplicateState\n"
                "./app/C.kt:1:class UniqueCheckoutViewModel\n"
            ),
            stderr="",
        )
        with mock.patch("scripts.lib.dynamic_task_prompts.subprocess.run", return_value=result):
            selected = select_code_symbol_target("/repo", rng=random.Random("stable"))

        self.assertIsNotNone(selected)
        self.assertEqual(selected.symbol, "UniqueCheckoutViewModel")

    def test_materialize_task_replaces_placeholder_symbol(self) -> None:
        task = TaskSpec(
            task_id="known_symbol_definition",
            task_family="known_kotlin_symbol_definition",
            repo="sample",
            prompt="Find the definition of SampleFeatureViewModel and report proof.",
            route_profiles=["D-full-router"],
            edit_allowed=False,
            build_allowed=False,
            expected_proof_layer="semantic_identity_or_search_labeled",
            expected_success_signal="SampleFeatureViewModel definition reported",
            forbidden_claims="Do not claim runtime behavior.",
            timeout_seconds=900,
        )
        symbol_target = mock.Mock(
            symbol="CheckoutViewModel",
            source_file="./feature/CheckoutViewModel.kt",
            line=12,
            language="kotlin",
            declaration_kind="class",
        )

        materialized = materialize_task_for_symbol(task, symbol_target)

        self.assertIn("CheckoutViewModel", materialized.prompt)
        self.assertNotIn("SampleFeatureViewModel", materialized.prompt)
        self.assertEqual(materialized.expected_success_signal, "CheckoutViewModel definition reported")
        self.assertEqual(task.prompt, "Find the definition of SampleFeatureViewModel and report proof.")


if __name__ == "__main__":
    unittest.main()
