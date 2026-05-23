# Swift/iOS Tool Routing

Use this routing when working on Swift/iOS code.

## Known Swift Symbol

Use SourceKit-LSP / Serena first.

Examples:

- class;
- struct;
- enum;
- method;
- property;
- protocol;
- initializer;
- extension namespace.

Use semantic tools for definitions, references, hover/type information, diagnostics, overloads, and protocol relationships.

## High-Fanout Swift Symbol

Use LSP grouped counts first. Never dump full references.

Narrow by:

- overload;
- method;
- property;
- initializer;
- protocol;
- module;
- containing type.

## Literal Key/String/Log/Error

Use `rg` / `fd` first.

Use LSP only after discovery if the literal maps to a Swift symbol.

## Structural Swift Pattern

Use `ast-grep` first.

Use `rg` only for broad scope estimation.

## Resource/Generated/Dynamic Surfaces

Use `fd` / `rg` first.

Do not expect LSP to understand XIB/storyboard/localization/generated/schema behavior fully.

## Build/Test/Runtime

Use Xcode, plugin, CI, or the project build system first.

Do not claim runtime or build proof from LSP or search.

