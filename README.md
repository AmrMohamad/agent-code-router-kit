# agent-code-router-kit

A public toolkit for teaching AI coding agents how to route Swift/iOS and Android/Kotlin codebase work to the right evidence layer.

The core idea is simple: an agent should not treat text search as code understanding. It should classify the task, choose the right tool, and keep semantic, structural, discovery, and runtime evidence separate.

## Problem

AI coding agents often start with broad search, read too many files, and infer relationships from matching text. That works for literal strings, but it is weak for Swift code identity:

- a class name can appear in comments, strings, generated files, or unrelated namespaces;
- protocols, conformances, overloads, and extension namespaces are semantic relationships, not just text;
- high-fanout names like `Resolver`, `Router`, `Service`, `Manager`, and `ViewModel` can flood the model context;
- XIB, storyboard, localization, generated, and resource surfaces are not fully represented by Swift symbol graphs;
- successful symbol lookup does not prove the app builds or runs.

## Solution

Route each task to the evidence layer that can actually prove it.

<p align="center">
  <img src="docs/assets/lsp-guided-code-navigation.png" alt="Before vs After: LSP-guided code navigation" width="100%">
</p>

The image above summarizes the core workflow change: broad text search is no
longer treated as semantic proof. The agent classifies the task, uses
SourceKit-LSP or Serena for Swift symbol identity, uses grouped summaries for
high-fanout symbols, keeps `rg` / `fd` for literal and resource discovery, uses
`ast-grep` for syntax-shaped patterns, and leaves build/runtime proof to the
project's build or Xcode/plugin layer.

| Task | First tool | Why |
|---|---|---|
| Known Swift symbol | SourceKit-LSP / Serena | Proves semantic identity, definitions, references, protocols, overloads, extension namespaces, and diagnostics |
| Known Kotlin/Java symbol | Serena / Kotlin or Java LSP | Proves semantic identity, definitions, references, implementations, packages, and diagnostics |
| High-fanout Swift symbol | LSP grouped counts first | Keeps semantic correctness without dumping every reference into context |
| Literal/resource lookup | `rg` / `fd` | Best for strings, logs, route keys, file discovery, localization, resources, and generated surfaces |
| GraphQL query/schema work | GraphQL tools + `rg` / `fd` | Serena does not provide native GraphQL LSP routing; generated Kotlin/Swift can be handled semantically after discovery |
| Structural Swift/Kotlin pattern | `ast-grep` | Matches syntax-shaped patterns and migration candidates more safely than regex |
| Build/runtime truth | Xcode, Android Studio, Gradle, plugin, CI, or build system | Proves compile, test, simulator/emulator, UI, and runtime behavior |

## Quick Start

Clone the toolkit, then make sure the minimum same-results dependency gate
passes. That gate verifies the portable baseline needed before another agent
should expect the same routing behavior:

```text
1. Xcode with SourceKit-LSP
2. xcode-build-server
3. Serena or an equivalent agent-facing LSP access layer
4. rg / fd / ast-grep
```

If any of those are missing, the agent can still read the policy, but it should
not claim the same Swift/iOS LSP-guided behavior or benchmark conclusions yet.

```bash
git clone <your-fork-or-copy>
cd agent-code-router-kit

bash scripts/setup/check-swift-ios-prereqs.sh
bash scripts/setup/check-android-prereqs.sh
python3 scripts/benchmarks/shared/benchmark_runner.py --validate \
  --cases benchmarks/ios/cases.example.tsv
python3 scripts/benchmarks/shared/benchmark_runner.py --validate \
  --cases benchmarks/android/cases.sample.tsv
python3 scripts/benchmarks/android/studio_semantic_probe.py --validate \
  --cases benchmarks/android/studio-semantic-cases.sample.tsv
python3 scripts/benchmarks/android/serena_source_symbol_probe.py --validate \
  --cases benchmarks/android/serena-source-symbol-cases.sample.tsv
python3 scripts/benchmarks/android/serena_project_server_probe.py --validate \
  --cases benchmarks/android/serena-project-server-cases.sample.tsv
python3 scripts/benchmarks/android/process_state_probe.py --validate
python3 scripts/benchmarks/android/project_model_probe.py --validate \
  --cases benchmarks/android/project-model-cases.sample.tsv
python3 scripts/benchmarks/run_real_agent_benchmark.py \
  --dry-run \
  --agent codex \
  --repo "$PWD" \
  --tasks benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv \
  --arms A-search-only,D-full-router \
  --task-limit 2 \
  --repeats 1 \
  --out /tmp/agent-code-router-kit-rarb
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/benchmarks/shared/check_public_sanitization.py
```

