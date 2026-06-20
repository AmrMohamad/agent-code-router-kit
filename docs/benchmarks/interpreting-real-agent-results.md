# Interpreting Real-Agent Results

RARB measures agent behavior, not just tool capability.

## Strong Claims

You can claim a routing arm reduced context only when the report compares the same agent, task, repo commit, repeat policy, and token metric type.

Good:

```text
For the same agent, task, repo commit, and repeat, D-full-router reduced model-visible proxy tokens by the percentage recorded in route-comparisons.json.
```

Bad:

```text
Cursor used fewer tokens than Claude, therefore the router works.
```

## Correctness Comes First

Token reduction is not useful if correctness drops. The first pass condition is:

```text
full-router correctness >= search-only correctness
```

## High-Fanout Tasks

High-fanout tasks should show the largest savings. A full-router run should use summaries first and should have zero raw-dump incidents.

If a live row ends with `completion_reason=output_budget_exceeded`, treat it as
a controlled benchmark failure, not as a missing harness feature. The row proves
the subject agent exceeded the route budget under live monitoring. Keep it in
failure-rate and policy-adherence reporting, but exclude it from pass/pass
savings claims.

## Claim Readiness

`route-comparisons.json` proves that paired measurements exist. It does not by
itself prove that the router saved tokens. Use `route-claim-readiness.json`
before writing a savings claim:

- exact-token savings claims require pass/pass correctness, `token_source=exact`
  on both paired rows, and positive exact-token savings;
- uncached exact-token savings claims require the same exact-token evidence, but
  compare `exact_total_tokens - exact_cached_input_tokens` when cache fields are
  available;
- agent-reported savings claims require pass/pass correctness,
  `token_source=agent_reported` on both paired rows, and positive reported-token
  savings;
- model-visible proxy savings claims require pass/pass correctness and positive
  proxy-token savings;
- if raw exact, uncached exact, agent-reported, and proxy tokens disagree,
  report the distinction instead of choosing the more favorable metric.

The readiness audit has two savings modes:

- without `--min-supported-savings-pairs`, every paired row must support the
  selected savings metric;
- with `--min-supported-savings-pairs N`, at least N paired rows must support
  the selected metric, and the published claim must be scoped to those supported
  rows.

## Runtime Tasks

Launch/build smoke only proves launch/build smoke. It does not prove business-flow correctness.
