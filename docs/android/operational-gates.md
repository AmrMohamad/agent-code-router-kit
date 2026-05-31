# Android Operational Gates

Android operational gates test whether a real Android app can move beyond
routing policy into build/install/launch smoke while preserving semantic,
discovery, generated-source, process, and runtime proof boundaries.

## Capability Scope

```text
Routing benchmark:
  tool-selection proof across search, semantic, structural, generated, and
  runtime boundaries.

Operational gate:
  app-level proof for Studio semantics, Serena/Kotlin behavior,
  generated-source discovery, high-fanout summaries, Gradle build/install, and
  launch smoke.

Readiness audit:
  aggregate check that process state, semantic disagreements, generated-source
  mapping, transport, memory, behavior, and second-repo scope have evidence.
```

## Current Operational Result

Latest recorded Sample B2B gate:

```text
summary:
  pass: 12
  warn: 2
  fail: 0

manifest_policy:
  pass: 14
  fail: 0
```

Evidence path:

```text
results/android/operational/android-operational-summary-2026-05-29-124321.json
```

The gate is app-level smoke evidence. It is not a business-flow runtime test and
does not make LSP, Studio, or Gradle interchangeable proof layers.

## What Passed

- Android Studio saw `SampleWholesaleAndroid` as ready.
- Android Studio `analyze-file` passed for the smoke source file.
- Android Studio `find-declaration` passed for `SampleFeatureViewModel`.
- Android Studio `find-usages` passed for `SampleFeatureViewModel`.
- Serena/Kotlin semantic symbol lookup passed.
- Serena diagnostics passed.
- Generated-source readiness passed.
- High-fanout summary discipline passed without raw dumps.
- Gradle `help` passed on Gradle 8.13.
- `:app:assembleStagingDebug` passed.
- `:app:installStagingDebug` passed.
- adb package launch smoke passed.

## Named Warnings

The gate has two important warnings. They are intentional evidence, not hidden
successes.

### 1. Serena Process-State Risk

The latest process probe showed:

```text
serena_mcp: 6
kotlin_lsp: 0
json_lsp: 0
java_jdtls: 0
status: stale-session-risk
```

This means strict process mode is not yet proven clean. The process-state probe
now supports project-aware classification so the next strict run can distinguish
target-project Serena sessions from other-project, controlled streamable-HTTP
server, stale, and unknown sessions. The strict gate compares the expected
count to target-project sessions, not blindly to every Serena process on the
machine; other-project sessions still fail strict mode unless explicitly
allowed with `--allow-other-project-serena`.

Latest project-aware probe against the Sample B2B repo:

```text
results/android/process-state-stable-project-aware/android-process-state-summary-2026-05-29-234258.json
status: stale-session-risk
serena_mcp: 4
classification_counts:
  other_project_cwd: 4
target_serena_mcp_count: 0
unknown_serena_mcp_count: 0
assertions: pass=5, warn=1, fail=0
```

With other active Serena/Codex sessions explicitly allowed, the target-project
strict check passes:

```text
results/android/process-state-stable-project-aware-allowed-other/android-process-state-summary-2026-05-29-234408.json
status: clean
target_serena_mcp_count: 0
other_project_serena_mcp_count: 4
unknown_serena_mcp_count: 0
assertions: pass=6, warn=0, fail=0
```

This is not the same as clean-room strict mode after closing all sessions. It
proves the gate can distinguish Sample B2B target-process cleanliness from
intentional other-project sessions.

Project-aware strictness must be accepted explicitly before it can satisfy the
readiness process gate:

```bash
python3 scripts/benchmarks/android/process_scope_acceptance.py \
  --accept-project-aware-strictness \
  --accepted-by "<name-or-role>" \
  --reason "Other Serena sessions are intentionally active for unrelated projects; target-project ownership is clean."
```

A run without `--accept-project-aware-strictness` is template-only and does not
satisfy readiness. This prevents the benchmark from silently treating other active
Serena/Codex workspaces as clean-room proof. The latest acceptance artifact
explicitly accepts project-aware strictness for the current machine:

```text
results/android/process-scope-acceptance/android-process-scope-acceptance-summary-2026-05-30-083208.json
status: accepted
assertions: pass=3, warn=0, fail=0
```

Current project-aware process probe result:

```text
Assertions: pass=6, warn=0, fail=0
target_serena_mcp_count: 0
other_project_serena_mcp_count: 1
unknown_serena_mcp_count: 0
classification: other_project_cwd=1
```