For a full Android/Kotlin routing benchmark over two Android repos, use the
suite runner:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

This runs default `rg` / `fd` / `ast-grep` measurements, Android Studio
semantic probes, Serena/Kotlin LSP source-symbol probes, Serena ProjectServer
semantic probes, process-state checks, project-model readiness checks, and report generation. The
project-model check is preflight-only unless `--run-gradle-project-model` is
passed.

For a strict Android regression run after intentionally cleaning stale
Serena/LSP processes:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --require-clean-process-state \
  --enforce-assertions \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

For the Sample B2B-first Android operational hardening gate, use the real open
Android Studio/emulator setup:

```bash
python3 scripts/benchmarks/android/operational_gate.py \
  --sample-b2b-repo /path/to/sample-repos/sample-b2b-android-app \
  --device emulator-5554 \
  --variant stagingDebug \
  --enforce-assertions
```

This stable gate checks Android Studio declaration/usages recovery,
Serena/Kotlin semantic proof, generated-source readiness, high-fanout summary
discipline, Gradle 8.13 project-model/build proof, APK install, and package
launch smoke on Sample B2B as a testbed. Sample Retail now has a separate stable operational
follow-up gate against its Gradle 9 project model.

To expand the Android Studio proof beyond one smoke symbol, run the stable Studio
symbol matrix:

```bash
python3 scripts/benchmarks/android/studio_symbol_matrix.py \
  --validate --run \
  --repo sample_b2b=/path/to/sample-repos/sample-b2b-android-app \
  --enforce-assertions
```

This matrix requires expected declaration and usage files across ViewModels,
methods, DI properties, services, network code, request builders, and
generated/broad-symbol boundaries before Studio becomes a secondary semantic
proof layer.

Latest Sample B2B matrix result:

```text
case_count: 16
trusted_studio_layer: true
declaration_pass_count: 15
usage_pass_count: 16
assertions: pass=18, warn=2, fail=0
```

The warning is the expected generated `BuildConfig` boundary, not a Studio
command failure.

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

Apollo generated query/mutation flows are Studio-semantic-proven and
build-proven. Room, Moshi KSP, and BuildConfig are build-proven generated
boundaries, not semantic navigation successes.

High-fanout summaries now use a shared output budget helper:

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

For an Xcode project, create a machine-local `buildServer.json`:

```bash
./scripts/setup/create-build-server-json.sh \
  --project YourApp.xcodeproj \
  --scheme "Your Scheme"
```

or:

```bash
./scripts/setup/create-build-server-json.sh \
  --workspace YourApp.xcworkspace \
  --scheme "Your Scheme"
```

For an Android/Kotlin project, create a Serena project with Kotlin and JSON language servers:

```bash
cd /path/to/android-repo

serena project create \
  --language kotlin \
  --language json

serena project health-check .
```

Start with Kotlin and JSON. Include `--language java` only when Java semantic
proof is needed and Gradle/Android Studio sync is known healthy.

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

This reports missing required `local.properties` keys by name only. It does not
print or create secret values. If Gradle sync cannot configure the app, Android
Studio, Serena JetBrains, and Kotlin LSP may be diagnostic-ready but not
reference-proof-ready.

The same gate also reports installed Android Studio apps, whether Android
Studio Preview/Quail is running, and whether `android studio check` sees the
exact target repo as open. Treat this as readiness evidence only; run a
declaration/usages smoke test before using Android Studio CLI as symbol proof.

