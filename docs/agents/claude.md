# Claude Usage

Use the same policy in Claude project instructions or a reusable prompt.

Recommended instruction:

```text
Before searching a Swift/iOS or Android/Kotlin codebase, classify the task.

Known Swift symbol: use SourceKit-LSP or an equivalent semantic tool first.
Known Kotlin/Java symbol: use Serena/Kotlin LSP, Java LSP, or an equivalent semantic tool first.
High-fanout symbol: request grouped counts first; do not dump references.
Literal/resource/generated surface: use rg/fd first.
GraphQL operation/schema: use GraphQL tools plus rg/fd first; use LSP only for generated/source symbols after discovery.
Structural Swift/Kotlin pattern: use ast-grep first.
Build/runtime proof: use the project's build, test, simulator, or CI proof layer.
```

The policy is tool-agnostic. If Claude has a different LSP bridge, use that bridge for the semantic layer.
