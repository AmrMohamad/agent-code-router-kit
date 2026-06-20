# Claude Code Serena Routing Instructions

Before searching or editing a codebase, classify the task and choose the proof
layer deliberately.

## Serena Readiness

Use Serena for source-code semantics only after:

1. the exact repository is active;
2. `.serena/project.yml` contains the smallest correct language set;
3. one real source-symbol smoke has passed in the current repo.

MCP connection, visible tools, hook reminders, and local text matches are not
semantic readiness proof.

Default language policy:

- Android/Kotlin: `kotlin,json`; add `java` only when Java proof is needed and
  Gradle or Android Studio sync is healthy.
- Swift/iOS: `swift`.
- Python: `python`.
- GraphQL: no native Serena route; use GraphQL tooling and search first.

## Routing

- Known Swift symbol: SourceKit-LSP or Serena first.
- Known Kotlin/Java symbol: Serena/Kotlin or Java LSP first after source-symbol smoke.
- Known Python symbol: Serena/Python LSP first after source-symbol smoke.
- High-fanout source symbol: request grouped counts first; do not dump references.
- Literal/resource/generated lookup: use `rg` / `fd` first.
- GraphQL operation/schema: use GraphQL tools plus `rg` / `fd`; use Serena only for generated/source symbols after discovery.
- Structural Swift/Kotlin/Python pattern: use `ast-grep` or an AST-aware tool first.
- Build/test/runtime proof: use the project build, test, simulator, emulator, device, or CI proof layer.

Do not claim build, test, install, launch, runtime, screenshot, or backend/schema
proof from Serena.
