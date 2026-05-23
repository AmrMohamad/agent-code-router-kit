# Known Symbol Investigation Prompt

```text
Use the codebase tool router.

Investigate this Swift symbol: <SymbolName>

Rules:
- Use SourceKit-LSP / Serena first.
- Find the definition and real semantic references.
- Use rg only as recall after LSP.
- Do not claim build/runtime proof.
- Read only focused ranges.
```

