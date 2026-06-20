from __future__ import annotations

import unittest

from scripts.lib.transcript_parser import (
    classify_failure_reason,
    command_primary_tool,
    count_tools_from_events,
    expand_json_text_fragments,
    extract_token_usage,
    observed_tool_events,
    observed_tool_output_bytes,
    parse_benchmark_response,
    redact_secrets,
    tool_output_bytes,
)


SAMPLE = """BENCHMARK_RESULT
status: pass
confidence: high

tools_used:
  - rg
  - Serena

files_opened:
  count: 1
  paths:
  - app/Foo.kt

raw_dump_incidents:
  count: 0

policy_adherence: pass

final_answer:
  Done from evidence.

BENCHMARK_DONE
"""


class TranscriptParserTests(unittest.TestCase):
    def test_parse_contract(self) -> None:
        parsed = parse_benchmark_response(SAMPLE)
        self.assertTrue(parsed.done)
        self.assertTrue(parsed.contract_present)
        self.assertEqual(parsed.status, "pass")
        self.assertEqual(parsed.confidence, "high")
        self.assertIn("rg", parsed.tools_used)
        self.assertIn("app/Foo.kt", parsed.files_opened)
        self.assertEqual(parsed.final_answer, "Done from evidence.")

    def test_redacts_secret_values(self) -> None:
        self.assertNotIn("abc123", redact_secrets("API_KEY=abc123"))
        self.assertIn("[REDACTED_SECRET]", redact_secrets("API_KEY=abc123"))

    def test_final_answer_keeps_indented_headings(self) -> None:
        parsed = parse_benchmark_response(
            """BENCHMARK_RESULT
status: pass
final_answer:
  Done.
  Evidence:
  - file: app/Foo.kt
BENCHMARK_DONE
"""
        )
        self.assertEqual(parsed.final_answer, "Done.\nEvidence:\n- file: app/Foo.kt")

    def test_tool_output_bytes_prefers_structured_section(self) -> None:
        transcript = """BENCHMARK_RESULT
status: pass
tool_outputs:
  raw line
final_answer:
  ok
BENCHMARK_DONE
"""
        self.assertEqual(tool_output_bytes(transcript), len("raw line".encode("utf-8")))

    def test_live_tool_output_bytes_uses_conservative_transcript_fallback(self) -> None:
        transcript = """large command output from the terminal
BENCHMARK_RESULT
status: pass
tool_outputs:
  compact
final_answer:
  ok
BENCHMARK_DONE
"""
        self.assertGreater(tool_output_bytes(transcript, fallback_to_transcript=True), len("compact"))

    def test_live_tool_output_bytes_prefers_observed_command_payloads_over_json_envelope(self) -> None:
        transcript = (
            '{"type":"item.completed","item":{"id":"cmd-1","type":"command_execution",'
            '"command":"rg Foo","aggregated_output":"abc"}}\n'
            '{"type":"item.completed","item":{"id":"cmd-1","type":"command_execution",'
            '"command":"rg Foo","aggregated_output":"abcdefghij"}}\n'
            'BENCHMARK_RESULT\nstatus: pass\ntool_outputs:\n  compact\nfinal_answer:\n  ok\nBENCHMARK_DONE\n'
        )
        self.assertEqual(observed_tool_output_bytes(transcript), len("abcdefghij"))
        self.assertEqual(tool_output_bytes(transcript, fallback_to_transcript=True), len("abcdefghij"))

    def test_json_protocol_fallback_does_not_charge_entire_transcript(self) -> None:
        transcript = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":'
            '"BENCHMARK_RESULT\\nstatus: pass\\ntool_outputs:\\n  compact\\n'
            'final_answer:\\n  ok\\nBENCHMARK_DONE"}]}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        )
        self.assertEqual(tool_output_bytes(transcript, fallback_to_transcript=True), len("compact"))

    def test_counts_tools_from_observed_events_not_prompt_mentions(self) -> None:
        counts = count_tools_from_events(
            [
                {"tool": "rg", "phase": "task"},
                {"tool": "nl", "phase": "task"},
                {"tool": "find_referencing_symbols", "phase": "task"},
                {"tool": "ast-grep", "phase": "task"},
            ]
        )
        self.assertEqual(counts["search_count"], 2)
        self.assertEqual(counts["semantic_tool_count"], 1)
        self.assertEqual(counts["ast_grep_count"], 1)

    def test_counts_provider_neutral_semantic_navigation_events(self) -> None:
        counts = count_tools_from_events(
            [
                {"tool": "find_declaration", "phase": "task"},
                {"tool": "semSearch", "phase": "task"},
            ]
        )

        self.assertEqual(counts["semantic_tool_count"], 2)

    def test_extracts_exact_token_usage_from_jsonl(self) -> None:
        usage = extract_token_usage(
            '{"type":"usage","input_tokens":11,"cached_input_tokens":5,'
            '"output_tokens":7,"reasoning_output_tokens":3}\n'
        )
        self.assertEqual(
            usage["exact"],
            {
                "input": 11,
                "output": 7,
                "cached_input": 5,
                "reasoning_output": 3,
                "total": 18,
                "usage_event_count": 1,
            },
        )

    def test_sums_exact_token_usage_across_multiple_jsonl_events(self) -> None:
        usage = extract_token_usage(
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2,"cached_input_tokens":4}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":3,"cached_input_tokens":1}}\n'
        )
        self.assertEqual(
            usage["exact"],
            {"input": 15, "output": 5, "cached_input": 5, "total": 20, "usage_event_count": 2},
        )

    def test_preserves_anthropic_cache_usage_fields(self) -> None:
        usage = extract_token_usage(
            '{"type":"assistant","message":{"usage":{'
            '"input_tokens":10,'
            '"cache_creation_input_tokens":20,'
            '"cache_read_input_tokens":30,'
            '"output_tokens":4'
            "}}}\n"
        )
        self.assertEqual(
            usage["exact"],
            {
                "input": 10,
                "output": 4,
                "cached_input": 30,
                "cache_creation_input": 20,
                "cache_read_input": 30,
                "total": 64,
                "usage_event_count": 1,
            },
        )

    def test_extracts_cursor_camel_case_usage_fields(self) -> None:
        usage = extract_token_usage(
            '{"type":"result","usage":{"inputTokens":17795,"outputTokens":33,'
            '"cacheReadTokens":1536,"cacheWriteTokens":0}}\n'
        )
        self.assertEqual(
            usage["exact"],
            {
                "input": 17795,
                "output": 33,
                "cached_input": 1536,
                "cache_creation_input": 0,
                "cache_read_input": 1536,
                "total": 19364,
                "usage_event_count": 1,
            },
        )

    def test_extracts_observed_tool_events(self) -> None:
        events = observed_tool_events("mcp: serena/find_symbol started\nRan rg SampleFeatureViewModel\n")
        self.assertEqual([event["tool"] for event in events], ["serena/find_symbol", "rg"])

    def test_extracts_primary_tool_from_command_execution_json(self) -> None:
        command = "/bin/zsh -lc \"rg -n 'class Foo' .\""
        self.assertEqual(command_primary_tool(command), "rg")
        self.assertEqual(command_primary_tool("/bin/zsh -lc \"'rg' -n Foo .\""), "rg")
        events = observed_tool_events(
            '{"type":"item.completed","item":{"type":"command_execution","command":"/bin/zsh -lc \\"cat /Users/me/.codex/memories/MEMORY.md\\""}}\n'
            '{"type":"item.completed","item":{"type":"command_execution","command":"/bin/zsh -lc \\"rg -n Foo .\\""}}\n'
        )
        self.assertEqual(events[0]["phase"], "bootstrap_context")
        self.assertEqual(events[1]["tool"], "rg")

    def test_extracts_wrapped_command_execution_json_from_pty_text(self) -> None:
        transcript = (
            '{"type":"item.completed","item":{"type":"command_execution","command":'
            '"/bin/zsh -lc \\"rg -n SampleFeatureViewModel app/src/main/java\\""}}\n'
        )
        wrapped = transcript[:84] + "\r\n" + transcript[84:]
        events = observed_tool_events(wrapped)
        self.assertEqual([event["tool"] for event in events], ["rg"])
        self.assertNotIn("{\"type\"", [event["tool"] for event in events])

    def test_extracts_cursor_tool_call_events_and_output_bytes(self) -> None:
        transcript = (
            '{"type":"tool_call","subtype":"completed","call_id":"call-1",'
            '"tool_call":{"grepToolCall":{"args":{"pattern":"Foo"},'
            '"result":{"success":{"content":{"matches":[{"file":"Foo.kt"}]}}}}}}\n'
            '{"type":"tool_call","subtype":"completed","call_id":"call-2",'
            '"tool_call":{"readToolCall":{"args":{"path":"Foo.kt"},'
            '"result":{"success":{"content":"class Foo"}}}}}\n'
        )
        events = observed_tool_events(transcript)
        self.assertEqual([event["tool"] for event in events], ["rg", "read"])
        self.assertGreater(observed_tool_output_bytes(transcript), len("class Foo"))

    def test_cursor_skill_reads_are_bootstrap_not_task_output(self) -> None:
        transcript = (
            '{"type":"tool_call","subtype":"completed","call_id":"skill",'
            '"tool_call":{"readToolCall":{"args":{"path":"/Users/me/.codex/skills/android/SKILL.md"},'
            '"result":{"success":{"content":"large skill text"}}}}}\n'
            '{"type":"tool_call","subtype":"completed","call_id":"search",'
            '"tool_call":{"grepToolCall":{"args":{"pattern":"Foo"},'
            '"result":{"success":{"content":{"matches":[{"file":"Foo.kt"}]}}}}}}\n'
        )
        events = observed_tool_events(transcript)
        task_events = [event for event in events if event.get("phase") != "bootstrap_context"]
        self.assertEqual([event["tool"] for event in events], ["read", "rg"])
        self.assertEqual([event["tool"] for event in task_events], ["rg"])
        self.assertNotEqual(observed_tool_output_bytes(transcript), len("large skill text"))
        self.assertGreater(observed_tool_output_bytes(transcript), 0)

    def test_cursor_started_and_permission_denied_tools_are_not_task_evidence(self) -> None:
        transcript = (
            '{"type":"tool_call","subtype":"started","call_id":"shell",'
            '"tool_call":{"shellToolCall":{"args":{"command":"rg Foo"}}}}\n'
            '{"type":"tool_call","subtype":"completed","call_id":"shell",'
            '"tool_call":{"shellToolCall":{"result":{"permissionDenied":{"error":"blocked"}}}}}\n'
            '{"type":"tool_call","subtype":"completed","call_id":"search",'
            '"tool_call":{"grepToolCall":{"args":{"pattern":"Foo"},'
            '"result":{"success":{"content":"Foo.kt"}}}}}\n'
        )
        events = observed_tool_events(transcript)
        self.assertEqual([event["tool"] for event in events], ["rg"])

    def test_counts_generic_json_tool_result_bytes_without_bootstrap_noise(self) -> None:
        transcript = (
            '{"type":"tool_call","id":"bootstrap","name":"initial_instructions","result":"large setup output"}\n'
            '{"type":"tool_call","id":"symbol-1","name":"find_symbol","result":"class FooViewModel"}\n'
            '{"type":"tool_call","id":"symbol-1","name":"find_symbol","result":"class FooViewModel with members"}\n'
        )
        events = observed_tool_events(transcript)
        self.assertEqual(
            [event["tool"] for event in events if event.get("phase") != "bootstrap_context"],
            ["find_symbol", "find_symbol"],
        )
        self.assertEqual(
            observed_tool_output_bytes(transcript),
            len("class FooViewModel with members".encode("utf-8")),
        )

    def test_extracts_wrapped_exact_token_usage_from_pty_text(self) -> None:
        transcript = '{"type":"usage","input_tokens":12345,"output_tokens":67}\n'
        wrapped = transcript[:35] + "\r\n" + transcript[35:]
        usage = extract_token_usage(wrapped)
        self.assertEqual(
            usage["exact"],
            {"input": 12345, "output": 67, "total": 12412, "usage_event_count": 1},
        )

    def test_classifies_agent_bootstrap_tools_and_ignores_symbol_ran_lines(self) -> None:
        transcript = (
            '{"type":"tool_call","name":"initial_instructions"}\n'
            '{"type":"tool_call","name":"onboarding"}\n'
            '{"type":"tool_call","name":"find_symbol"}\n'
            "Ran SampleFeatureViewModel\n"
            "Ran rg SampleFeatureViewModel\n"
        )
        events = observed_tool_events(transcript)
        task_tools = [event["tool"] for event in events if event.get("phase") != "bootstrap_context"]
        self.assertEqual(task_tools, ["find_symbol", "rg"])

    def test_does_not_treat_final_answer_tool_mentions_as_tool_events(self) -> None:
        transcript = "SampleFeatureViewModel was found with rg evidence, but this line is prose.\n"
        self.assertEqual(observed_tool_events(transcript), [])

    def test_parse_contract_from_jsonl_text_fragment(self) -> None:
        transcript = (
            '{"type":"message","content":"BENCHMARK_RESULT\\nstatus: pass\\n'
            'raw_dump_incidents:\\n  count: 0\\npolicy_adherence: pass\\n'
            'final_answer:\\n  ok\\nBENCHMARK_DONE"}\n'
        )
        self.assertIn("BENCHMARK_RESULT", expand_json_text_fragments(transcript))
        parsed = parse_benchmark_response(transcript)
        self.assertTrue(parsed.done)
        self.assertEqual(parsed.status, "pass")

    def test_does_not_parse_contract_from_user_json_event(self) -> None:
        transcript = (
            '{"type":"user","message":{"role":"user","content":[{"type":"text",'
            '"text":"BENCHMARK_RESULT\\nstatus: pass\\nBENCHMARK_DONE"}]}}\n'
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"quota exceeded"}]}}\n'
        )
        parsed = parse_benchmark_response(transcript)
        self.assertFalse(parsed.done)
        self.assertFalse(parsed.contract_present)

    def test_classifies_prompt_delivery_failure(self) -> None:
        self.assertEqual(
            classify_failure_reason("Error: Input must be provided either through stdin or as a prompt argument"),
            "prompt_delivery_failed",
        )

    def test_classifies_claude_model_access_denied_separately_from_auth_failure(self) -> None:
        self.assertEqual(
            classify_failure_reason("Your organization does not have access to Claude."),
            "model_access_denied",
        )
        self.assertEqual(classify_failure_reason('{"error":"authentication_failed"}'), "authentication_failed")


if __name__ == "__main__":
    unittest.main()
