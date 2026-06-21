# Real Agent Routing Benchmark

RARB measures real AI-agent token/context consumption under routing policies. It runs the same preregistered tasks through subject agent adapters and compares controlled routing profiles across semantic-access and routing-discipline factors.

This package is dry-run safe by default. Dry-run writes task packets, transcripts, telemetry, normalized metrics, judge results, and reports without launching a real agent.

The CLI prints a Codex TUI-friendly summary by default so local runs are easy to
scan in terminal scrollback. Add `--json` for machine-readable stdout.
Add `--monitor` to print one progress line per run while also writing
`monitor.jsonl`.
For live debugging in a visible terminal, add `--stream-agent-output` so the
subject Codex/agent stdout is displayed while still being captured. Use
`--terminal-mode tmux` when a persistent terminal session/pane transcript is
needed for adapter debugging.
Use `--terminal-mode codex-tui` for Codex-only visible TUI debugging. That mode
opens the real interactive Codex UI in a tmux-backed Terminal session with
`--no-alt-screen`, starts the run with the task packet as the initial Codex
prompt argument, captures the visible transcript as
`visible-terminal-transcript.txt`, and keeps `transcript.txt` parseable by using
only the final benchmark contract block. Search-only hard isolation is intentionally not claimed
for `codex-tui`; use the default `codex exec --json` path for strict
search-only isolation and token telemetry. Because interactive Codex can start
Serena/MCP servers from the user's config, `codex-tui` snapshots Serena-related
processes before the run and terminates only new Serena/LSP PIDs it spawned
after the run. The per-run `codex-tui-process-cleanup.json` records before,
after, spawned, and terminated PIDs.
Source-symbol tasks are dynamic by default: the runner samples a real Kotlin or
Java declaration from the mapped target repo, rewrites the prompt around that
symbol, and records the selected target. The run manifest records the random
seed. Pass `--seed <n>` to reproduce the same sampled symbols and run order, or
`--static-code-prompts` to use task TSV prompts exactly as written.

## Profiles

| Profile | Purpose |
|---|---|
| `A-search-only` | Search and infer with `rg`, `fd`, basic file reads, and allowed build tools only when required. |
| `B-search-summary` | Search-only plus grouped summaries and strict output budgets. |
| `C-lsp-naive` | Semantic tools available but without strict high-fanout discipline. |
| `D-full-router` | Full router: semantic proof, discovery tools, structural tools, runtime proof, and high-fanout summary-first rules. |

## Dry Run

```bash
python3 scripts/benchmarks/run_real_agent_benchmark.py \
  --dry-run \
  --agent codex \
  --repo /path/to/sample-android-repo \
  --tasks benchmarks/real-agent-routing/tasks/android-realworld.example.tsv \
  --arms A-search-only,D-full-router \
  --task-limit 3 \
  --repeats 1 \
  --out results/real-agent-routing/dry-run
```

## Router Effect V1 Confirmatory Study

The `router-effect-v1` protocol is the stricter scientific path beyond the
current A/D smoke bundle. It treats A/B/C/D as a `2x2` factorial design:

| Arm | Semantic access | Routing discipline |
|---|---:|---:|
| `A-search-only` | off | off |
| `B-search-summary` | off | on |
| `C-lsp-naive` | on | off |
| `D-full-router` | on | on |

Study mode requires clean detached snapshots, a fresh controlled Codex home per
run, isolated semantic-session configuration for semantic arms, captured tool
versions, external task oracles, and balanced Latin-square ordering. It writes
per-run `effective-agent-config.json`, `effective-agent-config.sha256`,
`treatment-diff.json`, `semantic-session.json`, and `oracle.json` artifacts.
Semantic C/D runs use per-run Codex MCP stdio sessions with isolated Serena and
XDG homes under the run directory; A/B rows record semantic access as disabled.
The run manifest also
pins the study package with hashes for the study plan, protocol, analysis plan,
oracle file, and task manifest; private task/oracle inputs are additionally
fingerprinted with keyed HMACs for safe public evidence.

Dry-run the study controls before any live execution:

```bash
export RARB_PRIVATE_HMAC_KEY="$(openssl rand -hex 32)"

python3 scripts/benchmarks/run_real_agent_benchmark.py \
  --dry-run \
  --agent codex \
  --repo /path/to/clean/ios-reference \
  --repo-map ios_reference=/path/to/clean/ios-reference,web_reference=/path/to/clean/web-reference \
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

Audit a completed study output with:

```bash
python3 scripts/benchmarks/audit_real_agent_study.py \
  --root results/real-agent-routing/router-effect-v1-dry-run \
  --out results/real-agent-routing/router-effect-v1-dry-run/study-audit.json
