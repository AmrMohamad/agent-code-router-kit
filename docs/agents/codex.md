# Codex Setup

Codex can use this routing policy through project instructions and a reusable skill.

## AGENTS.md

Place the policy in a project `AGENTS.md`:

```text
templates/AGENTS.md
```

Use the project root or another directory whose children should inherit the policy.

## Skill

Install the skill template from:

```text
templates/codebase-tool-router/SKILL.md
```

For Android-specific tasks, also install:

```text
templates/android-codebase-tool-router/SKILL.md
```

Use your Codex skill installation path and keep the skill general. Do not embed private repository details.

## Prompt

```text
Use the codebase tool router.

For this Swift/iOS task:
- use LSP/Serena for known symbols
- use grouped counts for high-fanout symbols
- use rg/fd for literals and resources
- use ast-grep for structural patterns
- use Xcode/plugin/build proof for build/runtime claims
```

For Android:

```text
Use the Android codebase tool router.

For this Android/Kotlin task:
- use Serena/Kotlin or Java LSP for known source symbols
- use grouped counts for high-fanout symbols
- use rg/fd for resources, generated files, XML, and literals
- use GraphQL tools + rg/fd for GraphQL operations/schemas
- use ast-grep for structural Kotlin patterns
- use Gradle/Android Studio/emulator/CI proof for build/runtime claims
```

## Readiness Audit

Ask Codex to confirm:

1. SourceKit-LSP or Serena is available for Swift/iOS, or Serena/Kotlin LSP is available for Android/Kotlin.
2. `buildServer.json` exists when using an Xcode project.
3. `.serena/project.yml` lists `kotlin` and `json` for Android/Kotlin projects.
4. `rg`, `fd`, and `ast-grep` are available.
5. Xcode/plugin/build proof or Gradle/Android Studio/emulator/CI proof is available when build/runtime claims are needed.
6. No high-fanout references will be dumped.
