# Structural Migration Prompt

```text
Use the codebase tool router.

Find candidates for this Swift syntax-shaped migration:
<pattern description>

Rules:
- Use rg only to estimate scope.
- Use ast-grep to match syntax shape.
- Sample matches before editing.
- Verify with diagnostics/build/test when code changes are made.
```

