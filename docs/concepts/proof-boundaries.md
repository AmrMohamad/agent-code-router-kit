# Proof Boundaries

Every tool has a boundary. A good agent states that boundary instead of overclaiming.

## LSP Does Not Prove Runtime Behavior

SourceKit-LSP can prove semantic relationships and provide diagnostics. It does not prove:

- the app launches;
- a screen behaves correctly;
- a simulator flow works;
- tests pass;
- build settings are fresh.

Use Xcode, CI, or the build system for that.

## Search Does Not Prove Semantic Identity

`rg` can find text. It cannot prove:

- a reference points to the intended Swift symbol;
- a protocol conformance is real;
- an overload is the selected overload;
- an extension namespace refers to the type you mean.

Use LSP for those.

## ast-grep Does Not Prove Types

`ast-grep` proves syntax shape, not type identity. It is excellent for structural migrations, but a compiler or LSP still needs to verify type-level assumptions.

## Build Tools Do Not Replace Semantic Navigation

A successful build does not tell the agent where all references are or which overload is semantically connected. Build proof and semantic proof complement each other.

## Resource And Generated Surfaces

Generated files, XIB/storyboard files, localization, and resource surfaces often require discovery-first handling:

```text
fd/rg -> focused read -> LSP only if mapped to a Swift symbol -> build/runtime proof if behavior matters
```

