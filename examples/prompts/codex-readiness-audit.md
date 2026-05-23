# Codex Readiness Audit Prompt

```text
Use the codebase tool router.

Do a Swift/iOS routing readiness audit.

Check:
1. SourceKit-LSP or Serena semantic tooling is available.
2. buildServer.json exists when this is an Xcode project.
3. rg, fd, and ast-grep are available.
4. The build/runtime proof layer is known.
5. High-fanout references will be summarized before expansion.

Do not edit files.
```

