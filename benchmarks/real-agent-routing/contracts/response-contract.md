# RARB Response v1

Every subject agent must return a parseable response:

```text
BENCHMARK_RESULT
status: pass|partial|fail|blocked
confidence: high|medium|low

tools_used:
  - ...

proof_layers:
  semantic_identity:
  references:
  runtime:

files_opened:
  count:
  paths:

raw_dump_incidents:
  count:

tool_outputs:
  optional compact excerpts or summaries of command/tool output that entered
  the model-visible answer path

policy_adherence:
  pass|warn|fail

final_answer:
  ...

BENCHMARK_DONE
```

Runs without the configured done sentinel are invalid. In live mode, `tools_used`
is treated as a subject-agent claim; the judge prefers observed terminal, JSONL,
and MCP/tool events from telemetry. Runs that claim runtime or business-flow
proof without a matching proof command are invalid or warned by the judge.
