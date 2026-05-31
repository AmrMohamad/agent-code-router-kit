# Android Studio Semantic Layer

Android Studio is the strongest Android-aware semantic environment because it
owns Gradle sync, Android Gradle Plugin state, generated sources, resources,
Compose, and IDE indexes.

Use it as a separate layer from portable LSP:

```text
Serena / Kotlin LSP:
  portable semantic proof after source-symbol smoke tests pass

Android Studio CLI:
  IDE readiness, file diagnostics, and semantic probes when Quail is running

Serena JetBrains backend:
  strongest IDE-backed symbol layer when the Serena JetBrains plugin is installed

Gradle / emulator / adb / CI:
  build, test, install, run, logcat, and runtime proof
```

## Readiness

Install Android Studio Preview/Quail and Android CLI, then open the target repo
in Android Studio and let Gradle sync/index finish.

On this machine, the Android CLI bridge currently sees Android Studio Preview:

```text
version: Quail 2 | 2026.1.2 Canary 2
Projects:
    READY     sample-b2b-android-app
    READY     sample-retail-android-app
```

Check:

```bash
android studio check
android studio analyze-file --project <project-name> <real-source-file.kt>
```

`check` only proves the CLI can see Studio and the project. `analyze-file`
proves the IDE can inspect a concrete file. Neither proves that declaration or
usage lookup works.

## Semantic Smoke Test

Before using Android Studio CLI for symbol proof, run:

```bash
android studio find-declaration \
  --project <project-name> \
  --short \
  --context-file <real-source-file.kt> \
  <KnownSymbol>

android studio find-usages \
  --project <project-name> \
  --short \
  <KnownSymbol>
```

If these return `No declaration found` or `failed to identify the target
declaration`, do not treat Android Studio CLI as the symbol-proof layer yet.
Use Serena/Kotlin LSP if stable, or use `rg/fd` only as discovery while fixing
the semantic layer.

## stable Symbol Matrix

A one-symbol smoke test proves possibility, not reliability. For stable, use the
matrix gate before promoting Android Studio from comparison/probe layer to a
trusted secondary semantic layer:

```bash
python3 scripts/benchmarks/android/studio_symbol_matrix.py \
  --validate --run \
  --repo sample_b2b=/path/to/sample-repos/sample-b2b-android-app \
  --enforce-assertions
```

The manifest is:

```text
benchmarks/android/studio-symbol-matrix.sample-b2b.tsv
```

The matrix checks more than ten symbols across ViewModels, member functions,
use cases, services, network classes, DI properties, request builders, and
generated-source boundaries. A pass requires the expected declaration file and
expected usage files, not just non-empty CLI output.

Thresholds:

```text
declarations: >= 8 passing cases
usages:       >= 7 passing cases
no-result:    must be classified
```

Current local benchmark state after installing Android Studio Preview:

- `android studio check` passes for both ExampleCo Android repos.
- `android studio analyze-file` passes for one real Kotlin file in each repo.
- The older repeated Studio probe produced `51` passes, `39` warnings, and `0`
  failures; those warnings were declaration/usages `no-result` responses, not
  IDE connection failures.
- The Sample B2B stable operational gate recovered `find-declaration` and
  `find-usages` for `SampleFeatureViewModel`.
- The stable Studio matrix passed on Sample B2B with 16 cases, 15 declaration passes,
  16 usage passes, and 0 failures. The only classified warning was generated
  `BuildConfig`, which remains a generated-source boundary.
- Studio is now a trusted secondary semantic proof layer for the tested Sample B2B
  symbol shapes and for Sample Retail's expanded 16-case matrix. The Sample Retail matrix passed
  16 declaration and 16 usage checks across Android activity/service code, KMP
  ViewModels, Compose navigation, Room DAO/database symbols, repository/config
  symbols, DI property usage, method-level Room access, and a private Compose
  helper.
- Serena/Kotlin LSP `index-file` can extract source symbols in Sample Retail and
  Sample B2B, but duplicate/stale Serena or Kotlin LSP sessions can cause workspace
  ownership conflicts until restarted cleanly.
- Gradle project-model readiness remains a build/runtime proof layer rather
  than an LSP proof layer. In the latest stable evidence, Sample B2B and Sample Retail both
  have local project-model/build/install/launch smoke proof, but this does not
  prove business-flow correctness.

Do not hide these as "LSP failed". For Android, semantic indexing depends on
the Gradle project model. If local project sync cannot configure the app, IDE
semantic lookup can be unavailable even when the CLI bridge and file diagnostics
work.

Use the setup gate to surface these blockers without printing secret values:

```bash
bash scripts/setup/check-android-prereqs.sh \
  --target-repo /path/to/android-repo
```

That gate now separates the common failure classes:

- Android Studio Preview app missing;
- Android CLI cannot see a running Quail project;
- the wrong target repo is not open in Studio;
- Gradle wrapper/cache or local machine keys are missing;
- Serena project metadata does not list Kotlin/JSON.

## Serena JetBrains Backend

Serena's JetBrains plugin lets Serena use IDE-backed code intelligence. For
Android projects, this is often the closest equivalent to iOS/Xcode-backed
semantic truth.

Requirements:

- install the Serena JetBrains plugin in Android Studio or IntelliJ;
- open the exact same project root in the IDE;
- configure Serena to use the JetBrains backend globally, per server, or per
  project;
- restart the Serena MCP server because the backend is selected at startup.

Use per-project config when only Android repos should use JetBrains:

```yaml
language_backend: JetBrains
```

Do not mix LSP and JetBrains backends inside one already-running Serena MCP
server; start separate server instances or activate the desired project at
startup.

Sources:

- https://developer.android.com/tools/agents/android-cli
- https://oraios.github.io/serena/02-usage/025_jetbrains_plugin.html
- https://kotlinlang.org/docs/kotlin-lsp.html
