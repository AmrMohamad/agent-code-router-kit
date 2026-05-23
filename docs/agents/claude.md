# Claude Usage

Use the same policy in Claude project instructions or a reusable prompt.

Recommended instruction:

```text
Before searching a Swift/iOS codebase, classify the task.

Known Swift symbol: use SourceKit-LSP or an equivalent semantic tool first.
High-fanout symbol: request grouped counts first; do not dump references.
Literal/resource/generated surface: use rg/fd first.
Structural Swift pattern: use ast-grep first.
Build/runtime proof: use the project's build, test, simulator, or CI proof layer.
```

The policy is tool-agnostic. If Claude has a different LSP bridge, use that bridge for the semantic layer.

