# Token Measurement Strategy

RARB uses three token measurement levels.

## Level 1: Exact Tokens

Use exact input/output token telemetry when a subject agent exposes it through OpenTelemetry, usage logs, API metadata, or structured CLI output.

Exact fields:

```text
exact_input_tokens
exact_output_tokens
exact_total_tokens
exact_uncached_total_tokens
exact_cached_input_tokens
exact_cache_creation_input_tokens
exact_cache_read_input_tokens
exact_reasoning_output_tokens
exact_usage_event_count
token_source=exact
```

`exact_total_tokens` remains the comparable total reported or derived from
input/output fields. When structured output exposes Anthropic-style cache
creation/read fields and no explicit total is present, RARB derives the total
from input, output, cache-creation input, and cache-read input tokens. Cached,
cache-creation, cache-read, and reasoning-output fields are preserved as
separate columns because they materially affect cost and interpretation.
When `exact_cached_input_tokens` is available, RARB also records
`exact_uncached_total_tokens = exact_total_tokens - exact_cached_input_tokens`.
Use it only for explicitly cache-adjusted exact-token claims; keep raw exact
totals visible because they remain the full reported usage.

When a transcript contains multiple structured usage events, RARB sums them.
`exact_usage_event_count` records how many structured usage records contributed
to the exact totals.

## Level 2: Agent-Reported Tokens

Some CLIs may print usage summaries without full OTel. Record those separately:

```text
agent_reported_input_tokens
agent_reported_output_tokens
agent_reported_total_tokens
token_source=agent_reported
```

## Level 3: Proxy Tokens

Proxy tokens are always available:

```text
proxy_tokens = ceil(bytes / 4)
```

RARB records:

```text
prompt_proxy_tokens
answer_proxy_tokens
tool_output_proxy_tokens
model_visible_proxy_tokens
```

For live runs, `tool_output_bytes` is taken from a structured `tool_outputs:`
section when present; otherwise the runner falls back to transcript-visible
bytes outside the final answer. Dry-runs keep tool output at zero because no
subject tool output exists.

The telemetry collector parses structured JSONL usage events first, then
agent-reported token summaries, then proxy bytes. Reports must keep exact,
agent-reported, and proxy values separate.

Adapter probes and the adapter doctor expose token readiness before a full
benchmark run:

```text
token_source
exact_total_tokens
exact_usage_event_count
agent_reported_total_tokens
non_proxy_token_telemetry_ready
token_telemetry_ready
token_telemetry_next_action
```

`ready_for_live_benchmark=true` only means the subject-agent adapter can launch
with acceptable route controls. Real-token claims still require
`token_telemetry_ready=true` with `exact_total_tokens` or
`agent_reported_total_tokens` present, and strict run audits should use
`--require-non-proxy-tokens`. Usage events without total-token fields are kept
for diagnostics but do not count as exact-token readiness.