An earlier dry-run cleanup script reported six Serena MCP processes and did not
stop them:

```text
scripts/setup/repair-serena-android-sessions.sh --dry-run
Serena MCP processes: 6
Kotlin LSP processes: 0
JSON LSP processes: 0
Java/JDTLS processes: 0
```

No cleanup was performed during this snapshot because the remaining session can
belong to another active Codex/Serena workspace. readiness is satisfied through
project-aware scope acceptance, not clean-room proof.

### 2. Serena Reference Disagreement

For the selected smoke symbol:

```text
Android Studio find-usages:
  returned real Kotlin usages for SampleFeatureViewModel

Serena find_symbol:
  passed

Serena diagnostics:
  passed

Serena find_referencing_symbols:
  returned empty or near-empty output
```

This is a semantic-layer disagreement. Do not treat it as a Serena reference
success. The next step is focused triage against exact symbol paths, fully
qualified names, relative paths, constructor/member symbols, increased output
limits, process cleanup, re-indexing, and HTTP/server-mode Serena.

The initial triage package is:

```text
benchmarks/android/serena-reference-triage.sample-b2b.tsv
scripts/benchmarks/android/serena_reference_triage.py
docs/android/android-serena-reference-disagreement.md
```

The latest expanded triage run classified the issue as:

```text
case_count: 11
overall_classification: unclassified disagreement
classification_counts:
  unclassified disagreement: 4
  query-shape issue: 6
  kotlin-lsp limitation: 1
assertions: pass=33, warn=4, fail=0
```

The expanded manifest now covers `SampleFeatureViewModel`,
`SampleContentViewModel`, and `SamplePushService`. Studio usages
returned expected Kotlin/XML files for those symbols while Serena class-name
reference attempts returned empty `{}`. Other name-shape variants failed as
query-shape issues, and the member-level query hit a Kotlin LSP limitation.

Evidence path:

```text
results/android/serena-reference-triage/android-serena-reference-triage-summary-2026-05-29-202552.json
```

Direct MCP reference triage now confirms the same boundary through both stdio
and streamable HTTP for the original class-level smoke cases. The expanded
stdio pass adds query-shape and member-level variants:

```text
case_count: 8
assertions: pass=37, warn=8, fail=0
classification_counts:
  serena-reference-empty-boundary: 5
  query-shape issue: 2
  kotlin-lsp limitation: 1

symbols:
  SampleFeatureViewModel
  SampleContentViewModel
  SamplePushService
  SampleGraphQLClient

transports:
  stdio
  streamable-http

process_delta:
  serena_mcp: 0
  kotlin_lsp: 0
  json_lsp: 0
  java_jdtls: 0
```

Evidence path:

```text
results/android/serena-mcp-reference-triage/android-serena-mcp-reference-triage-summary-2026-05-29-222707.json
```

Interpretation: the reference disagreement is not just a ProjectServer fallback
artifact and is not resolved by switching between stdio and streamable HTTP.
For these class-level reference patterns, route reference proof to Android
Studio usages until Serena references are fixed.

## Studio Matrix Gate

The next stable hardening layer is the Android Studio semantic matrix:

```text
benchmarks/android/studio-symbol-matrix.sample-b2b.tsv
scripts/benchmarks/android/studio_symbol_matrix.py
```

This exists because the `SampleFeatureViewModel` smoke result is not enough to
trust Studio declaration/usages broadly. The matrix checks sixteen symbols
across ViewModels, methods, use cases, services, network code, DI properties,
request builders, and generated/broad-name boundaries. It requires expected
declaration and usage files, not just non-empty CLI output.

Latest live matrix result:

```text
case_count: 16
trusted_studio_layer: true
declaration_pass_count: 15
usage_pass_count: 16
assertions:
  pass: 18
  warn: 2
  fail: 0
classification_counts:
  pass: 15
  no-result-classified: 1
```

Evidence path:

```text
results/android/studio-symbol-matrix/android-studio-symbol-matrix-summary-2026-05-29-191347.json
```

The only warning is the expected generated-source boundary for `BuildConfig`.
That boundary supports the routing rule: generated surfaces start with
discovery/build mapping, not direct source-symbol proof.

Promotion rule:

```text
Android Studio becomes a secondary semantic proof layer only after the matrix
passes its declaration/usages thresholds with classified no-result cases.
```

## Generated-Source Semantic Mapping

stable now separates generated-source proof into four layers:

