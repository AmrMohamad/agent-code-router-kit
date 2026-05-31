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

# Android/Kotlin Tool Routing

Use this routing when working on Android, Kotlin, Java, Gradle, JSON, XML resources, or GraphQL surfaces.

## Known Kotlin / Java Symbol

Use a proven semantic layer first:

- Serena / Kotlin LSP after a source-symbol smoke test passes.
- Serena JetBrains backend or Android Studio semantic tools after they pass a
  source-symbol smoke test on the current repo.
- `rg` only as recall/discovery, not as proof of symbol identity.

Examples:

- class;
- object;
- interface;
- sealed type;
- function;
- property;
- constructor;
- extension function;
- ViewModel;
- repository;
- use case;
- mapper;
- DI binding or module.

Use semantic tools for definitions, references, implementations, hover/type information, diagnostics, package/module ownership, and overload/member relationships.

## High-Fanout Kotlin / Java Symbol

Use LSP grouped counts first. Never dump full references.

Narrow by:

- package;
- Gradle module;
- containing type;
- function;
- property;
- constructor;
- implementation;
- annotation;
- generated vs handwritten source.

## Literal / Resource / Dynamic Lookup

Use `rg` / `fd` first for:

- strings and resource names;
- layout IDs, navigation IDs, menu IDs;
- manifest permissions, deep links, intent actions;
- analytics events, logs, errors, feature flags;
- generated `R`, BuildConfig, Safe Args, Hilt/Dagger/KSP/KAPT output;
- ProGuard/R8 rules.

Use LSP only after discovery if the literal maps to a Kotlin or Java symbol.

## GraphQL

Do not assume Serena has native GraphQL LSP support.

Use:

- `rg` / `fd` for operation, fragment, schema, and generated-file discovery;
- GraphQL validation/workbench tools for schema/query correctness;
- Serena / Kotlin LSP only after discovery maps to generated Kotlin symbols or source mappers.

## Structural Kotlin Pattern

Use `ast-grep` first for syntax-shaped repeated patterns.

Use `rg` only for broad scope estimation.

## Android Build / Test / Runtime

Use Gradle, Android Studio, emulator/device, or CI first.

Do not claim runtime or build proof from LSP, search, or ast-grep.

## Android LSP Freshness

If Kotlin LSP results look wrong, check Serena project languages, Gradle sync/build freshness, generated sources, KSP/KAPT output, module boundaries, Android Studio/IntelliJ index, and generated GraphQL models.

Start Serena Android projects with `kotlin,json`. Add `java` only when Java
semantic proof is needed and Gradle/Android Studio sync is healthy; Java/JDTLS
can trigger Gradle sync and local.properties failures on Android roots.

Do not assume Android Studio CLI `find-declaration` or `find-usages` are ready
just because `android studio check` passes. First prove a real source-symbol
lookup on the current repo.

If Serena health-check targets `build.gradle.kts` and reports no symbols, confirm with a real `.kt` source-symbol smoke test before calling Kotlin LSP broken.
