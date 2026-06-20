---
name: android-codebase-tool-router
description: Route Android/Kotlin codebase work between Serena/Kotlin LSP, JSON LSP, rg/fd, ast-grep, GraphQL tools, Gradle, Android Studio, emulator, and runtime proof layers.
---

# Android Codebase Tool Router

Use this skill when an agent must understand, change, or verify Android code across Kotlin, Java, Gradle, JSON, XML resources, generated files, GraphQL, or app runtime surfaces.

## Core Principle

```text
Classify intent -> prove identity with the right layer -> keep discovery separate from proof -> verify with Gradle/Android runtime tools
```

## Intent Classifier

Classify first:

- Known Kotlin/Java symbol: class, object, interface, function, property, constructor, sealed type, extension function, annotation, DI binding, ViewModel, repository, use case.
- High-fanout symbol: broad names such as Repository, Service, Manager, ViewModel, Factory, Mapper, Module, Provider, Navigator, Route, GraphQLClient.
- Literal/resource lookup: string, route key, deep link, analytics event, log, error text, SharedPreferences key, feature flag, resource name.
- Android resource/generated/dynamic surface: XML layout, navigation graph, manifest, strings/resources, generated `R`, BuildConfig, KSP/KAPT/Hilt/Dagger output, GraphQL generated models, ProGuard/R8 rules.
- GraphQL surface: `.graphql`, `.gql`, schema JSON, introspection JSON, query/mutation strings, generated operation/model files.
- Structural pattern: repeated call shape, coroutine/Flow/Compose pattern, Dagger/Hilt annotation migration, Retrofit/OkHttp interceptor pattern, Gradle/Kotlin DSL shape.
- Build/runtime claim: Gradle build, unit test, instrumented test, emulator/device behavior, screenshot, logcat, crash, APK/AAB output.

## Routing Table

| Intent | First tool | Rule |
|---|---|---|
| Known Kotlin/Java symbol | Serena / Kotlin or Java LSP | Prove semantic identity before reading many files |
| High-fanout Kotlin/Java symbol | LSP grouped counts | Never dump all references; narrow by package/module/type/member |
| Literal/resource lookup | rg / fd | Search broadly, then read focused ranges |
| XML/resource/generated/dynamic surface | fd / rg | Discovery first; LSP only after mapping to source symbols |
| GraphQL query/schema work | GraphQL workbench + rg/fd | Do not assume Serena has native GraphQL LSP support |
| Structural Android/Kotlin pattern | ast-grep | Match syntax shape, not raw text only |
| Build/test/runtime claim | Gradle, Android Studio, emulator/device, CI | Search and LSP are not runtime proof |

## Serena Setup

Before trusting Serena for Android semantics:

1. Activate the exact Android repo.
2. Confirm `.serena/project.yml` uses the smallest correct language set.
3. Check duplicate Serena/Kotlin/JSON/JDTLS processes if results look stale.
4. Prove one real handwritten `.kt` source symbol through Serena.

MCP connection, visible tools, and hook reminders are not readiness proof. A
local text match is only a precondition; the Serena/Kotlin LSP lookup is the
semantic proof. Gradle, Android Studio, emulator/device, or CI remains required
for build, test, install, launch, screenshot, crash, and runtime claims.

For Android projects, create or update Serena project config with the real project languages:

```bash
serena project create --language kotlin --language json
```

Start with Kotlin and JSON even when a repo has a small amount of Java.
Add Java only after Kotlin source-symbol smoke tests pass and Java proof is
actually needed.

Use this if Java source is meaningful for the task:

```bash
serena project create --language kotlin --language java --language json
```

Rules:

- Kotlin semantic support comes from Serena's Kotlin language server integration.
- JSON support must be explicitly listed when JSON structure or diagnostics matter.
- GraphQL is not a native Serena language key in current Serena releases; route it separately.
- For multi-repo work, register each repo in Serena or create a temporary monorepo folder and activate that.
- Prefer project creation plus a source-symbol smoke test before running full indexing; Kotlin/Android indexing can be slower than Swift on large Gradle projects.
- If `serena project health-check` chooses `build.gradle.kts` and reports no symbols, do not treat that alone as Kotlin LSP failure. Retry with a real `.kt` source symbol through Serena.
- If Java/JDTLS makes Serena slow or triggers Gradle sync failures, remove `java` from `.serena/project.yml`, restart Serena, and use Kotlin/JSON first.
- If Kotlin LSP is incomplete or stale, check Gradle sync/build state, generated sources, KSP/KAPT output, module boundaries, and whether Android Studio/IntelliJ or Serena JetBrains backend gives stronger semantic proof.

## Android Studio / JetBrains Semantic Layer

If Android Studio Preview/Quail and Android CLI are available:

```bash
android studio check
android studio analyze-file --project <project> <real-source-file.kt>
```

Treat `check` and `analyze-file` as readiness/diagnostic proof only. Do not
trust `find-declaration` or `find-usages` until they pass a smoke test on the
current repo.

If `find-declaration` and `find-usages` pass on the current repo, Android
Studio can be used as an IDE-backed semantic comparison layer. For Sample B2B
stable, require the Studio symbol matrix before promoting it to secondary proof:

```bash
python3 scripts/benchmarks/android/studio_symbol_matrix.py \
  --validate --run \
  --repo sample_b2b=/path/to/sample-repos/sample-b2b-android-app \
  --enforce-assertions
```

If Android Studio usages disagree with Serena/Kotlin references, report the
disagreement and do not silently call either layer authoritative.

Current Sample B2B stable matrix status:

```text
case_count: 16
trusted_studio_layer: true
declaration_pass_count: 15
usage_pass_count: 16
assertions: pass=18, warn=2, fail=0
```

This is Sample B2B proof, not global Android proof. Re-run a matrix for the active
repo before treating Android Studio as broadly trusted there.

Current Sample Retail stable follow-up status:

```text
followup-operational-equivalent
assertions: pass=8, warn=2, fail=0
```

Sample Retail currently proves Gradle project-model readiness, generated-source
discovery, high-fanout summary discipline, Serena symbol lookup, a 16-case
Android Studio declaration/usages matrix, build/install/launch smoke, and a
project-aware clean process-state probe for the Sample Retail target project. Sample Retail
still does not prove Serena reference correctness or business-flow runtime
correctness.

Current Sample B2B stable disagreement status:

```text
expanded triage cases: 11
symbols: SampleFeatureViewModel, SampleContentViewModel, SamplePushService
assertions: pass=33, warn=4, fail=0
overall_classification: unclassified disagreement
direct MCP triage cases: 8
direct MCP expanded stdio assertions: pass=37, warn=8, fail=0
direct MCP classifications:
  serena-reference-empty-boundary: 5
  query-shape issue: 2
  kotlin-lsp limitation: 1
```

For those class-level reference patterns, Android Studio usages are the
reference proof layer until Serena references are fixed. Serena still proves
symbol identity and diagnostics for those symbols.

For the strongest Android semantics, prefer Serena's JetBrains backend/plugin
when installed, with the exact same project root open in Android Studio.

## Kotlin / Java Workflow

1. Use a proven semantic layer first for known source symbols: Serena/Kotlin LSP, Serena JetBrains backend, or Android Studio semantic tools after smoke proof.
2. Ask for definition, references, containing symbols, hover/type info, and diagnostics.
3. If Serena references are empty but another proven semantic layer returns usages, record a semantic-layer disagreement instead of treating the empty result as proof.
4. For high-fanout symbols, ask for grouped counts by file/package/module/containing type first.
5. Narrow to a constructor, function, property, annotation, implementation, or module before reading bodies.
6. Use `rg` only as a recall check for dynamic keys, generated code, XML references, resource names, reflection, and string-based DI.

For benchmark/probe output, enforce the shared budget:

```text
scripts/benchmarks/shared/output_budget.py
warn: > 12 KB
fail: > 50 KB unless marked baseline
```

For Serena ProjectServer fallback transport stability on Sample B2B, the current
stable evidence is:

```text
25 measured calls
assertions: pass=38, warn=0, fail=0
process_delta: serena_mcp=0, kotlin_lsp=0, json_lsp=0, java_jdtls=0
```

For the measured ProjectServer fallback path, the Kotlin LSP memory matrix kept
`-Xmx2G` as the lowest stable setting across `-Xmx2G`, `-Xmx4G`, and `-Xmx6G`.
Do not recommend a higher default without a measured timeout, transport
failure, or process-stability reason.

For Android routing behavior regression checks, the repo provides a stable
policy-proxy gate:

```bash
python3 scripts/benchmarks/android/agent_behavior_gate.py \
  --validate --run \
  --enforce-assertions
```

Latest evidence:

```text
case_count: 40
assertions: pass=200, warn=0, fail=0
```

This is a deterministic policy-proxy gate, not live Codex model proof. Use it
to catch routing drift across known symbols, reference disagreement,
high-fanout symbols, JSON structure, literals/resources, GraphQL, generated
surfaces, DI/Gradle structural patterns, build/runtime, Sample Retail/KMP follow-up,
localization/resources, navigation graphs, SharedPreferences keys, manifest
permissions, Room DAO symbols, version catalogs, coroutine dispatcher patterns,
Koin module shapes, and vague discovery prompts.

For readiness live behavior proof, score observed first-tool choices against the same
manifest with `--observed-log` and `--require-observed`; do not treat the proxy
classifier alone as proof that a live agent will obey the policy. The readiness
audit requires at least 10 live first-tool observations before this gate can
satisfy readiness. Current live evidence has 11/10 observations and satisfies this
gate.

Use the live observation recorder to avoid hand-edited blank or copied rows:

```bash
python3 scripts/benchmarks/android/live_observation_recorder.py behavior \
  --log results/android/live-evidence/android-live-behavior-observations.json \
  --case-id <case_id> \
  --observed-first-tool <tool_id> \
  --evidence "<transcript-or-artifact-reference>"

python3 scripts/benchmarks/android/live_observation_recorder.py transport \
  --log results/android/live-evidence/android-transport-real-task-observations.json \
  --task-id <task_id> \
  --transport streamable-http \
  --status pass \
  --transport-error false \
  --process-growth 0 \
  --evidence "<result-artifact-reference>"
```

Use the promotion-readiness audit to keep status honest:

```bash
python3 scripts/benchmarks/android/readiness_audit.py \
  --enforce-stable
```

Current status is stable achieved with named boundaries and readiness ready under the
recorded project-aware process-scope acceptance. All 10 readiness gates pass. Serena reference disagreement is
handled by using Android Studio usages as the proof layer for affected
class-level reference patterns.

If other Serena/Codex sessions are intentionally active, do not silently call
that clean-room proof. Record explicit project-aware process acceptance:

```bash
python3 scripts/benchmarks/android/process_scope_acceptance.py \
  --accept-project-aware-strictness \
  --accepted-by "<name-or-role>" \
  --reason "Other Serena sessions are intentionally active for unrelated projects; target-project ownership is clean."
```

For direct Serena MCP lifecycle on Sample B2B, stable evidence is:

```text
stdio MCP:
  initialize/tools-list passed
  4/4 find_symbol cases passed
  tool_count=22

streamable HTTP MCP:
  initialize/tools-list passed
  4/4 find_symbol cases passed
  tool_count=22

assertions: pass=10, warn=0, fail=0
process_delta: serena_mcp=0, kotlin_lsp=0, json_lsp=0, java_jdtls=0
```

Use realistic Android MCP tool timeouts. A 90 second stdio semantic call timed
out during cold Kotlin startup; the 240 second probe passed. Treat this as a
cold-start timeout-budget boundary, not as a `Transport closed` failure.

## Android Resource Workflow

Use `fd` / `rg` first for:

- `AndroidManifest.xml`
- `res/layout`, `res/navigation`, `res/values`, `res/drawable`, `res/mipmap`
- resource names such as `R.string.foo`, `@id/foo`, `@layout/foo`
- deep links, intent actions, permissions, analytics names, ProGuard/R8 rules
- generated `R`, BuildConfig, Safe Args, Navigation, Hilt/Dagger, KSP/KAPT output

After discovery, map to Kotlin/Java symbols only when a real source symbol is involved.

For Sample B2B stable generated-source mapping, use:

```bash
python3 scripts/benchmarks/android/generated_semantic_mapping.py \
  --validate --run \
  --repo sample_b2b=/path/to/sample-repos/sample-b2b-android-app \
  --run-build-proofs \
  --enforce-assertions
```

Interpret generated-source proof in four layers:

```text
discovery -> mapping -> semantic -> build
```

Apollo generated symbols may be semantic-proven through Studio. Room, Moshi
KSP, and BuildConfig can be build-proven generated boundaries without being
semantic navigation successes.

## GraphQL Workflow

Use GraphQL tooling and discovery first for:

- `.graphql` / `.gql` operations
- schema SDL, `schema.json`, introspection JSON
- operation names, fragments, variables, response fields
- generated Kotlin GraphQL models and mappers

Workflow:

1. Use `fd` / `rg` to find operations, fragments, schema files, and generated output.
2. Use GraphQL validation/workbench tools for schema/query correctness.
3. Use Serena/Kotlin LSP only after discovery maps to generated Kotlin symbols or source mappers.
4. Verify runtime/network behavior with tests, logs, emulator/device proof, or CI.

## Structural Pattern Workflow

Use `ast-grep` for syntax-shaped Android/Kotlin work:

```bash
ast-grep --lang kotlin -p 'viewModelScope.launch { $$$BODY }' .
ast-grep --lang kotlin -p '$RECEIVER.collect { $$$BODY }' .
ast-grep --lang kotlin -p '@Inject constructor($$$ARGS)' .
ast-grep --lang kotlin -p 'fun $NAME($$$ARGS): $RET { $$$BODY }' .
```

Use `rg --files-with-matches` or `rg --count` only to estimate scope before structural matching.

## Build And Runtime Proof

Use Gradle, Android Studio, emulator/device, or CI for proof:

```bash
./gradlew tasks
./gradlew assembleDebug
./gradlew test
./gradlew connectedAndroidTest
```

Prefer the repo's Gradle wrapper when present. If the repo does not ship an executable wrapper, use the team's documented system Gradle, Android Studio, or CI path.

Prefer module/variant-specific tasks when the repo is large:

```bash
./gradlew :app:testDebugUnitTest
./gradlew :feature:assembleDebug
```

Do not claim app correctness from LSP, search, or ast-grep. Runtime truth requires build/test/emulator/device/log evidence.

For the Android Sample B2B operational hardening gate, use:

```bash
python3 scripts/benchmarks/android/operational_gate.py \
  --sample-b2b-repo /path/to/sample-repos/sample-b2b-android-app \
  --device emulator-5554 \
  --variant stagingDebug \
  --enforce-assertions
```

This gate can prove Sample B2B build/install/launch smoke only. It does not claim
business-flow correctness and does not make Android globally readiness-complete.

Reserve readiness language for clean-process strict success or an explicit
project-aware process-scope acceptance artifact, Studio-usages replacement for
affected Serena reference disagreements, Android Studio symbol matrix coverage,
generated-source semantic mapping, a daily-use Serena MCP transport
recommendation beyond lifecycle smoke, and live-agent behavior evidence or
explicit proxy acceptance.

## Final Answer Discipline

Include:

- the intent category selected;
- which tool led and why;
- files touched, if any;
- semantic/search/structural evidence gathered;
- Gradle, Android Studio, emulator, device, or CI verification run;
- verification not run;
- stale-index, generated-code, or dynamic-resource risks.