```text
discovery:
  source surface, generated file, and usage file exist

mapping:
  source pattern maps to generated symbol and source usage

semantic:
  Studio/LSP can navigate to the generated symbol when supported

build:
  Gradle task proves generated integration
```

The generated mapping package is:

```text
benchmarks/android/generated-semantic-mapping.sample-b2b.tsv
scripts/benchmarks/android/generated_semantic_mapping.py
```

Latest live result with build proofs:

```text
case_count: 5
mapping_pass_count: 5
semantic_pass_count: 2
build_proofs_requested: true
assertions:
  pass: 14
  warn: 3
  fail: 0
classification_counts:
  pass: 2
  pass-with-boundary: 3
semantic_classification_counts:
  pass: 2
  boundary: 3
```

Evidence path:

```text
results/android/generated-semantic-mapping/android-generated-semantic-mapping-summary-2026-05-29-193909.json
```

Interpretation:

- Apollo generated query/mutation flows are discovery-proven, mapping-proven,
  Studio-semantic-proven, and build-proven.
- Room DAO implementation, Moshi adapter, and BuildConfig flows are
  discovery-proven, mapping-proven, and build-proven, but direct semantic lookup
  remains a generated-source boundary.

## High-Fanout Budget

stable now uses a reusable output budget helper:

```text
scripts/benchmarks/shared/output_budget.py
```

The Android high-fanout summary groups broad symbols by module, package, and
file without raw snippets:

```text
scripts/benchmarks/android/high_fanout_summary.py
```

Latest Sample B2B run:

```text
assertions:
  pass: 10
  warn: 8
  fail: 0

UseCase:
  files: 262
  matches: 1813
  output_budget: warn, 22590 bytes
  top_modules: app=585, app-checkout=257, app-core=229
  top_packages: com.app.core.di=526, com.app.core.usecases=203

ViewModel:
  files: 101
  matches: 330
  output_budget: pass, 8032 bytes
  top_modules: app=87, app-orders=50, auth-module=35

Repository:
  files: 175
  matches: 676
  output_budget: warn, 14188 bytes
  top_modules: app-core=390, app=121, app-checkout=74

Mapper:
  files: 16
  matches: 30
  output_budget: pass, 1238 bytes

Service:
  files: 156
  matches: 1447
  output_budget: warn, 12643 bytes

Module:
  files: 40
  matches: 93
  output_budget: pass, 3038 bytes
```

Evidence path:

```text
results/android/high-fanout-summary-sample_b2b-stable-expanded/android-high-fanout-summary-2026-05-29-231150.json
```

Interpretation: high-fanout broad names remain summary-first only. Count output
above 12 KB warns; output above 50 KB fails unless explicitly marked as a
baseline. The summary output now includes `mode: summary_only`, grouped counts,
and per-pattern next actions such as narrowing by module, package, concrete
class, or member before switching to semantic proof.

## Serena ProjectServer Transport

stable now has a bounded ProjectServer fallback transport benchmark:

```text
scripts/benchmarks/android/serena_transport_benchmark.py
benchmarks/android/serena-transport.sample-b2b.tsv
```

Latest Sample B2B run:

```text
mode: project-server-fallback
case_count: 5
measured_rows: 25
repeats: 5
warmups: 1
assertions:
  pass: 38
  warn: 0
  fail: 0
process_delta:
  serena_mcp: 0
  kotlin_lsp: 0
  json_lsp: 0
  java_jdtls: 0
```

Evidence path:

```text
results/android/serena-transport/android-serena-transport-summary-2026-05-29-202023.json
```

Interpretation: the Serena ProjectServer fallback is stable for repeated
symbol, overview, diagnostics, and reference calls in this run. This remains
separate from direct Codex MCP lifecycle proof.

## Direct Serena MCP Lifecycle

stable now has a direct stdio-vs-streamable-HTTP lifecycle probe:

```text
scripts/benchmarks/android/serena_mcp_lifecycle_probe.py
benchmarks/android/serena-mcp-lifecycle.sample-b2b.tsv
```

The probe starts a temporary Serena MCP server, initializes the MCP session,
lists tools, then calls `find_symbol` for real Sample B2B symbols across feature,
service, and network code:

```text
SampleFeatureViewModel
SampleContentViewModel
SamplePushService
SampleGraphQLClient
```

Latest Sample B2B run with a 240 second semantic timeout:

```text
case_count: 8
assertions:
  pass: 10
  warn: 0
  fail: 0

stdio:
  initialize: pass
  tools/list: pass
  tool_count: 22
  find_symbol cases: 4/4 pass

streamable-http:
  initialize: pass
  tools/list: pass
  tool_count: 22
  find_symbol cases: 4/4 pass

process_delta:
  serena_mcp: 0
  kotlin_lsp: 0
  json_lsp: 0
  java_jdtls: 0
```

Evidence path:

```text
results/android/serena-mcp-lifecycle/android-serena-mcp-lifecycle-summary-2026-05-29-221154.json
```

Latest lifecycle rerun:

```text
results/android/serena-mcp-lifecycle/android-serena-mcp-lifecycle-summary-2026-05-30-063552.json
candidate_transport: streamable-http
recommendation_status: lifecycle_candidate_only
process_delta: serena_mcp=0, kotlin_lsp=0, json_lsp=0, java_jdtls=0
```

Transport recommendation audit:

```text
results/android/transport-recommendation/android-transport-recommendation-summary-2026-05-30-065042.json
candidate_transport: streamable-http
recommendation_status: lifecycle_candidate_only
qualified_lifecycle_runs: 3
real_task_observations: 0 / 10
```

An earlier run with a 90 second semantic timeout initialized stdio and listed
tools, but timed out on the cold `find_symbol` call. Streamable HTTP passed the
same semantic call in that run after the Kotlin layer had warmed. Treat this as
a timeout-budget and cold-start boundary, not as a transport-closed failure.

Interpretation: both local MCP transports can be made operational for Sample B2B
symbol lookup across different code areas when the timeout budget is realistic.
This does not resolve the Serena reference-disagreement gate, and it does not
by itself make Android complete. It does make streamable HTTP a viable
controlled-lifecycle candidate and keeps stdio viable when configured with
longer tool timeouts. Do not promote either transport to the daily default from
lifecycle smoke alone.

## Kotlin LSP Memory Matrix

stable now has a safe memory-matrix harness:

```text
scripts/benchmarks/android/kotlin_lsp_memory_matrix.py
```

It temporarily writes `.serena/project.local.yml`, runs the ProjectServer
transport cases, then restores the original file unless `--keep-local-override`
is explicitly passed.

Latest Sample B2B run:

```text
values: -Xmx2G, -Xmx4G, -Xmx6G
assertions:
  pass: 87
  warn: 0
  fail: 0
recommended_jvm_options: -Xmx2G

-Xmx2G: median=0.111s, avg=0.266s, p95=0.813s, process_delta=0
-Xmx4G: median=0.111s, avg=0.265s, p95=0.797s, process_delta=0
-Xmx6G: median=0.110s, avg=0.325s, p95=1.036s, process_delta=0
```

Evidence path:

```text
results/android/kotlin-lsp-memory-matrix/android-kotlin-lsp-memory-matrix-summary-2026-05-29-204205.json
```

Interpretation: under the measured ProjectServer fallback path, `-Xmx2G`
remains the lowest stable memory setting. Do not change the global Android
recommendation to `-Xmx4G` or `-Xmx6G` without a separate failing transport,
timeout, or large-symbol memory result.

## Current Boundary

stable proves that Sample B2B can pass an operational hardening gate on this machine.
It does not prove:

- Android LSP is globally complete;
- Sample Retail semantic/reference behavior is globally clean. Sample Retail now has equivalent
  stable operational follow-up proof, but still keeps reference/process
  boundaries;
- Serena references are trustworthy for the selected class-name reference
  patterns;
- Android Studio declarations/usages are globally trustworthy beyond the Sample B2B
  matrix;
- generated-source semantic mapping is complete across all generated surfaces;
- Codex MCP stdio/HTTP transport is chosen for daily use, beyond the current
  lifecycle smoke;
- launch smoke proves business-flow correctness;
- build/install success proves semantic reference correctness.

## External Context

This boundary matches the current Android tooling reality:

- Kotlin Language Server is official, but active development / Alpha, with
  experimental Android Gradle Plugin support:
  https://kotlinlang.org/docs/kotlin-lsp.html
- Serena exposes Kotlin LSP configuration, including JVM options such as the
  default `-Xmx2G`:
  https://oraios.github.io/serena/02-usage/050_configuration.html
- Android CLI provides agent-oriented Studio commands such as `check`,
  `analyze-file`, `find-declaration`, and `find-usages`:
  https://developer.android.com/tools/agents/android-cli

## Next Claim

The correct current label is:

```text
Android Sample B2B operational hardening passed with named warnings.
```

Use `docs/android/readiness-audit.md` to decide whether the broader Android
workflow is ready under the recorded scope.