```

Before a live confirmatory run, validate that each frozen task has a
task-specific oracle contract:

```bash
python3 scripts/benchmarks/verify_task_oracles.py \
  --tasks benchmarks/real-agent-routing/studies/router-effect-v1/confirmatory-tasks.tsv \
  --oracles benchmarks/real-agent-routing/studies/router-effect-v1/task-oracles.json \
  --require-task-specific
```

The stricter `--confirmatory` audit is intentionally reserved for live runs
using the frozen `confirmatory-tasks.tsv` and the study-plan oracle file. It
rejects dry-runs, custom task manifests, custom oracle files, missing
analysis/power artifacts, non-primary metric analysis, and row hashes that do
not match the frozen package. It also rejects weak oracle plans that rely only
on family-level fallbacks.

The study protocol is intentionally public-safe: repository labels are generic,
and public evidence must omit private names, paths, prompts, symbols, snippets,
and transcripts.

## Outputs

Each run directory contains:

```text
task-packet.md
route-isolation.json
transcript.txt
telemetry.jsonl
metrics.normalized.json
judge.json
agent_final_answer.md
dynamic-task-target.json      # source-symbol tasks only
serena-readiness.json         # live semantic-router source-symbol cells only
effective-agent-config.json   # study/hermetic mode only
effective-agent-config.sha256 # study/hermetic mode only
treatment-diff.json           # study/hermetic mode only
semantic-session.json         # study mode only
oracle.json                   # study/oracle mode only
visible-terminal-transcript.txt # codex-tui mode only
codex-tui-process-cleanup.json # codex-tui mode only
```

The top-level output directory contains:

```text
run-manifest.json
monitor.jsonl
runs.jsonl
metrics-summary.json
policy-violations.json
correctness-summary.json
route-comparisons.json
route-claim-readiness.json
token-savings-report.md
codex-tui-summary.md
```

## Live Runs

Live runs are intentionally explicit. Use `--live`; the runner rejects dirty
target repos unless `--allow-dirty` is provided. Prefer `--snapshot-repos` for
benchmark evidence when source repos have unrelated local edits: it creates
clean detached git worktrees under the output directory and records source plus
snapshot repo states. Codex, Claude Code, and Cursor Agent adapters are
configured for non-interactive PTY execution when their CLIs are installed. Use
`--agents codex,claude-code,cursor-agent` for a multi-agent run, and
`--repo-map repo_id=/path` when task rows should execute in different
repositories. Live mode rejects named task repos that do not have an explicit
mapping; falling back to the default `--repo` for named rows would invalidate a
multi-repo comparison.
For live runs, per-run `telemetry.jsonl` records process/session lifecycle
events such as prompt delivery, output byte chunks, process exit, tmux capture
changes, sentinel observation, post-sentinel capture completion for trailing
usage events, and timeout without duplicating raw transcript text.

For full-router Kotlin/Java source-symbol cells, the runner performs a Serena
source-symbol readiness smoke before launching the subject agent. It runs
`serena project index-file` against the sampled declaration file and writes the
result to `serena-readiness.json`. If Serena is not ready, the task packet says
`Ready: false` and instructs the subject agent not to claim semantic proof from
Serena. Stale-session risks such as multiple Serena MCP or Kotlin LSP processes
are recorded as readiness warnings instead of being hidden. Add
`--require-clean-serena-process-state` for benchmark cells where semantic
session contamination must be a hard blocker: under that flag, a full-router
source-symbol run stops before launching the subject agent if readiness reports
multiple Serena MCP, Kotlin LSP, or JSON LSP processes.

For search-only arms, Cursor Agent route isolation is accepted only when the
launch plan does not include `--approve-mcps` and the adapter verifies
`agent mcp list` in the target workspace has no loaded MCP servers. If that
probe fails or finds loaded MCPs, the run is marked with weak route controls and
strict readiness blocks it.

Run `scripts/benchmarks/probe_live_agent_adapters.py` first. A failed probe is
not a benchmark result; it records external readiness such as auth, quota, CLI
flag, timeout, or prompt-delivery failures.

Use `scripts/benchmarks/doctor_live_agent_adapters.py` when probes fail. It
records command resolution, probe status, search-only route-isolation controls,
sanitized CLI diagnostics, token telemetry readiness, failure reason, and next
action for each subject agent so auth/quota/flag, weak-isolation, or proxy-only
token blockers are visible before a full run. `ready_for_live_benchmark=true`
means the adapter can launch under the route controls;
`token_telemetry_ready=true` is the separate gate for exact or agent-reported
token claims with usable total-token fields. For Codex full-router pilots, add
`--require-clean-serena-process-state`; the doctor then records the current
Serena MCP/Kotlin/JSON LSP process counts and blocks readiness if stale
multiple-process state would contaminate a semantic benchmark cell. A
usage-shaped error event without totals is diagnostic evidence only; it is not
real-token readiness. Diagnostic fields intentionally redact emails, UUIDs,
tokens, API keys, and authorization-like values before writing JSON artifacts.

If a pilot has only part of the requested matrix, use
`scripts/benchmarks/plan_missing_real_agent_runs.py` before relaunching agents.
It reads the existing `runs.jsonl`, optional adapter doctor/probe output, and
the manifest task TSV, then lists missing `agent/profile/task/repo/repeat`
cells. Pass `--out-markdown <benchmark-out>/missing-run-plan.md` to keep the
blocked agents, token readiness, resume commands, and exact missing cells next
to the benchmark reports. Ready agents get `resume_commands[].argv`; blocked
agents keep explicit auth, quota, prompt, route-isolation, or token-telemetry
next actions. Resume runs use `run_real_agent_benchmark.py --resume-from` and
write a new output directory so previous rows are carried forward without being
rerun or overwritten. The planner also writes `execution_plan.status` as
`complete`, `runnable`, `blocked`, or `unknown`; do not launch another run
unless `execution_plan.can_resume_now=true` and the emitted `resume_commands[]`
cover the intended agent cells.

`run_real_agent_benchmark.py --monitor` prints live lifecycle events from the
terminal bridge as the agent runs: prompt delivery, process or tmux session
state, observed output/capture growth, sentinel observation, timeout, and
exit/close events. Add `--stream-agent-output` only when the raw subject-agent
transcript should also be echoed.

Dry-run correctness is reported as `dry_run_contract_pass`, not real task
correctness. Live correctness requires the judge to see expected success
signals, observed tool evidence, and route-policy compliance.

## Codex Exact Paired Pilot

Use the Codex pilot wrapper when the immediate goal is the Phase 1 proof:
one same-agent, same-task `A-search-only` versus `D-full-router` Codex run
with exact-token telemetry, observed tools, strict clean-Serena gating, a
claim audit, and a sanitized export.

```bash
python3 scripts/benchmarks/run_codex_exact_paired_pilot.py \
  --repo /path/to/controller-repo \
  --repo-map sample_b2b_android=/path/to/android-repo \
  --tasks benchmarks/real-agent-routing/tasks/android-realworld.local.tsv \
  --out /tmp/rarb-codex-exact-paired-pilot \
  --allow-dirty \
  --snapshot-repos
