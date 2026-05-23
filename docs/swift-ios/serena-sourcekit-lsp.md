# Serena And SourceKit-LSP

Serena can act as an agent-facing semantic layer over language servers. For Swift/iOS, the important source of semantic truth is still SourceKit-LSP plus correct Xcode project context.

## Recommended Use

Use Serena / SourceKit-LSP for:

- find symbol;
- go to definition;
- find references;
- hover/type information;
- diagnostics;
- protocol and implementation relationships;
- overload and namespace disambiguation.

## High-Fanout Guard

When a symbol is likely broad, ask for summaries first:

```text
Find the symbol.
Return grouped reference counts by file/module/containing symbol.
Do not dump every reference snippet.
```

Then inspect only the focused ranges needed for the task.

## Not A Runtime Proof Layer

Serena and SourceKit-LSP do not prove that the app builds, tests, launches, or behaves correctly. Use Xcode, a plugin, CI, or the build system for runtime proof.

