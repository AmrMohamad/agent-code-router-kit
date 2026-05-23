# Literal Discovery Prompt

```text
Use the codebase tool router.

Find this literal: <literal>

Rules:
- Start with rg/fd.
- Use files/counts before dumping matches if broad.
- Read focused ranges only.
- Use LSP only if the literal maps to a Swift symbol.
```

