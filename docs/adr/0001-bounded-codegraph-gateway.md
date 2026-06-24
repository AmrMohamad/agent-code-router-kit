# ADR 0001: Bounded CodeGraph Gateway

## Status

Accepted for Phase 1 implementation.

## Context

`agent-code-router-kit` teaches agents to route work to the proof layer that can actually support a claim. The existing model separates:

- literal and resource discovery via `rg` / `fd`
- semantic identity via Serena / LSP
- syntax-shaped audits via `ast-grep`
- runtime proof via build, test, simulator, device, or CI tools

CodeGraph is useful for architecture, multi-file flow, impact, and mobile-bridge discovery, but it is too broad and too verbose to expose directly to subject agents.

## Decision

Phase 1 introduces an optional, read-only MCP gateway between the coding agent and the raw CodeGraph MCP server.

The gateway exposes exactly four model-facing tools:

1. `architecture_context`
2. `trace_code_flow`
3. `impact_scope`
4. `expand_evidence`

The gateway:

- lazy-starts CodeGraph only after a valid graph request
- keeps one child process alive per gateway session
- validates provider tool compatibility before use
- checks freshness internally
- enforces small byte and call budgets
- normalizes outputs into compact evidence
- preserves path, line range, confidence, and provenance
- labels graph output as discovery proof only
- falls back cleanly when CodeGraph is absent, stale, or incompatible

## Non-goals

Phase 1 does not:

- replace Serena/LSP
- replace `rg` / `fd`
- replace `ast-grep`
- prove build or runtime behavior
- auto-run `codegraph install`
- auto-run `codegraph init` during agent tasks
- expose raw CodeGraph tools to subject agents
- modify the frozen `router-effect-v1` study
- enable CodeGraph by default
- write private source snippets into telemetry
- add another LLM inside the gateway

## Budgets

- architecture: `4000` bytes
- flow: `3500` bytes
- impact: `3500` bytes
- expansion: `2500` bytes
- per-scope total: `6000` bytes
- gateway calls per scope: `2`
- child calls per gateway call: `2`
- max files: `5`
- max anchors: `8`
- max relationships: `12`
- expanded evidence IDs: `2`

## Failure behavior

When CodeGraph is not installed, not initialized, stale, incompatible, or returns malformed output, the gateway returns a bounded typed response with a recommended fallback to the existing router.

Malformed provider output returns `partial`; the gateway never invents relationships.

## Packaging

The gateway lives in an isolated Python package under `packages/codegraph-gateway/` so the root toolkit remains lightweight and existing flows remain unchanged when CodeGraph is disabled.

## Host matrix

The gateway contract is host-agnostic and identical for:

- Codex CLI
- Codex Desktop/App where local project MCP config is supported
- Claude Code
- Cursor
- OpenCode

Host-specific behavior is limited to configuration examples, readiness checks, and route-isolation adapters.

## Benchmark boundary

Phase 1 adds a separate `codegraph-router-v1` study. It does not alter the semantics, hashes, arms, or frozen artifacts of `router-effect-v1`.

## Rollback

Rollback requires disabling or removing one MCP entry and the optional CodeGraph policy fragment. Existing router behavior remains intact.
