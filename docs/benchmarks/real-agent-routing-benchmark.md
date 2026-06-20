# Real Agent Routing Benchmark

The Real Agent Routing Benchmark (RARB) measures real AI-agent behavior under different routing policies. It is not a shell-tool benchmark. It asks whether an agent actually avoids noisy search, follows proof boundaries, and reduces model-visible context while preserving correctness.

## Routing Arms

| Arm | Name | Intent |
|---|---|---|
| A | Search-only baseline | Measure old-world search-and-infer behavior. |
| B | Search + summary discipline | Isolate savings from grouped counts and output budgets without semantic tools. |
| C | LSP naive | Measure whether LSP availability alone helps or still floods context. |
| D | Full router system | Measure the target system: semantic proof, discovery tools, structural tools, runtime proof, and high-fanout budgets. |

## What A Run Produces

Each run writes:

```text
transcript.txt
telemetry.jsonl
metrics.normalized.json
judge.json
agent_final_answer.md
task-packet.md
```

Dry-run mode writes those artifacts without launching a real subject agent. This is the default validation path for CI and local development.

The runner prints a Codex TUI-oriented summary by default and also writes
`codex-tui-summary.md` beside the JSON and Markdown metrics files. The
contract-bearing files remain structured so judge and report tooling do not
depend on terminal formatting.
With `--monitor`, the runner emits one progress line per run and writes a
top-level `monitor.jsonl` stream with `run_started` and `run_completed` events.
Live run directories also write lifecycle events to `telemetry.jsonl`, including
process spawn/exit, prompt delivery, PTY output byte chunks, tmux session
start/close, capture changes, sentinel observation, post-sentinel capture
completion for trailing usage events, and timeout events. These
events record process state and byte counts, not raw output text. Use
`--require-live-lifecycle-telemetry` in the readiness audit when claiming that
real-time terminal monitoring was active for a live benchmark.

When resuming from a previous benchmark with `--resume-from`, the runner imports
each carried-forward run directory into the new output root and rewrites the
row's `run_dir`. This keeps resumed benchmark packages self-contained. A row
whose evidence directory or required files are missing is not carried as
evidence; the cell is planned again and counted under
`missing_artifact_carried_forward_runs` in `run-manifest.json`.

Live mode requires `--live`, an adapter with `supports_live: true`, and a clean
target repo unless `--allow-dirty` is provided. Prefer `--snapshot-repos` over
`--allow-dirty` for benchmark evidence: it creates clean detached git worktrees
from the recorded source commits and runs agents there. Codex, Claude Code, and
Cursor Agent have configured PTY/tmux launch plans, but each host must pass the
adapter probe before its benchmark rows count as real evidence.
The readiness audit should be run with `--require-no-weak-route-controls`,
`--require-hard-isolation-for-blocked-tools`, and
`--require-paired-route-comparisons`. For publication-grade runs, also require
`--require-expected-proof-layer`, `--require-fresh-sessions`, `--require-randomized-order`,
`--require-repo-snapshots`, `--require-repo-metadata`,
`--require-real-task-manifest`, `--require-balanced-matrix`, and
`--require-self-contained-artifacts`; if an
adapter only has prompt or environment-level controls for a blocked-tool arm, if
a same-task/same-repeat route cell is missing, if the expected task proof layer
is not observed, if the paired A/D comparison is missing, if run-validity
metadata is missing, or if a run's evidence directory lives outside the
benchmark package, the result remains adapter diagnosis rather than publishable
route-isolation evidence.
With `--require-repo-metadata`, each row's `repo_path` must also match the
manifest `repo_map` entry for that task repo, so carried-forward rows cannot
retain stale workspace paths from an older output package.
`--require-real-task-manifest` rejects `.sample.tsv` and `.example.tsv` task
manifests so demo scaffolds cannot be published as real benchmark results.
Cursor Agent is treated as hard-isolated for search-only arms only when
`--approve-mcps` is absent and the runner probes `agent mcp list` in the target
workspace and observes no loaded MCP servers. A failed MCP probe, loaded MCP
server, or auto-approval flag leaves the row in weak-control status.

Reports include `route-comparisons.json` for paired same-agent, same-task,
same-repeat comparisons between `A-search-only` and `D-full-router`. Use that
paired output for routing-effect claims. A profile-level median can hide a bad
paired result and should be treated as supporting context only.
Reports also include `route-claim-readiness.json`; use it to separate a
completed paired measurement from a supported savings claim. It blocks claims
when correctness is not pass/pass, exact token sources are not comparable, or
the claimed metric did not decrease.
Real-agent rows can also end as controlled failures, for example
`output_budget_exceeded`. Those rows are valid benchmark observations: they
prove the subject agent exceeded a route budget under live monitoring. They are
not correctness passes and they must not be counted as savings-claim support.
For execution-readiness audits that should accept controlled failures as data,
use `--allow-controlled-failures` and omit `--require-all-pass`. For
publishable pass/pass comparisons or savings claims, keep `--require-all-pass`
enabled.
For publishable savings language, run the readiness audit with
`--require-supported-savings-claim exact`, `exact_uncached`, `agent_reported`,
`proxy`, or `any`
so unsupported claim rows fail the audit instead of relying on manual report
reading. Use `exact_uncached` only for an explicitly cache-adjusted exact-token
claim; use `agent_reported` only when the subject agent provides comparable
reported total-token fields. If the claim is intentionally scoped to a subset, add
`--min-supported-savings-pairs N`; then the publishable statement must name that
scope and must not imply that unsupported or controlled-failure rows saved
tokens.

## Metrics

RARB always records proxy metrics:

- prompt bytes;
- transcript bytes;
- answer bytes;
- model-visible bytes;
- tool-output bytes;
- raw-output bytes;
- proxy tokens, computed as bytes / 4;
- tool counts;
- file-open counts;
- raw-dump incidents;
- policy violations;
- correctness status.

Exact token telemetry is optional and must be labeled with a token source. A report must never mix exact, agent-reported, and proxy token numbers without naming the source.

Dry-run runs are judged as `dry_run_contract_pass` when the response contract is
valid. They are not task-correctness evidence. Live pass status requires the
judge to observe the configured success signal and no route-policy violation.

## Safety Boundary

The first implementation is read-only/review-first:

- no destructive commands;
- no hidden file writes by subject agents;
- unique run id per run;
- timeout per run;
- done sentinel per run;
- redacted transcript export;
- no secrets in prompts, telemetry, or reports;
- no success claim without a judge record.

## Current Scope

The first package supports:

- dry-run execution;
- live terminal execution through PTY or tmux for adapters that pass the
  doctor/probe gate;
- Codex, Claude Code, and Cursor adapter launch plans;
- adapter doctor output that separates ready adapters from auth, model-access,
  quota, prompt, flag, and weak route-isolation blockers;
- A/B/C/D route profile files;
- Android task manifests, including real local task rows and sample/example
  rows that strict audits reject for publishable claims;
- route-aware judge and report builders, including matrix-completion,
  terminal-control, route-policy, route-comparison, and claim-readiness
  summaries;
- unit tests for token proxy, transcript parsing, schema validation, terminal bridge behavior, runner dry-run, and judging.

Before publishing a live pilot, validate adapters on the target Mac and run
`audit_real_agent_benchmark_readiness.py` in the mode that matches the claim.
Use execution-readiness mode for "the real benchmark ran and recorded valid
outcomes"; use strict pass/pass mode for "this paired route comparison supports
a correctness-preserving savings claim." Failed strict readiness does not make
the execution artifact scaffold; it means the subject-agent outcomes do not
support that stronger claim.