```

The wrapper writes `pilot-status.json` at every stop point. Its phases are:
`doctor-preflight`, `doctor-probe`, `benchmark`, `audit`, and `export`.
`doctor-preflight` checks clean Serena/Kotlin/JSON LSP process state without
launching Codex; if stale Serena state is present, the pilot stops there with
explicit blockers and no subject-agent run. After a clean preflight it runs the
Codex readiness probe, launches the paired benchmark, applies the
`codex-exact-paired` claim gate, and exports
`sanitized-live-pilot/`.

Use `--no-doctor-probe` for a non-launching host status check. That mode can
prove the current Serena process-state blocker, but it intentionally cannot
prove live Codex readiness or benchmark completion.

When `doctor-preflight` blocks on stale Serena state, inspect the generated
`serena-cleanup-plan.json` or run the standalone dry-run repair command:

```bash
python3 scripts/benchmarks/repair_serena_process_state.py \
  --dry-run \
  --format text \
  --out /tmp/serena-process-repair.json
```

Only after confirming the listed candidates are stale user-safe sessions, rerun
with `--execute`. The repair command records before/after process state and
does not terminate anything unless `--execute` is present. The text table
includes PID, process kind, age, parent, project/cwd guess, safe flag, and kill
reason. Execute mode only terminates candidates marked
`safe_to_terminate=true`; if any unsafe candidates remain, plain `--execute`
refuses partial cleanup. Use `--allow-partial-safe-execute` only when a partial
safe-candidate cleanup is intentional and you understand it will not by itself
make the semantic benchmark state clean. Candidates with safety exclusions
remain review-only unless explicitly handled outside the default repair path.
If the repair status is `blocked_no_safe_candidates`, no default execute command
can help: close the owning Codex/Serena/project sessions or get explicit
approval for a broader process cleanup, then rerun the dry-run table.
When explicit approval is granted, use the generated
`review_only_execute_command` so the cleanup still records before/after state
and the approval token instead of falling back to ad hoc `kill` commands.

## Readiness Audit

Use the audit before making a real benchmark claim:

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
  --require-clean-serena-process-state \
  --require-balanced-matrix \
  --require-live-lifecycle-telemetry \
  --require-paired-route-comparisons \
  --require-matrix-completion-report \
  --require-terminal-control-summary \
  --require-route-policy-summary \
  --missing-plan results/real-agent-routing/live-pilot/missing-run-plan.json
```

