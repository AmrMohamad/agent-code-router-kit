---
description: Serena-first code routing for Cursor Agent
alwaysApply: true
---

# Cursor Serena Routing Rule

Classify the task before searching. Use Serena or the editor language server for
source-code semantics only after the current repository and language-server
readiness are clear.

## Readiness Contract

- Activate or open the exact repository.
- Confirm `.serena/project.yml` uses the smallest correct language set.
- Smoke one real source symbol before trusting semantic references.
- Treat hooks and MCP connection as advisory, not readiness proof.
- Treat local text matches as discovery, not semantic proof.

Language defaults:

- Android/Kotlin: `kotlin,json`; add `java` only when needed and sync is healthy.
- Swift/iOS: `swift`.
- Python: `python`.
- GraphQL: use GraphQL tools and search first.

## Routing

- Known Swift, Kotlin, Java, or Python symbols require semantic navigation first.
- High-fanout symbols require grouped counts before reading references.
- Strings, resources, XML, XIB/storyboard, manifests, logs, generated files, and dynamic keys start with `rg` / `fd`.
- GraphQL schemas, operations, and fragments start with GraphQL tooling plus search.
- Syntax-shaped migrations use `ast-grep` or an AST-aware tool.
- Build, test, install, launch, runtime, screenshot, crash, and backend claims require the real project proof layer.