If Android LSP behavior looks stale, inspect duplicate Serena/LSP sessions
without killing anything:

```bash
bash scripts/setup/repair-serena-android-sessions.sh --dry-run
```

Only after intentionally reconnecting active agents, stop stale sessions
explicitly:

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

The strict process gate is project-aware: it separates target-project Serena
MCP sessions from other-project sessions, unknown ownership, and controlled
streamable-HTTP server mode. Use `--allow-other-project-serena` only when other
active Serena/Codex sessions are intentional. Latest Sample B2B snapshot:
target-owned Serena MCP sessions were `0`, other-project Serena sessions were
`4`, unknown sessions were `0`; the normal project-aware probe warned, while
the explicit `--allow-other-project-serena --require-clean` run passed with
6 pass / 0 warn / 0 fail. That proves project-aware strict behavior, not a
clean-room shutdown of every active Serena session.

To make that distinction count as an explicit readiness acceptance instead of an
implicit shortcut, record a project-aware scope acceptance artifact:

```bash
python3 scripts/benchmarks/android/process_scope_acceptance.py \
  --accept-project-aware-strictness \
  --accepted-by "<name-or-role>" \
  --reason "Other Serena sessions are intentionally active for unrelated projects; target-project ownership is clean."
```

Without `--accept-project-aware-strictness`, this script writes a template-only
artifact and does not satisfy the readiness clean-process gate.

Android Studio / Quail can add an IDE-backed semantic layer:

```bash
android studio check
android studio analyze-file --project <project-name> <real-source-file.kt>
```

Do not assume `android studio find-declaration` or `find-usages` are reliable
until they pass a source-symbol smoke test on the current repo. See
`docs/android/studio-symbol-matrix.md`.

To diagnose why Android semantic lookup is unavailable, run:

```bash
python3 scripts/benchmarks/android/project_model_probe.py \
  --validate --run \
  --cases benchmarks/android/project-model-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/project-model
```

The probe reports missing project-model prerequisites without printing secret
values.

To generate only a combined Android benchmark report from the latest artifacts:

```bash
python3 scripts/benchmarks/android/generate_report.py \
  --results-root results/android \
  --output results/android/android-benchmark-report-$(date +%F).md
```

## Install The Policy In An Agent

Use these templates:

- `templates/AGENTS.md` for project instructions.
- `templates/codebase-tool-router/SKILL.md` for Codex-style skill routing.
- `templates/android-codebase-tool-router/SKILL.md` for Android/Kotlin-specific routing.
- `templates/codex/` for Codex setup notes.
- `templates/cursor/` for Cursor rules.
- `templates/claude/` for Claude-style instructions.

For a guided install that is read-only by default:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/ios-repo \
  --agent codex \
  --profile swift-ios \
  --dry-run
```

For Android:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/android-repo \
  --agent codex \
  --profile android \
  --dry-run
```

See `docs/agents/agent-self-install.md`.

Minimal prompt:

```text
Use the codebase tool router.

Classify the task before searching:
- known Swift symbol -> SourceKit-LSP / Serena
- known Kotlin/Java symbol -> Serena / Kotlin or Java LSP
- high-fanout symbol -> LSP grouped counts first
- literal/resource -> rg/fd
- structural Swift/Kotlin pattern -> ast-grep
- build/runtime proof -> Xcode/plugin/build system
- Android build/runtime proof -> Gradle/Android Studio/emulator/CI
- GraphQL -> GraphQL tools + rg/fd first, then LSP for generated source

Do not dump high-fanout references.
Do not claim runtime proof from LSP or search.
```

## Benchmark Layout

The benchmark package is now stable and versionless. Files are grouped by platform and by shared infrastructure:

