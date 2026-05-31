# Generic Agent Policy

This policy works for any AI coding agent.

## Classify Before Searching

Before choosing a tool, classify the task:

1. Known Swift or Kotlin/Java symbol.
2. High-fanout Swift or Kotlin/Java symbol.
3. Literal string, key, log, path, resource, or generated surface.
4. GraphQL operation/schema/generated surface.
5. Syntax-shaped pattern or migration.
6. Build, test, simulator/emulator, or runtime proof.

## Routing

| Classification | Route |
|---|---|
| Known Swift symbol | SourceKit-LSP / Serena first |
| Known Kotlin/Java symbol | Serena / Kotlin or Java LSP first |
| High-fanout Swift/Kotlin symbol | LSP grouped counts first |
| Literal or resource | `rg` / `fd` first |
| GraphQL operation/schema | GraphQL tools + `rg` / `fd` first |
| Structural Swift/Kotlin pattern | `ast-grep` first |
| Build/runtime proof | Xcode/Android Studio/Gradle/plugin/build system first |

## Required Guardrails

- Never treat `rg` as proof of all references.
- Never treat LSP as proof that an app builds or runs.
- Never dump high-fanout references into context.
- Use focused file ranges after discovery.
- State what was verified and what was not verified.
