# High-Fanout Investigation Prompt

```text
Use the codebase tool router.

Investigate this high-fanout Swift symbol: <SymbolName>

Rules:
- Use LSP to identify the exact symbol.
- Request grouped counts by file/module/containing symbol first.
- Do not dump full references.
- Narrow by overload, method, property, protocol, module, or containing type.
- Use rg only as recall.
```

