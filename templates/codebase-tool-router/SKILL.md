---
name: codebase-tool-router
description: Route Swift/iOS and general codebase work between LSP/semantic tools, rg/fd, ast-grep, and build/runtime proof layers.
---

# Codebase Tool Router

Use this skill when an agent must understand, change, or verify code across files.

## Core Principle

```text
Discover broadly -> prove semantically -> transform structurally -> verify with runtime/build tools
```

## Intent Classifier

Classify first:

- Known Swift symbol: class, struct, enum, protocol, method, property, initializer, extension.
- High-fanout symbol: broad names such as Resolver, Router, Service, Manager, ViewModel, Factory, Coordinator.
- Literal lookup: string, route key, log, error text, localization, config key, feature flag.
- Resource/generated/dynamic surface: XIB, storyboard, asset, schema, generated file, Objective-C selector, dynamic key.
- Structural pattern: syntax-shaped repeated call or migration.
- Runtime/build claim: compile, test, simulator, UI behavior, crash, screenshot, result bundle.

## Routing Table

| Intent | First tool | Rule |
|---|---|---|
| Known Swift symbol | SourceKit-LSP / Serena | Prove semantic identity before reading many files |
| High-fanout Swift symbol | LSP grouped counts | Never dump all references |
| Literal lookup | rg / fd | Search broadly, then read focused ranges |
| Resource/generated/dynamic surface | fd / rg | Discovery first; LSP only after mapping to a Swift symbol |
| Structural Swift pattern | ast-grep | Match syntax shape, not raw text only |
| Runtime/build claim | Xcode/plugin/build system | Search and LSP are not runtime proof |

## High-Fanout Guard

For high-fanout symbols:

1. Find the symbol semantically.
2. Request grouped counts by file/module/containing symbol.
3. Narrow by overload/method/property/initializer/protocol/module/containing type.
4. Read only focused ranges.
5. Use `rg` only as recall, never as proof.

## Swift/iOS Workflow

1. Confirm whether the task is semantic, literal, structural, or runtime-oriented.
2. For semantic Swift work, use SourceKit-LSP / Serena first.
3. For Xcode projects, make sure SourceKit-LSP has correct project context through `buildServer.json`.
4. For literals/resources/generated surfaces, use `rg` / `fd`.
5. For syntax-shaped changes, use `ast-grep`.
6. For build/test/runtime proof, use Xcode, plugin, CI, or the project build system.

## Generic Workflow

1. Start with the smallest useful inventory.
2. Avoid dumping large output.
3. Prove identity with the strongest available semantic tool.
4. Make focused edits.
5. Verify with the correct proof layer.
6. Inspect the diff.

## Verification Discipline

State what was verified:

- semantic references;
- search/file discovery;
- structural matches;
- diagnostics;
- build/test/runtime proof.

State what was not verified. Do not imply a build or runtime check passed unless it was actually run.

## Final Answer Discipline

Include:

- what changed or what was found;
- which routing path was used;
- files touched, if any;
- verification run;
- verification not run;
- remaining risks or assumptions.

