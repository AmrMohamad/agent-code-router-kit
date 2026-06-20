from __future__ import annotations

import unittest

from scripts.agents.codex_tui_terminal_bridge import answer_delta


class CodexTuiTerminalBridgeTests(unittest.TestCase):
    def test_answer_delta_removes_exact_baseline_prefix(self) -> None:
        baseline = "OpenAI Codex\n> old prompt"
        transcript = baseline + "\nassistant answer\nDONE"

        self.assertEqual(answer_delta(baseline, transcript), "assistant answer\nDONE")

    def test_answer_delta_falls_back_to_common_line_prefix(self) -> None:
        baseline = "line one\nline two"
        transcript = "line one\nline two changed\nline three"

        self.assertEqual(answer_delta(baseline, transcript), "line two changed\nline three")


if __name__ == "__main__":
    unittest.main()
