# Android Serena Reference Disagreement

This document tracks the stable semantic disagreement between Serena/Kotlin
references and Android Studio usages for concrete Sample B2B symbols. The first
smoke symbol was `SampleFeatureViewModel`; the expanded run also covers
`SampleContentViewModel` and `SamplePushService`. The direct MCP run
adds both stdio and streamable HTTP transport coverage and includes
`SampleGraphQLClient`.

## Current Observation

stable proved these layers for Sample B2B:

```text
Android Studio find-usages:
  returned real Kotlin usages for SampleFeatureViewModel

Serena find_symbol:
  passed

Serena diagnostics:
  passed

Serena find_referencing_symbols:
  returned empty or near-empty output for the same smoke symbol
```

This is not treated as success. It is a named disagreement.

## Latest ProjectServer Triage Run

Latest ProjectServer fallback run:

```text
results/android/serena-reference-triage/android-serena-reference-triage-summary-2026-05-29-202552.json
```

Result:

```text
overall_classification: unclassified disagreement
case_count: 11
assertions: pass=33, warn=4, fail=0

classification_counts:
  unclassified disagreement: 4
  query-shape issue: 6
  kotlin-lsp limitation: 1
```

Case summary:

| Case | Serena find | Serena refs | Studio usages | Classification |
| --- | --- | --- | --- | --- |
| class name | pass | pass, empty `{}` | pass, 2 files | unclassified disagreement |
| larger `max_answer_chars` | pass | pass, empty `{}` | pass, 2 files | unclassified disagreement |
| `SampleContentViewModel` class name | pass | pass, empty `{}` | pass, 2 files | unclassified disagreement |
| `SamplePushService` class name | pass | pass, empty `{}` | pass, 3 files plus manifest | unclassified disagreement |
| indexed name path | pass | error | pass, 2 files | query-shape issue |
| fully qualified name | pass | error | pass, 2 files | query-shape issue |
| no relative path | pass | error | pass, 2 files | query-shape issue |
| DI relative path | pass | error | pass, 2 files | query-shape issue |
| member `handleNotificationClick` | pass | Kotlin LSP error | pass, 1 file | kotlin-lsp limitation |

This means Android Studio usages are currently stronger for this selected
reference pattern. Serena still proves symbol lookup and diagnostics, but its
reference layer should not be used as sole proof for these class-name reference
patterns until the disagreement is fixed or formally routed around.

## Direct MCP Reference Triage

Latest expanded direct MCP stdio run:

```text
results/android/serena-mcp-reference-triage-stdio-expanded/android-serena-mcp-reference-triage-summary-2026-05-30-001146.json
```

Result:

```text
case_count: 8
assertions: pass=37, warn=8, fail=0
classification_counts:
  serena-reference-empty-boundary: 5
  query-shape issue: 2
  kotlin-lsp limitation: 1

transports:
  stdio

process_delta:
  serena_mcp: 0
  kotlin_lsp: 0
  json_lsp: 0
  java_jdtls: 0
```

Direct MCP case summary:

| Symbol | Transport | Serena find | Serena refs | Studio usages | Classification |
| --- | --- | --- | --- | --- | --- |
| `SampleFeatureViewModel` baseline | stdio | pass | pass, empty | pass, expected files | serena-reference-empty-boundary |
| `SampleFeatureViewModel` no relative path | stdio | pass | tool validation error | pass, expected files | query-shape issue |
| `SampleFeatureViewModel[0]` indexed name | stdio | pass | no matching symbol | pass, expected files | query-shape issue |
| `SampleFeatureViewModel` larger answer | stdio | pass | pass, empty | pass, expected files | serena-reference-empty-boundary |
| `handleNotificationClick` member | stdio | pass | Kotlin LSP error | pass, expected file | kotlin-lsp limitation |
| `SampleContentViewModel` | stdio | pass | pass, empty | pass, expected files | serena-reference-empty-boundary |
| `SamplePushService` | stdio | pass | pass, empty | pass, expected files | serena-reference-empty-boundary |
| `SampleGraphQLClient` | stdio | pass | pass, empty | pass, expected file | serena-reference-empty-boundary |

Interpretation: the direct stdio path now has a named boundary rather than a
generic disagreement. Baseline class-level queries, larger answer budgets, and
multiple symbols still return empty Serena references while Studio usages finds
expected files. No-relative-path and indexed-name variants are query-shape
failures. The narrowed member case hits a Kotlin LSP content-root limitation.
For these tested patterns, Android Studio usages is the current reference proof
layer. Serena remains valid for symbol identity and diagnostics, but not for
sole reference proof on these patterns.

## Triage Gate

Run:

```bash
python3 scripts/benchmarks/android/serena_reference_triage.py \
  --validate --run \
  --repo sample_b2b_android=/path/to/sample-repos/sample-b2b-android-app \
  --output results/android/serena-reference-triage
```

The manifest is:

```text
benchmarks/android/serena-reference-triage.sample-b2b.tsv
```

The gate compares three evidence layers for each case:

- Serena `find_symbol`;
- Serena `find_referencing_symbols`;
- Android Studio `find-usages`.

## Cases

The manifest currently tests:

- `SampleFeatureViewModel` class-name reference query;
- indexed `name_path` query;
- fully qualified `name_path` query;
- no-`relative_path` query;
- larger `max_answer_chars`;
- narrowed member query for `handleNotificationClick`;
- DI call-site relative path query;
- `SampleContentViewModel` class-name and no-`relative_path` queries;
- `SamplePushService` class-name and no-`relative_path` queries.

The direct MCP manifest is:

```text
benchmarks/android/serena-mcp-reference-triage.sample-b2b.tsv
```

Run:

```bash
python3 scripts/benchmarks/android/serena_mcp_reference_triage.py \
  --validate --run \
  --repo /path/to/sample-repos/sample-b2b-android-app \
  --transports stdio,streamable-http \
  --timeout 240 \
  --startup-timeout 90 \
  --studio-timeout 120 \
  --enforce-assertions
```

## Classifications

Each case is classified as one of:

- `fixed`;
- `query-shape issue`;
- `stale-index issue`;
- `transport/process issue`;
- `kotlin-lsp limitation`;
- `serena-tool limitation`;
- `serena-reference-empty-boundary`;
- `studio over-reporting`;
- `studio-probe unavailable`;
- `unclassified disagreement`.

`probe` is allowed in the manifest when the expected result is intentionally
unknown and should not fail the runner.

## Policy

Until a case is `fixed`, do not use Serena references as sole reference proof
for these class-level symbol patterns. Use Android Studio usages as the
reference proof layer for the affected patterns and record the disagreement in
any Android semantic-readiness report.

The Readiness readiness audit now treats this as a satisfied replacement gate
when both Studio symbol matrices are trusted and the Sample Retail operational follow-up
is equivalent. That means the policy is resolved; it does not mean Serena
references are correct for these patterns.

If a Serena query variant fixes the disagreement, update the Android routing
policy and stable roadmap with the required query shape before using Serena
references as the primary proof for this pattern.