```text
benchmarks/android/             Android TSV manifests and Android benchmark README
benchmarks/ios/                 Swift/iOS TSV manifest, fixture, and sample results
scripts/benchmarks/android/     Android probes and operational gates
scripts/benchmarks/ios/         iOS entrypoint wrapper
scripts/benchmarks/shared/      generic TSV runner, sanitization, and output budget helpers
tests/android/                  Android benchmark tests
tests/ios/                      iOS benchmark tests
tests/shared/                   shared runner and setup tests
benchmarks/real-agent-routing/  Real-agent routing benchmark tasks, profiles, contracts, and adapter configs
scripts/agents/                 dry-run-capable subject-agent adapters and terminal bridge
scripts/lib/                    token proxy, transcript parsing, and run schema helpers
```

The public interface is organized by capability, not by historical milestone name:

- routing benchmark
- operational gate
- reference triage
- Studio symbol matrix
- generated-source mapping
- transport and lifecycle probes
- readiness audit
- high-fanout output budget
- real-agent routing benchmark

## Real-Agent Routing Benchmark

The real-agent benchmark is the next proof layer beyond tool benchmarks. It
generates task packets for subject agents and compares routing profiles such as
`A-search-only` and `D-full-router` by model-visible bytes, token source,
observed tool evidence, raw-dump incidents, policy adherence, and judge output.

The default console output is optimized for Codex TUI reading: short `Ran`,
`Updated Plan`, and `Evidence` sections. Use `--json` when a caller needs the
full machine-readable result on stdout.

Dry-run mode validates the harness without launching a real agent:

```bash
python3 scripts/benchmarks/run_real_agent_benchmark.py \
  --dry-run \
  --agent codex \
  --repo "$PWD" \
  --tasks benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv \
  --arms A-search-only,D-full-router \
  --task-limit 3 \
  --repeats 1 \
  --out /tmp/agent-code-router-kit-rarb
```

Live subject-agent runs are intentionally explicit. A live run validates the
adapter command, route profile, repo state, timeout, sentinel, and permission
boundary for the target machine.

Probe adapters before a benchmark run:

```bash
python3 scripts/benchmarks/probe_live_agent_adapters.py \
  --agents codex,claude-code,cursor-agent \
  --repo "$PWD" \
  --out /tmp/agent-code-router-kit-live-adapter-probe
```

For a blocker-oriented diagnosis, use the adapter doctor:

```bash
python3 scripts/benchmarks/doctor_live_agent_adapters.py \
  --agents codex,claude-code,cursor-agent \
  --repo "$PWD" \
  --out /tmp/agent-code-router-kit-live-adapter-doctor
```

It writes `adapter-doctor-summary.json` with command resolution, probe status,
search-only route-isolation controls, sanitized CLI diagnostics, token telemetry
readiness, failure reason, and next action per subject agent. A launch probe can
pass while readiness still fails if the adapter has weak route-isolation
controls. A launch probe can also pass with `token_telemetry_ready=false`; that
agent may be usable for harness smoke checks, but not for real-token benchmark
claims until exact or agent-reported token telemetry includes usable total-token
fields.

Live mode is explicit:

```bash
python3 scripts/benchmarks/run_real_agent_benchmark.py \
  --live \
  --agents codex,claude-code,cursor-agent \
  --repo /path/to/clean/android-repo \
  --repo-map sample_b2b_android=/path/to/clean/android-repo \
  --tasks benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv \
  --arms A-search-only,D-full-router \
  --task-limit 1 \
  --repeats 1 \
  --snapshot-repos \
  --out results/real-agent-routing/live-pilot
```

Every non-empty `repo` value in a live task TSV must have an explicit
`--repo-map repo_id=/absolute/path` entry. The runner rejects missing named
mappings instead of silently falling back to `--repo`; otherwise a multi-repo
matrix can record a task under the wrong repository.

If a live pilot already has valid rows for one agent, do not rerun those cells
just to fill a larger matrix. Plan the missing cells first:

```bash
python3 scripts/benchmarks/plan_missing_real_agent_runs.py \
  --benchmark-out results/real-agent-routing/live-pilot \
  --adapter-probe /tmp/agent-code-router-kit-live-adapter-doctor \
  --agents codex,claude-code,cursor-agent \
  --profiles A-search-only,D-full-router \
  --out-markdown results/real-agent-routing/live-pilot/missing-run-plan.md
```

