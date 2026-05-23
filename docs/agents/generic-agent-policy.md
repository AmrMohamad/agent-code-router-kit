# Generic Agent Policy

This policy works for any AI coding agent.

## Classify Before Searching

Before choosing a tool, classify the task:

1. Known Swift symbol.
2. High-fanout Swift symbol.
3. Literal string, key, log, path, resource, or generated surface.
4. Syntax-shaped pattern or migration.
5. Build, test, simulator, or runtime proof.

## Routing

| Classification | Route |
|---|---|
| Known Swift symbol | SourceKit-LSP / Serena first |
| High-fanout Swift symbol | LSP grouped counts first |
| Literal or resource | `rg` / `fd` first |
| Structural Swift pattern | `ast-grep` first |
| Build/runtime proof | Xcode/plugin/build system first |

## Required Guardrails

- Never treat `rg` as proof of all references.
- Never treat LSP as proof that an app builds or runs.
- Never dump high-fanout references into context.
- Use focused file ranges after discovery.
- State what was verified and what was not verified.