The audit writes explicit blockers for missing agents, missing profile cells,
dirty repos, sample/example task manifests, stale row `repo_path` values,
failed probes, proxy-only token rows, unobserved tool evidence, and
policy violations. It also writes `requirements[]`, a requirement-level summary
that maps those blockers back to the original benchmark plan: live execution,
adapter readiness, balanced matrix coverage, correctness/policy/proof evidence,
token measurement, route isolation, run-validity controls, live lifecycle
telemetry, paired A/D comparisons, and optional savings-claim support. It can
also require expected-proof-layer evidence, per-run process/session lifecycle
telemetry, fresh-session proof, randomized order, repo snapshot/commit metadata,
balanced same-agent/same-task/same-repeat route cells, and paired A/D
route-comparison rows for routing claims. A failed audit means the artifacts
remain a harness pilot or adapter diagnosis, not the final real-life benchmark.
Route-isolation checks compare `runs.jsonl` fields with each run's
`route-isolation.json`, so report rows cannot drift away from the actual launch
controls.
Fresh-session proof requires each run's `telemetry.jsonl` to carry a unique tmux
session name or process pid; `fresh_session_per_run=true` in the manifest is not
accepted by itself.

Reports also write `route-comparisons.json`. Treat that file as the primary
place to inspect same-agent, same-task `A-search-only` versus `D-full-router`
exact-token, agent-reported-token, proxy-token, and wall-time deltas. Aggregate
profile medians are supporting context, not proof of a paired routing effect.
When a missing-run plan exists, pass it to
`build_real_agent_report.py --missing-plan`; this writes
`matrix-completion-summary.json` and adds a top-level warning to
`token-savings-report.md` so a partial Codex/Cursor matrix is not mistaken for
a full requested-agent comparison.
`proof-layer-summary.json` shows expected-proof-layer coverage by profile,
agent, and task family, including rows with missing stale fields.
`route-isolation-summary.json` shows route-isolation modes, hard controls, and
weak controls by the same groups so weak isolation does not hide inside per-run
JSON.
Use `route-claim-readiness.json` before making a token-savings claim. It keeps
measurement coverage separate from claims that exact, agent-reported, or
model-visible proxy tokens actually decreased.
The readiness audit can enforce that boundary with
`--require-supported-savings-claim exact`, `exact_uncached`, `agent_reported`,
`proxy`, or `any`.
Use `--require-matrix-completion-report --missing-plan <plan.json>` when a
partial matrix is still publishable only as a scoped pilot; the audit then
verifies that `matrix-completion-summary.json` matches the planner evidence.
Use `--require-terminal-control-summary` to verify that the report includes
per-run prompt delivery, terminal mode, capture, and process/session close
evidence from `terminal-control-summary.json`, cross-checked against each run's
`telemetry.jsonl` and `launch-plan.json`.
Use `--require-route-policy-summary` to verify that report-level
`route-policy-summary.json` has no blocked-tool violations and no checkable
required-first-tool violations, and that its per-run flags still match
`runs.jsonl`.

## Sanitized Pilot Export

When a live pilot is strong enough to keep as durable evidence, export a
public-safe bundle instead of copying raw `/private/tmp` artifacts:

```bash
python3 scripts/benchmarks/export_sanitized_live_pilot.py \
  --benchmark-out results/real-agent-routing/live-codex-pilot \
  --out benchmarks/real-agent-routing/results/live-codex-pilot-sanitized \
  --title "Codex exact paired live pilot"
```

The export keeps manifests, run rows, metrics, judge summaries, route
comparisons, claim-readiness files, terminal-control summaries, route-policy
summaries, telemetry, and route-isolation evidence. It replaces local repo
paths with `<repo:...>` aliases and intentionally omits raw transcripts, task
packets, visible terminal captures, and final-answer text.

When transcript parsing or judging code changes, refresh existing captured runs
without relaunching agents:

```bash
python3 scripts/benchmarks/rejudge_real_agent_benchmark.py \
  --benchmark-out results/real-agent-routing/live-pilot \
  --write \
  --replace-runs
```

Current runner manifests record the task TSV path, so `--tasks` is only needed
for older artifacts or deliberate overrides.