When the planner reports a subject agent as runnable, use the emitted
`resume_commands[].argv`. The runner will carry forward prior `runs.jsonl`
rows into a new output directory and execute only missing
`agent/profile/task/repo/repeat` cells via `--resume-from`. Planner rows also
carry `token_source`, `token_telemetry_ready`, and
`token_telemetry_next_action` from adapter doctor/probe output, so a runnable
agent is not confused with an agent ready for exact-token benchmark claims.
Carried rows import their run directories into the new output root and rewrite
`run_dir`, so the resumed package is self-contained. If a carried row's evidence
directory or required files are missing, the runner plans that cell again and
records it in `missing_artifact_carried_forward_runs`.
Use `execution_plan.status` and `execution_plan.can_resume_now` as the launch
gate; an all-blocked plan must be fixed at the adapter/auth/model-access/quota
layer before rerunning the benchmark.
Use `--out-markdown` to keep the missing matrix cells, blocked agents, token
readiness, and resume commands as a first-class artifact next to the benchmark
reports.

The runner records per-repo branch/commit/dirty state, seeded run order, route
isolation controls, token source, observed tool events, tool-output bytes,
policy violations, and dry-run contract status. Dry-run results prove harness
behavior only; they do not prove correctness or savings.
With `--monitor`, the runner also prints live lifecycle events from the
terminal bridge while the subject agent is running, including prompt delivery,
process or tmux session state, observed output/capture growth, sentinel
observation, post-sentinel capture completion for trailing usage events,
timeout, and exit/close events. Use `--stream-agent-output` only when you also
want the raw subject-agent transcript echoed to the terminal.

For Cursor Agent search-only runs, route isolation is hard only when the launch
plan avoids `--approve-mcps` and the runner observes `agent mcp list` in the
target workspace with no loaded MCP servers. Otherwise the row carries weak
route controls and the strict readiness audit blocks publication.

Reports include `route-comparisons.json`, which compares paired runs for the
same agent, task, repo, and repeat across `A-search-only` and `D-full-router`.
Use those paired exact-token, agent-reported-token, proxy-token, and wall-time
deltas for routing claims; profile medians alone are not enough to prove
with-router versus without-router behavior. Exact cached-input and
reasoning-output token fields are preserved separately when the subject agent
exposes them. If a missing-run plan exists, pass it to
`build_real_agent_report.py --missing-plan`; the report will write
`matrix-completion-summary.json` and place the incomplete-matrix boundary at the
top of `token-savings-report.md`.
Reports also write `proof-layer-summary.json`, grouped by profile, agent, and
task family, so missing or stale `expected_proof_layer_seen` fields are visible
without inspecting every row.
`route-isolation-summary.json` similarly groups isolation modes, hard controls,
and weak controls so prompt-only or weakly isolated rows are visible in the
report layer.
Reports also include `route-claim-readiness.json`, which gates savings claims
separately from measurement coverage. A paired route comparison can prove that
the benchmark measured both arms while still blocking an exact-token savings
claim when exact tokens increased, token sources differ, or correctness is not
pass/pass.
Rows that stop with `completion_reason=output_budget_exceeded` are controlled
benchmark failures. They are valid live outcomes for execution coverage and
failure-rate reporting, but they are not correctness passes and cannot support
route-savings claims.

Use `--snapshot-repos` when source repos have unrelated local edits. It creates
clean detached git worktrees under the benchmark output directory, runs agents
against those snapshots, and records both source and snapshot repo states in the
manifest.

Gate any real benchmark claim with the readiness audit. For execution-readiness
claims where controlled failures are expected data, use
`--allow-controlled-failures` and omit `--require-all-pass`. For pass/pass
savings claims over the full matrix, keep `--require-all-pass` enabled and add
`--require-supported-savings-claim exact`, `exact_uncached`, `agent_reported`, `proxy`, or `any`. For a scoped
savings claim, add `--min-supported-savings-pairs N` and state the claim as
supported for only those N pass/pass pairs; unsupported pairs and controlled
failures still remain in the report.
With
`--require-all-adapters`, adapter doctor/probe rows must pass and must not mark
the adapter as not ready for live benchmark use or expose weak route-isolation
controls:

