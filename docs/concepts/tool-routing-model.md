# Tool Routing Model

The model is:

```text
Discover broadly -> prove semantically -> transform structurally -> verify with runtime/build tools
```

The point is not to make one tool win. The point is to stop an AI agent from using the wrong kind of evidence.

## 1. Discover Broadly

Use `rg` and `fd` when the task starts from text or files:

- route keys;
- log messages;
- localization keys;
- feature flags;
- generated files;
- XIB/storyboard files;
- filenames and folders;
- resource names;
- broad architecture inventory.

Good first passes:

```bash
rg --files-with-matches --glob '*.swift' "literal"
rg --count --glob '*.swift' "literal"
fd "ViewModel|Router|Service"
```

Avoid dumping large `rg -n` output as the first move.

## 2. Prove Semantically

Use SourceKit-LSP or an agent-facing wrapper such as Serena when the target is a Swift symbol:

- class, struct, enum, protocol, method, property, initializer;
- definition and declaration;
- real references;
- protocol conformance;
- overload disambiguation;
- extension namespace separation;
- hover/type information;
- diagnostics.

Text search can tell you where a name appears. LSP can tell you whether that appearance is the symbol you mean.

## 3. Transform Structurally

Use `ast-grep` when the task is syntax-shaped:

- repeated call shapes;
- nested closures;
- migration from one API shape to another;
- Swift constructs where regex can match the wrong structure.

Examples:

```bash
ast-grep --lang swift -p 'Task { $$$BODY }' .
ast-grep --lang swift -p '$A.map { $B in $$$C }' .
```

Use `rg` to estimate scope, then `ast-grep` to prove syntax shape.

## 4. Verify With Runtime Or Build Tools

Use Xcode, an Xcode plugin, CI, or the project build system for:

- build success;
- test success;
- simulator behavior;
- UI screenshots;
- runtime logs;
- result bundles.

LSP diagnostics are useful, but they do not prove that the app builds, tests, or runs.

## Routing Table

| Intent | First tool | Follow-up |
|---|---|---|
| Known Swift symbol | SourceKit-LSP / Serena | focused reads, diagnostics, build/test when changed |
| High-fanout Swift symbol | LSP grouped counts | narrow by overload, method, property, module, or containing type |
| Literal string/key/log | `rg` / `fd` | LSP only if it maps to a Swift symbol |
| Structural Swift pattern | `ast-grep` | compiler/build/test proof when edited |
| Resource/generated/dynamic surface | `fd` / `rg` | runtime proof if behavior matters |
| Build/test/runtime claim | Xcode/plugin/build system | result inspection |

