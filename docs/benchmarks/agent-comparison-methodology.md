# Agent Comparison Methodology

Start with within-agent comparisons.

```text
same agent + same repo + same task + same model/sandbox + different routing profile
```

Only after the harness is stable should cross-agent comparisons be used.

## First Pilot

```text
agent: one adapter
profiles: A-search-only, D-full-router
tasks: 3
repeats: 1
mode: dry-run first, then live through PTY after explicit adapter validation
```

## Full Benchmark

```text
agents: Codex, Claude Code, Cursor Agent
profiles: A, B, C, D
tasks: 12 families
repeats: 3
order: randomized
session: fresh per run
```

## Required Report Filters

Reports should allow filtering by:

- agent;
- profile;
- task family;
- repeat index;
- token source;
- tool evidence source;
- correctness status;
- policy adherence.

`build_real_agent_report.py` exposes these filters as CLI options. Keep
within-agent comparisons first; cross-agent comparisons are only meaningful
after the same task, repo state, repeat policy, and token source are held stable.
If a larger requested matrix is only partially filled, pass the missing-run plan
to `build_real_agent_report.py --missing-plan` so report readers see the
matrix-completion status before token or timing tables.