```bash
python3 scripts/benchmarks/audit_real_agent_benchmark_readiness.py \
  --benchmark-out results/real-agent-routing/live-pilot \
  --adapter-probe /tmp/agent-code-router-kit-live-adapter-probe \
  --agents codex,claude-code,cursor-agent \
  --profiles A-search-only,D-full-router \
  --require-live \
  --require-clean-repos \
  --require-all-adapters \
  --require-all-pass \
  --require-observed-tools \
  --require-non-proxy-tokens \
  --require-expected-proof-layer \
  --require-no-weak-route-controls \
  --require-hard-isolation-for-blocked-tools \
  --require-fresh-sessions \
  --require-randomized-order \
  --require-repo-snapshots \
  --require-repo-metadata \
  --require-real-task-manifest \
  --require-self-contained-artifacts \
  --require-balanced-matrix \
  --require-live-lifecycle-telemetry \
  --require-paired-route-comparisons \
  --require-matrix-completion-report \
  --require-terminal-control-summary \
  --require-route-policy-summary \
  --missing-plan results/real-agent-routing/live-pilot/missing-run-plan.json \
  --allow-controlled-failures
```

The audit is intentionally strict. It emits both low-level `issues[]` and
requirement-level `requirements[]` so a failed run maps back to the benchmark
plan instead of becoming a flat error list. A failed adapter probe, dirty repo,
missing agent/profile cell, proxy-only token source, unobserved tool evidence,
or policy violation means the run is not publishable as a clean pass/pass
comparison. If `--allow-controlled-failures` is enabled, recognized controlled
stops such as `output_budget_exceeded` remain valid execution outcomes while
still blocking correctness-preserving savings claims. A missing paired A/D
route comparison also blocks routing-effect claims.
Route-isolation claims compare each `runs.jsonl` row against its
`route-isolation.json` artifact, so stale copied hard/weak-control fields cannot
stand in for the actual launch controls.
Missing `expected_proof_layer_seen` evidence blocks proof-layer claims when
`--require-expected-proof-layer` is enabled.
Missing process/session lifecycle events in per-run `telemetry.jsonl` block
live-monitoring claims when `--require-live-lifecycle-telemetry` is enabled.
Missing fresh-session, randomized-order, snapshot, repo commit metadata,
per-row `repo_path` alignment with `repo_map`, or non-demo task-manifest
evidence blocks run-validity claims when the matching `--require-*` flags are
enabled. `--require-real-task-manifest` rejects `.sample.tsv` and
`.example.tsv` manifests for publishable benchmark claims.
`--require-fresh-sessions` also verifies each run's `telemetry.jsonl` contains a
unique tmux session name or process pid, so the manifest flag alone is not
enough.
Run directories outside the benchmark output, or missing required per-run
evidence files, block packaging claims when `--require-self-contained-artifacts`
is enabled.
Missing same-agent/same-task/same-repeat route cells block balanced comparison
claims when `--require-balanced-matrix` is enabled.
Missing or stale `matrix-completion-summary.json` blocks report-honesty claims
when `--require-matrix-completion-report` is enabled. Pass `--missing-plan` to
compare the report's matrix-completion fields against the planner JSON.
Missing or stale `terminal-control-summary.json` blocks control-plane claims
when `--require-terminal-control-summary` is enabled; it verifies that every
row has prompt-delivery, terminal mode, terminal-capture change, and
process/session close evidence in the report layer, and that those fields still
match each run's `telemetry.jsonl` and `launch-plan.json`.
Missing or stale `route-policy-summary.json` blocks route-policy claims when
`--require-route-policy-summary` is enabled; it verifies that report-level
blocked-tool and checkable required-first-tool violations are zero and that
per-run route-policy flags still match `runs.jsonl`.
When publishing a savings claim, add `--require-all-pass` and
`--require-supported-savings-claim exact`, `exact_uncached`, `agent_reported`, `proxy`, or `any` for a full-matrix
claim. Use `--min-supported-savings-pairs N` only when the claim is explicitly
scoped to at least N supported pairs. Use `exact` for a real-token savings
claim; use `exact_uncached` when exact totals include cached input and the
claim is explicitly cache-adjusted; use `agent_reported` when a subject CLI
prints totals but not exact structured usage; use `proxy` only when the claim is
explicitly about model-visible proxy tokens.

