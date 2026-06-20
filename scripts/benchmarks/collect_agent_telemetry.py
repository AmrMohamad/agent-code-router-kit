from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.token_proxy import byte_count, normalize_token_fields
from scripts.lib.transcript_parser import (
    count_tool_mentions,
    count_tools_from_events,
    extract_token_usage,
    observed_tool_events,
    parse_benchmark_response,
    tool_output_bytes,
)
from scripts.lib.agent_session import to_json_file


def collect_metrics(
    *,
    prompt_path: str | Path,
    transcript_path: str | Path,
    out: str | Path,
    run_id: str = "",
) -> dict[str, object]:
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    transcript = Path(transcript_path).read_text(encoding="utf-8")
    parsed = parse_benchmark_response(transcript)
    output_bytes = tool_output_bytes(transcript, fallback_to_transcript=True)
    token_usage = extract_token_usage(transcript)
    observed_events = observed_tool_events(transcript)
    observed_task_events = [event for event in observed_events if event.get("phase") != "bootstrap_context"]
    tool_counts = count_tools_from_events(observed_task_events) if observed_task_events else count_tool_mentions(transcript)
    metrics = {
        "run_id": run_id,
        "done": parsed.done,
        "contract_present": parsed.contract_present,
        "status": parsed.status,
        "policy_adherence": parsed.policy_adherence,
        "tool_call_count": len(parsed.tools_used),
        "files_opened_count": len(parsed.files_opened),
        "raw_dump_incidents": parsed.raw_dump_incidents,
        "raw_output_bytes": output_bytes,
        "observed_tool_events": observed_events,
        "observed_tools": [event["tool"] for event in observed_events],
        "observed_task_tools": [event["tool"] for event in observed_task_events],
        "tool_evidence_source": "observed" if observed_task_events else "self_report" if parsed.tools_used else "missing",
        **tool_counts,
        **normalize_token_fields(
            prompt_bytes=byte_count(prompt),
            answer_bytes=byte_count(parsed.final_answer),
            transcript_bytes=byte_count(transcript),
            tool_output_bytes=output_bytes,
            exact_tokens=token_usage.get("exact"),  # type: ignore[arg-type]
            agent_reported_tokens=token_usage.get("agent_reported"),  # type: ignore[arg-type]
        ),
    }
    to_json_file(out, metrics)
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect normalized metrics from prompt and transcript.")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args(argv)
    metrics = collect_metrics(
        prompt_path=args.prompt,
        transcript_path=args.transcript,
        out=args.out,
        run_id=args.run_id,
    )
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
