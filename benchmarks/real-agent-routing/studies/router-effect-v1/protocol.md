# Router Effect V1 Protocol

This study measures a Codex-specific routing intervention with a hermetic
factorial design. It is not an LSP-only claim and it is not a cross-agent
claim.

## Claim Boundary

For a pinned Codex model and fixed tool versions, on preregistered tasks from
clean repository snapshots, semantic access and routing discipline may change
context use and correctness relative to controlled baselines.

## Factorial Arms

| Arm | Semantic access | Routing discipline |
| --- | --- | --- |
| A-search-only | off | off |
| B-search-summary | off | on |
| C-lsp-naive | on | off |
| D-full-router | on | on |

Every arm runs from a fresh controlled Codex home with user config, rules, and
plugins ignored. Only semantic access and routing discipline may differ.
Semantic-access arms require a readiness prewarm before task execution. The
readiness result and semantic setup time are reported separately from task
execution time.
Every completed four-arm block publishes `treatment-diffs.jsonl`, comparing
effective agent configs for the preregistered A/B, A/C, C/D, and B/D contrasts.

## Order Design

Runs use a four-arm balanced Latin square:

1. A-search-only, B-search-summary, D-full-router, C-lsp-naive
2. B-search-summary, C-lsp-naive, A-search-only, D-full-router
3. C-lsp-naive, D-full-router, B-search-summary, A-search-only
4. D-full-router, A-search-only, C-lsp-naive, B-search-summary

Each task must complete at least four repetitions so every arm appears once in
each sequence position.

## Repository Policy

Confirmatory runs require clean detached snapshots and a clean controller
checkout. The manifest and run rows must record the controller commit and tree
hash used to execute the study. Public evidence may publish only opaque
repository labels and keyed private fingerprints. Private paths, project names,
symbols, prompts, and snippets must not be committed.

The confirmatory package is frozen by hashing the study plan, this protocol,
the analysis plan, the task oracle file, and the confirmatory task manifest
before execution. The publishable audit must reject any run that uses a custom
task manifest or oracle file, whose frozen package file hashes no longer match
the referenced files, whose analysis-plan semantics drift from this protocol,
or whose run rows do not match the frozen task manifest hash. Public bundles may
expose keyed HMAC fingerprints for private task/oracle inputs, not plain
private-input hashes.

Each confirmatory task requires a task-specific external oracle contract.
Family-level fallback oracles are acceptable only for exploratory development
work; they are insufficient for a publishable confirmatory audit.

## Task Families

The confirmatory set contains five families:

- known-symbol definition/reference
- high-fanout symbol
- literal/resource/generated discovery
- structural pattern
- build/runtime proof boundary

At least three independent tasks are defined per family. The repository labels
in this protocol are generic placeholders, not private project identifiers.

## Outcomes

Co-primary outcomes:

- correctness pass/fail from an external oracle
- exact uncached input tokens

Secondary outcomes:

- exact total tokens
- cached input tokens
- output and reasoning tokens
- model-visible bytes
- tool-output bytes
- wall time
- semantic setup time
- estimated cost when pricing and model identifiers are available
- tool calls, opened files, policy violations, timeouts, and failures

Cost is a secondary outcome only. A cost claim requires explicit pricing for
the pinned model: uncached input, cached input, output, and reasoning-output
rates per one million tokens. Cost reporting must include total cost, median
cost, cost per run, and cost per successful task by arm.

Every randomized run is retained for intention-to-treat analysis. Pass/pass
comparisons are secondary sensitivity analyses only.
Confirmatory runs must not use rerun-failed mode; wrong answers, timeouts,
policy violations, and output-budget stops are study outcomes, not cells to
replace. Valid resume carry-forward is allowed only for intact prior rows with
self-contained artifacts.

Continuous outcomes use paired log ratios with repository/task-cluster bootstrap
confidence intervals. The analysis block key is agent, task id, repository id,
and repetition index, so reused task ids in different repositories remain
independent cells. Confirmatory analysis reports pairwise effects, pass/pass
sensitivity, factorial effects, task-family effects, repository-stratified
effects, and Latin-square sequence-position sensitivity. Pairwise correctness
comparisons use Holm correction. Public evidence must replace
repository-stratified keys with opaque repository ids.
