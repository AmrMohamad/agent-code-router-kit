---
name: codebase-tool-router
description: Route Swift/iOS, Android/Kotlin, and general codebase work between LSP/semantic tools, rg/fd, ast-grep, GraphQL tools, and build/runtime proof layers.
---

# Codebase Tool Router

Use this skill when an agent must understand, change, or verify code across files.

## Serena Readiness Contract

Use Serena for source-code semantics only after the current repository is active
and one real source-symbol smoke has passed.

Treat each layer separately:

- MCP connected: transport only.
- Active project: repository selection only.
- `.serena/project.yml`: language-server intent only.
- Source-symbol smoke: first semantic readiness proof.
- Build/test/runtime tools: compile, behavior, UI, and release proof.

If Serena tools are visible but fail, activate the exact project and retry one
small symbol lookup. If a health check chooses a build file or generated file,
smoke a handwritten source symbol before calling the language server broken.

Default language policy:

- Android: `kotlin,json`; add `java` only when Java proof is needed and Gradle
  sync is healthy.
- Swift/iOS: `swift`.
- Python: `python`.
- GraphQL: route through GraphQL tooling first, then use Serena only for
  generated/source symbols after discovery.

Do not claim build, test, install, launch, runtime, screenshot, or backend proof
from Serena.

## Core Principle

```text
Discover broadly -> prove semantically -> transform structurally -> verify with runtime/build tools
```

## Intent Classifier

Classify first:

- Known Swift symbol: class, struct, enum, protocol, method, property, initializer, extension.
- Known Kotlin/Java symbol: class, object, interface, function, property, constructor, extension function, ViewModel, repository, use case, mapper, DI binding.
- High-fanout symbol: broad names such as Resolver, Router, Service, Manager, ViewModel, Factory, Coordinator.
- Literal lookup: string, route key, log, error text, localization, config key, feature flag.
- Resource/generated/dynamic surface: XIB, storyboard, Android XML resource, asset, schema, generated file, Objective-C selector, dynamic key.
- GraphQL surface: `.graphql`, `.gql`, schema JSON, introspection JSON, operation string, generated model.
- Structural pattern: syntax-shaped repeated call or migration.
- Runtime/build claim: compile, test, simulator, UI behavior, crash, screenshot, result bundle.

## Routing Table

| Intent | First tool | Rule |
|---|---|---|
| Known Swift symbol | SourceKit-LSP / Serena | Prove semantic identity before reading many files |
| Known Kotlin/Java symbol | Proven Serena / Kotlin LSP, Serena JetBrains backend, or Android Studio semantic layer | Prove semantic identity before reading many files |
| High-fanout Swift/Kotlin symbol | LSP grouped counts | Never dump all references |
| Literal lookup | rg / fd | Search broadly, then read focused ranges |
| Resource/generated/dynamic surface | fd / rg | Discovery first; LSP only after mapping to a Swift symbol |
| GraphQL surface | GraphQL tools + rg/fd | LSP only after mapping to generated/source symbols |
| Structural Swift/Kotlin pattern | ast-grep | Match syntax shape, not raw text only |
| Runtime/build claim | Xcode/Android Studio/Gradle/plugin/build system | Search and LSP are not runtime proof |

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

## Android/Kotlin Workflow

1. Confirm whether the task is semantic, literal/resource, GraphQL, structural, or runtime-oriented.
2. For known Kotlin/Java symbols, use a proven semantic layer first: Serena/Kotlin LSP, Serena JetBrains backend, or Android Studio semantic tools after source-symbol smoke proof.
3. For Android resources, manifests, generated files, dynamic keys, and XML, use `rg` / `fd` first.
4. For GraphQL operations/schemas, use GraphQL validation/workbench tools plus `rg` / `fd`; use Kotlin LSP only for generated/source symbols after discovery.
5. For syntax-shaped Kotlin/Gradle patterns, use `ast-grep`.
6. For build/test/runtime proof, use Gradle, Android Studio, emulator/device, CI, or the project build system.
7. Start Serena Android projects with `kotlin,json`; add `java` only when Java proof is needed and Gradle sync is healthy.
8. If Kotlin LSP is stale, incomplete, or slow, check Gradle sync/build freshness, generated KSP/KAPT/Hilt/Dagger/GraphQL sources, module boundaries, and whether Serena JetBrains backend or Android Studio is the stronger semantic layer.
9. Do not trust Android Studio CLI `find-declaration` / `find-usages` until they pass a source-symbol smoke test on the current repo.

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
