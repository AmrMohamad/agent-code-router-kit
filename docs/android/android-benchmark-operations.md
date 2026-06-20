# Android Benchmark Operations

This page contains the Android/Kotlin benchmark and operational gate commands that are useful when exercising the Android side of the toolkit. The root README keeps Android detail out of the front-page flow, but the commands remain here for reproducibility.

## Android Suite Runner

For a full Android/Kotlin routing benchmark over two Android repos, use the suite runner:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

This runs default `rg` / `fd` / `ast-grep` measurements, Android Studio semantic probes, Serena/Kotlin LSP source-symbol probes, Serena ProjectServer semantic probes, process-state checks, project-model readiness checks, and report generation. The project-model check is preflight-only unless `--run-gradle-project-model` is passed.

For a strict Android regression run after intentionally cleaning stale Serena/LSP processes:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --require-clean-process-state \
  --enforce-assertions \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

## Operational Gates

For the Sample B2B-first Android operational hardening gate, use the real open Android Studio/emulator setup:

```bash
python3 scripts/benchmarks/android/operational_gate.py \
  --sample-b2b-repo /path/to/sample-repos/sample-b2b-android-app \
  --device emulator-5554 \
  --variant stagingDebug \
  --enforce-assertions
```

This stable gate checks Android Studio declaration/usages recovery, Serena/Kotlin semantic proof, generated-source readiness, high-fanout summary discipline, Gradle 8.13 project-model/build proof, APK install, and package launch smoke on Sample B2B as a testbed. Sample Retail has a separate stable operational follow-up gate against its Gradle 9 project model.

To expand the Android Studio proof beyond one smoke symbol, run the stable Studio symbol matrix:

```bash
python3 scripts/benchmarks/android/studio_symbol_matrix.py \
  --validate --run \
  --repo sample_b2b=/path/to/sample-repos/sample-b2b-android-app \
  --enforce-assertions
```

This matrix requires expected declaration and usage files across ViewModels, methods, DI properties, services, network code, request builders, and generated/broad-symbol boundaries before Studio becomes a secondary semantic proof layer.

Latest Sample B2B matrix result:

```text
case_count: 16
trusted_studio_layer: true
declaration_pass_count: 15
usage_pass_count: 16
assertions: pass=18, warn=2, fail=0
```

The warning is the expected generated `BuildConfig` boundary, not a Studio command failure.

## Generated Source Mapping

To prove generated-source mapping separately from semantic navigation, run:

```bash
python3 scripts/benchmarks/android/generated_semantic_mapping.py \
  --validate --run \
  --repo sample_b2b=/path/to/sample-repos/sample-b2b-android-app \
  --run-build-proofs \
  --enforce-assertions
```

Latest Sample B2B generated-source result:

```text
case_count: 5
mapping_pass_count: 5
semantic_pass_count: 2
assertions: pass=14, warn=3, fail=0
```

Apollo generated query/mutation flows are Studio-semantic-proven and build-proven. Room, Moshi KSP, and BuildConfig are build-proven generated boundaries, not semantic navigation successes.

## High-Fanout Budgets

High-fanout summaries use a shared output budget helper:

```text
scripts/benchmarks/shared/output_budget.py
```

Latest Sample B2B high-fanout result:

```text
assertions: pass=10, warn=8, fail=0
UseCase:     262 files / 1813 matches / budget warn
ViewModel:   101 files / 330 matches / budget pass
Repository:  175 files / 676 matches / budget warn
Mapper:       16 files / 30 matches / budget pass
Service:     156 files / 1447 matches / budget warn
Module:       40 files / 93 matches / budget pass
```

## Serena And Project Model Readiness

For an Android/Kotlin project, create a Serena project with Kotlin and JSON language servers:

```bash
cd /path/to/android-repo

serena project create \
  --language kotlin \
  --language json

serena project health-check .
```

Start with Kotlin and JSON. Include `--language java` only when Java semantic proof is needed and Gradle/Android Studio sync is known healthy.

Or use the wrapper:

```bash
./scripts/setup/create-android-serena-project.sh \
  --target-repo /path/to/android-repo
```

For Android, prove one real `.kt` source declaration before running full Serena indexing. Generic health checks can accidentally target `build.gradle.kts`, which may return no symbols even when Kotlin LSP is working.

Also verify the Android project model before blaming the semantic layer:

```bash
bash scripts/setup/check-android-prereqs.sh \
  --target-repo /path/to/android-repo
```

This reports missing required `local.properties` keys by name only. It does not print or create secret values. If Gradle sync cannot configure the app, Android Studio, Serena JetBrains, and Kotlin LSP may be diagnostic-ready but not reference-proof-ready.

The same gate also reports installed Android Studio apps, whether Android Studio Preview/Quail is running, and whether `android studio check` sees the exact target repo as open. Treat this as readiness evidence only; run a declaration/usages smoke test before using Android Studio CLI as symbol proof.

## Process State

If Android LSP behavior looks stale, inspect duplicate Serena/LSP sessions without killing anything:

```bash
bash scripts/setup/repair-serena-android-sessions.sh --dry-run
```

Only after intentionally reconnecting active agents, stop stale sessions explicitly:

```bash
bash scripts/setup/repair-serena-android-sessions.sh --kill
```

After cleanup, prove the session state is clean:

```bash
python3 scripts/benchmarks/android/process_state_probe.py \
  --validate --run \
  --target-project-path /path/to/sample-repos/sample-b2b-android-app \
  --require-clean \
  --enforce-assertions \
  --output results/android/process-state
```

The strict process gate is project-aware: it separates target-project Serena MCP sessions from other-project sessions, unknown ownership, and controlled streamable-HTTP server mode. Use `--allow-other-project-serena` only when other active Serena/Codex sessions are intentional.

To make that distinction count as an explicit readiness acceptance instead of an implicit shortcut, record a project-aware scope acceptance artifact:

```bash
python3 scripts/benchmarks/android/process_scope_acceptance.py \
  --accept-project-aware-strictness \
  --accepted-by "<name-or-role>" \
  --reason "Other Serena sessions are intentionally active for unrelated projects; target-project ownership is clean."
```

Without `--accept-project-aware-strictness`, this script writes a template-only artifact and does not satisfy the readiness clean-process gate.

Android Studio / Quail can add an IDE-backed semantic layer:

```bash
android studio check
android studio analyze-file --project <project-name> <real-source-file.kt>
```

Do not assume `android studio find-declaration` or `find-usages` are reliable until they pass a source-symbol smoke test on the current repo. See [`studio-symbol-matrix.md`](studio-symbol-matrix.md).

To diagnose why Android semantic lookup is unavailable, run:

```bash
python3 scripts/benchmarks/android/project_model_probe.py \
  --validate --run \
  --cases benchmarks/android/project-model-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/project-model
```

The probe reports missing project-model prerequisites without printing secret values.

To generate only a combined Android benchmark report from the latest artifacts:

```bash
python3 scripts/benchmarks/android/generate_report.py \
  --results-root results/android \
  --output results/android/android-benchmark-report-$(date +%F).md
```
