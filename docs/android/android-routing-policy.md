# Android Tool Routing Policy

Use this policy for Android/Kotlin projects.

## Known Kotlin / Java Symbol

Use a proven semantic layer first for:

- classes, objects, interfaces, sealed types;
- functions, constructors, properties, extension functions;
- ViewModels, repositories, use cases, mappers;
- DI modules, providers, bindings, annotations;
- Retrofit services, OkHttp interceptors, Room DAOs.

Preferred order:

1. Serena / Kotlin LSP when project smoke tests pass.
2. Android Studio semantic commands when a symbol matrix has passed on the
   current project.
3. `rg` only as recall, not as proof of symbol identity.

If Serena references are empty but Android Studio `find-usages` returns real
Kotlin usages, record a semantic-layer disagreement. Do not treat the empty
Serena reference response as success.

## High-Fanout Symbol

Use grouped summaries first. Never dump all references or raw JSON.

Budget rules:

```text
warn: output > 12 KB
fail: output > 50 KB unless explicitly marked baseline
```

Narrow by package, Gradle module, containing type, function/property,
constructor, implementation, annotation, or generated-vs-handwritten source.

## Literal / Resource / Dynamic Surface

Use `rg` / `fd` first for:

- strings and resource names;
- XML layout IDs, navigation IDs, menu IDs;
- manifest permissions, deep links, intent actions;
- analytics events, logs, error text, feature flags;
- generated `R`, BuildConfig, Safe Args, Hilt/Dagger/KSP/KAPT output;
- ProGuard/R8 rules.

Use LSP only after discovery maps to a concrete Kotlin/Java source symbol.

## GraphQL

Do not route GraphQL to Serena as a native language. Route:

```text
operation/schema discovery -> fd / rg
schema/query correctness -> GraphQL validation/workbench
generated Kotlin models -> Serena / Kotlin LSP or Android Studio
network/runtime behavior -> tests, logs, emulator/device, CI
```

## Structural Android / Kotlin Patterns

Use `ast-grep` for syntax-shaped work:

```bash
ast-grep --lang kotlin -p 'viewModelScope.launch { $$$BODY }' .
ast-grep --lang kotlin -p '$FLOW.collect { $$$BODY }' .
ast-grep --lang kotlin -p '@Inject constructor($$$ARGS)' .
ast-grep --lang kotlin -p 'LaunchedEffect($$$KEYS) { $$$BODY }' .
```

Use `rg` only for broad scope estimation.

## Build / Test / Runtime

Use Gradle, Android Studio, emulator/device, adb, or CI for proof. Do not claim
build/runtime truth from LSP, search, or static symbol navigation.

## Benchmark Commands

Routing benchmark:

```bash
python3 scripts/benchmarks/android/run_benchmark_suite.py \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --sample-retail-repo /path/to/sample-retail-android-app
```

Operational gate:

```bash
python3 scripts/benchmarks/android/operational_gate.py \
  --sample-b2b-repo /path/to/sample-b2b-android-app \
  --device emulator-5554 \
  --variant stagingDebug \
  --enforce-assertions
```

Reference triage:

```bash
python3 scripts/benchmarks/android/serena_reference_triage.py \
  --validate --run \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --output results/android/serena-reference-triage
```

Studio symbol matrix:

```bash
python3 scripts/benchmarks/android/studio_symbol_matrix.py \
  --validate --run \
  --repo sample_b2b=/path/to/sample-b2b-android-app \
  --enforce-assertions
```

Readiness audit:

```bash
python3 scripts/benchmarks/android/readiness_audit.py \
  --results-root results/android \
  --enforce-stable
```
