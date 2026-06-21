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

## Order Design

Runs use a four-arm balanced Latin square:

1. A-search-only, B-search-summary, D-full-router, C-lsp-naive
2. B-search-summary, C-lsp-naive, A-search-only, D-full-router
3. C-lsp-naive, D-full-router, B-search-summary, A-search-only
4. D-full-router, A-search-only, C-lsp-naive, B-search-summary

Each task must complete at least four repetitions so every arm appears once in
each sequence position.

## Repository Policy

Confirmatory runs require clean detached snapshots. Public evidence may publish
only opaque repository labels and keyed private fingerprints. Private paths,
project names, symbols, prompts, and snippets must not be committed.

The confirmatory package is frozen by hashing the study plan, this protocol,
the analysis plan, the task oracle file, and the confirmatory task manifest
before execution. The publishable audit must reject any run that uses a custom
task manifest or oracle file, or whose run rows do not match the frozen task
manifest hash. Public bundles may expose keyed HMAC fingerprints for private
task/oracle inputs, not plain private-input hashes.

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

Every randomized run is retained for intention-to-treat analysis. Pass/pass
comparisons are secondary sensitivity analyses only.
