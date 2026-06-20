from __future__ import annotations

import unittest

from scripts.lib.token_proxy import byte_count, estimate_tokens_from_bytes, normalize_token_fields


class TokenProxyTests(unittest.TestCase):
    def test_estimate_tokens_rounds_up(self) -> None:
        self.assertEqual(estimate_tokens_from_bytes(0), 0)
        self.assertEqual(estimate_tokens_from_bytes(1), 1)
        self.assertEqual(estimate_tokens_from_bytes(4), 1)
        self.assertEqual(estimate_tokens_from_bytes(5), 2)

    def test_normalize_token_fields_keeps_proxy_separate(self) -> None:
        metrics = normalize_token_fields(prompt_bytes=4, answer_bytes=8, transcript_bytes=12, tool_output_bytes=4)
        self.assertEqual(metrics["token_source"], "proxy")
        self.assertEqual(metrics["model_visible_bytes"], 16)
        self.assertEqual(metrics["model_visible_proxy_tokens"], 4)
        self.assertIsNone(metrics["exact_input_tokens"])

    def test_normalize_token_fields_preserves_exact_auxiliary_fields(self) -> None:
        metrics = normalize_token_fields(
            prompt_bytes=4,
            answer_bytes=8,
            transcript_bytes=12,
            exact_tokens={
                "input": 11,
                "output": 7,
                "total": 18,
                "cached_input": 5,
                "cache_creation_input": 2,
                "cache_read_input": 5,
                "reasoning_output": 3,
                "usage_event_count": 2,
            },
        )
        self.assertEqual(metrics["token_source"], "exact")
        self.assertEqual(metrics["exact_total_tokens"], 18)
        self.assertEqual(metrics["exact_cached_input_tokens"], 5)
        self.assertEqual(metrics["exact_uncached_total_tokens"], 13)
        self.assertEqual(metrics["exact_cache_creation_input_tokens"], 2)
        self.assertEqual(metrics["exact_cache_read_input_tokens"], 5)
        self.assertEqual(metrics["exact_reasoning_output_tokens"], 3)
        self.assertEqual(metrics["exact_usage_event_count"], 2)

    def test_exact_usage_event_without_total_does_not_claim_exact_token_source(self) -> None:
        metrics = normalize_token_fields(
            prompt_bytes=4,
            answer_bytes=8,
            transcript_bytes=12,
            exact_tokens={"usage_event_count": 2},
        )

        self.assertEqual(metrics["token_source"], "proxy")
        self.assertEqual(metrics["exact_usage_event_count"], 2)
        self.assertIsNone(metrics["exact_total_tokens"])

    def test_byte_count_is_utf8(self) -> None:
        self.assertEqual(byte_count("abc"), 3)


if __name__ == "__main__":
    unittest.main()
