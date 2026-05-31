# Android Router Benchmark

This benchmark package measures Android/Kotlin routing behavior while keeping raw private output out of public documentation.

## What It Measures

The Android package is capability-based:

| Capability | Files |
|---|---|
| Routing benchmark | `cases.sample.tsv`, `scripts/benchmarks/shared/benchmark_runner.py` |
| Android Studio semantic probe | `studio-semantic-cases.sample.tsv`, `scripts/benchmarks/android/studio_semantic_probe.py` |
| Studio symbol matrix | `studio-symbol-matrix.*.tsv`, `scripts/benchmarks/android/studio_symbol_matrix.py` |
| Serena/Kotlin source symbols | `serena-source-symbol-cases.sample.tsv`, `scripts/benchmarks/android/serena_source_symbol_probe.py` |
| Serena ProjectServer semantics | `serena-project-server-cases.sample.tsv`, `scripts/benchmarks/android/serena_project_server_probe.py` |
| Reference triage | `serena-reference-triage.*.tsv`, `scripts/benchmarks/android/serena_reference_triage.py` |
| Direct MCP reference triage | `serena-mcp-reference-triage.*.tsv`, `scripts/benchmarks/android/serena_mcp_reference_triage.py` |
| Transport/lifecycle probes | `serena-transport.*.tsv`, `serena-mcp-lifecycle.*.tsv` |
| Generated-source mapping | `generated-semantic-mapping.*.tsv`, `scripts/benchmarks/android/generated_semantic_mapping.py` |
| Operational gate | `operational-gates.*.tsv`, `scripts/benchmarks/android/operational_gate.py` |
| Readiness audit | `scripts/benchmarks/android/readiness_audit.py` |
| Agent behavior gate | `agent-behavior.*.tsv`, `scripts/benchmarks/android/agent_behavior_gate.py` |

## Full Suite

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

For a strict run after intentionally cleaning stale Serena/LSP processes:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --require-clean-process-state \
  --enforce-assertions \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

Validate manifests without running cases:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --validate-only \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

## Focused Commands

Default search and structural tools:

```bash
python3 scripts/benchmarks/shared/benchmark_runner.py \
  --validate --run \
  --cases benchmarks/android/cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/default-search \
  --warmups 1 \
  --repeats 3
```

Android Studio semantic probes:

```bash
python3 scripts/benchmarks/android/studio_semantic_probe.py \
  --validate --run \
  --cases benchmarks/android/studio-semantic-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/android-studio-semantic \
  --repeats 2
```

Serena/Kotlin source-symbol probes:

```bash
python3 scripts/benchmarks/android/serena_source_symbol_probe.py \
  --validate --run \
  --cases benchmarks/android/serena-source-symbol-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/serena-source-symbol
```

Serena ProjectServer semantic probes:

```bash
python3 scripts/benchmarks/android/serena_project_server_probe.py \
  --validate --run \
  --cases benchmarks/android/serena-project-server-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/serena-project-server \
  --warmups 1 \
  --repeats 3
```

Process-state probe:

```bash
python3 scripts/benchmarks/android/process_state_probe.py \
  --validate --run \
  --target-project-path /path/to/android-repo \
  --output results/android/process-state
```

Operational gate:

```bash
python3 scripts/benchmarks/android/operational_gate.py \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --device emulator-5554 \
  --variant stagingDebug \
  --enforce-assertions
```

Readiness audit:

```bash
python3 scripts/benchmarks/android/readiness_audit.py \
  --results-root results/android \
  --enforce-stable
```

## Interpretation

The Android benchmark does not try to prove that LSP always beats search. It proves the router chooses the right evidence layer:

```text
Known Kotlin/Java symbol:
  Serena/Kotlin or Java LSP first, after readiness smoke.

High-fanout symbol:
  grouped counts and summaries first.

Literal/resource/XML/generated/GraphQL:
  rg/fd and GraphQL tooling first.

Structural Kotlin/Gradle/Compose/Flow pattern:
  ast-grep first.

Build/runtime:
  Gradle, Android Studio, emulator/device, adb, or CI.
```

If Serena references are empty while Android Studio usages returns concrete locations, record a semantic-layer disagreement. Do not treat either layer as silently authoritative.

## Public Safety

Do not publish raw benchmark output from private repositories without sanitizing paths, source snippets, credentials, package names, and organization-specific identifiers.