If parser, telemetry, or judge logic changes after a live run, refresh artifacts
from the captured transcripts before auditing:

```bash
python3 scripts/benchmarks/rejudge_real_agent_benchmark.py \
  --benchmark-out results/real-agent-routing/live-pilot \
  --write \
  --replace-runs
```

`rejudge_real_agent_benchmark.py` reads the task TSV path from
`run-manifest.json` when available. Pass `--tasks` only for older artifacts or
when intentionally overriding the recorded task manifest.

## Benchmark Summary

The benchmark package is sanitized and public-safe. It captures routing conclusions without private project names, raw private output, credentials, or organization-specific paths.

Swift/iOS fixture results demonstrate that broad raw search can flood context, while grouped file/count summaries keep high-fanout work bounded. Android/Kotlin results demonstrate the same routing principle under Android-specific constraints: Gradle project model, generated sources, Android Studio indexing, emulator/runtime proof, and Serena/Kotlin LSP process lifecycle must stay separate proof layers.

Core routing rule:

```text
Known Swift symbol       -> SourceKit-LSP / Serena first
Known Kotlin/Java symbol -> Serena / Kotlin or Java LSP first, after readiness smoke
High-fanout symbol       -> grouped summaries/counts first
Literal/resource         -> rg/fd first
GraphQL/generated        -> GraphQL/discovery/build mapping first, then semantic symbol proof if concrete
Structural pattern       -> ast-grep first
Build/runtime truth      -> Xcode, Android Studio, Gradle, emulator/device, CI, or plugin proof
```

Android operational gates are intentionally conservative. A passing build/install/launch smoke proves only build/runtime smoke, not business-flow correctness. Empty Serena references are treated as a named semantic disagreement when Android Studio usages returns real locations; the policy then records which layer is trusted for that pattern instead of silently accepting either result.

## Proof Boundaries

This toolkit does not claim that:

- LSP proves runtime behavior;
- `rg` proves all real symbol references;
- `ast-grep` proves types;
- Xcode/Android Studio/Gradle/build output replaces semantic navigation;
- generated files, XIB/storyboard, localization, and resource behavior are fully semantic;
- future agent behavior will always follow the policy without instruction.

See `docs/concepts/proof-boundaries.md`.

## Documentation

- `docs/concepts/tool-routing-model.md`
- `docs/concepts/lsp-vs-search.md`
- `docs/concepts/high-fanout-symbols.md`
- `docs/concepts/proof-boundaries.md`
- `docs/swift-ios/sourcekit-lsp-setup.md`
- `docs/swift-ios/xcode-build-server.md`
- `docs/swift-ios/serena-sourcekit-lsp.md`
- `docs/swift-ios/xcode-plugin-proof-layer.md`
- `docs/android/kotlin-serena-lsp-setup.md`
- `docs/android/android-routing-policy.md`
- `docs/android/operational-gates.md`
- `docs/android/reference-triage.md`
- `docs/android/studio-symbol-matrix.md`
- `docs/android/readiness-audit.md`
- `docs/android/operational-completion.md`
- `docs/android/sample-retail-follow-up.md`
- `docs/android/android-benchmark-results-2026-05-24.md`
- `docs/agents/generic-agent-policy.md`
- `docs/agents/agent-self-install.md`
- `docs/benchmarks/methodology.md`
- `docs/benchmarks/interpreting-results.md`
- `docs/benchmarks/proven-boundaries.md`
- `docs/benchmarks/history.md`

## Public Safety

Do not publish raw benchmark output from private repositories without sanitizing paths, names, source snippets, credentials, and organization-specific details.
