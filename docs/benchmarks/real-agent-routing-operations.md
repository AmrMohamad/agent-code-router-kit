# Real-Agent Routing Benchmark Operations

This page contains the real-agent benchmark operating manual that previously made the root README too long. It covers dry runs, live runs, adapter probes, missing-run planning, reporting, strict audits, and rejudging captured artifacts.

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

## Router Effect V1 Study Mode

Use `router-effect-v1` when the goal is a controlled Codex study rather than a
smoke run. The study treats A/B/C/D as a hermetic `2x2` design:

- semantic access off/on;
- routing and summary discipline off/on.

The runner enforces the study controls when `--study-plan` is present:

- A/B/C/D arm coverage;
- at least four repeats;
- balanced Latin-square order;
- clean detached snapshots;
- fresh controlled Codex home per run;
- isolated semantic-session configuration for C/D;
- captured tool versions;
- external task oracle artifacts;
- model and reasoning-effort metadata.

Example dry-run control check:

```bash
export RARB_PRIVATE_HMAC_KEY="$(openssl rand -hex 32)"

python3 scripts/benchmarks/run_real_agent_benchmark.py \
  --dry-run \
  --agent codex \
  --repo /path/to/clean/ios-reference \
  --repo-map ios_reference=/path/to/clean/ios-reference,web_reference=/path/to/clean/web-reference,portable_reference=/path/to/clean/portable-reference \
  --tasks benchmarks/real-agent-routing/studies/router-effect-v1/pilot-tasks.tsv \
  --task-oracles benchmarks/real-agent-routing/studies/router-effect-v1/task-oracles.json \
  --study-plan benchmarks/real-agent-routing/studies/router-effect-v1/study.yaml \
  --arms A-search-only,B-search-summary,C-lsp-naive,D-full-router \
  --repeats 4 \
  --snapshot-repos \
  --model-id '<exact-model-id>' \
  --reasoning-effort '<fixed-effort>' \
  --out results/real-agent-routing/router-effect-v1-dry-run
```

Audit the resulting package:

```bash
python3 scripts/benchmarks/audit_real_agent_study.py \
  --root results/real-agent-routing/router-effect-v1-dry-run \
  --out results/real-agent-routing/router-effect-v1-dry-run/study-audit.json
```

Analyze token/context effects:

```bash
python3 scripts/benchmarks/analyze_real_agent_study.py \
  --root results/real-agent-routing/router-effect-v1-dry-run \
  --metric exact_uncached_input_tokens \
  --out results/real-agent-routing/router-effect-v1-dry-run/study-analysis.json
```

Pass `--pricing pricing.json` only when the model identifier and per-1M token
prices are explicit. Cost estimates are reported separately from context
efficiency and are not inferred from uncached tokens alone.

Build a public bundle only after verifying that private paths, prompts, source
snippets, symbols, and transcripts are excluded:

```bash
python3 scripts/benchmarks/build_public_study_evidence.py \
  --root results/real-agent-routing/router-effect-v1-dry-run \
  --out benchmarks/real-agent-routing/evidence/router-effect-v1-sanitized
```

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

See [`docs/concepts/proof-boundaries.md`](../concepts/proof-boundaries.md).
