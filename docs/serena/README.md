# Serena Agent Operating Guide

This guide is the Serena-first entrypoint for agents using this toolkit. Use it
before benchmark docs. Benchmarks are optional validation artifacts; this page is
the daily operating model.

## What Serena Is In This Toolkit

Serena is an agent-facing semantic access layer. In practice, an agent connects
to Serena through MCP, activates one project, and asks language-server-backed
tools for source symbols, definitions, references, hover/type information, and
diagnostics.

Keep these layers separate:

| Layer | What It Proves | What It Does Not Prove |
| --- | --- | --- |
| MCP connection | the agent can talk to a Serena server | correct project, active tools, healthy language servers |
| Active project | Serena knows the intended repository | language-server readiness |
| Language-server startup | configured languages attempted to initialize | source-symbol correctness |
| Source-symbol smoke | one real symbol can be resolved semantically | build, tests, runtime behavior |
| Build/runtime proof | compile, install, launch, UI, or CI state | semantic reference completeness |

The important rule: do not treat "Serena is connected" as "Serena is ready".

## Default Agent Workflow

1. Activate the exact repository.
2. Confirm `.serena/project.yml` exists and contains only the languages needed
   for the current repo.
3. Check for stale or duplicate Serena/LSP processes.
4. Run a real source-symbol smoke before making semantic claims.
5. Use Serena for known source symbols.
6. Use `rg` / `fd` for literals, resources, generated files, logs, and dynamic
   keys.
7. Use GraphQL tooling for GraphQL schema and operation truth.
8. Use the project build/runtime layer for compile, test, install, launch, UI,
   screenshot, and backend proof.

For a read-only preflight:

```bash
python3 scripts/setup/serena-doctor.py \
  --target-repo /path/to/repo \
  --profile android \
  --source-file app/src/main/java/example/FeatureViewModel.kt \
  --symbol-smoke FeatureViewModel
```

Use `--json` when another agent or CI step needs stable machine output.

For deeper client-specific integration decisions, see
[Serena Integration Research For AI Agents](agent-integration-research.md).

## Language Defaults

| Repo Type | Serena Languages | Notes |
| --- | --- | --- |
| Android/Kotlin | `kotlin,json` | Add `java` only when Java proof is needed and Gradle/Studio sync is healthy. |
| Swift/iOS | `swift` | Keep `buildServer.json`, Xcode build/index state, and SourceKit readiness separate from runtime proof. |
| Python | `python` | Serena can handle Python source symbols, but tests still prove behavior. |
| GraphQL | none | Serena is not the GraphQL proof layer; use GraphQL tools and `rg` / `fd`. |

Serena starts one language server per configured language. A bad extra language
can break the whole semantic readiness path, so the smallest correct language
set is usually the strongest setup.

## Routing Rules

Use Serena first for:

- known classes, structs, interfaces, functions, properties, initializers, and
  methods;
- definitions, references, implementations, hover/type information, diagnostics,
  and package/module ownership;
- focused follow-up after `rg` maps a literal to a real source symbol.

Do not use Serena as the first proof layer for:

- strings, logs, error text, feature flags, analytics keys, resources, XML,
  XIB/storyboard files, manifests, generated `R`, BuildConfig, Safe Args,
  Hilt/Dagger/KSP/KAPT output, or generated schema files;
- GraphQL schemas, operations, fragments, or variables;
- build, test, install, launch, runtime, screenshot, or backend/schema claims.

For high-fanout symbols, ask for grouped counts by file/module/type first. Do
not dump full reference lists until the target is narrowed.

## Failure Modes And Recovery

| Symptom | Likely Cause | Recovery |
| --- | --- | --- |
| MCP tools are visible but fail | no active project or inactive tools | activate the exact repo and retry one small symbol lookup |
| MCP connected but references are empty | language server not initialized, stale index, or unsupported reference shape | run source-symbol smoke and compare with another semantic layer if available |
| health-check reports no symbols on Android | it targeted `build.gradle.kts` or a non-source file | smoke a real `.kt` declaration before calling Kotlin LSP broken |
| Serena starts slowly or fails on Android | extra `java`/JDTLS caused Gradle sync or `local.properties` trouble | use `kotlin,json` first; add `java` only for proven Java needs |
| results look stale | duplicate Serena/LSP processes or old project cwd | inspect process state, then restart only the affected sessions intentionally |
| GraphQL route is unclear | GraphQL is not native Serena routing | validate with GraphQL tools, then use Serena only for generated Kotlin/Swift symbols |
| hook fired but semantic tools fail | hooks are reminders, not readiness checks | run doctor/source-symbol smoke and treat hook output as advisory |

## Related Pages

- Android setup: [Kotlin Serena LSP Setup](../android/kotlin-serena-lsp-setup.md)
- Swift setup: [Serena SourceKit-LSP](../swift-ios/serena-sourcekit-lsp.md)
- Proof boundaries: [Proof Boundaries](../concepts/proof-boundaries.md)
- Agent install: [Agent Self-Install Playbook](../agents/agent-self-install.md)
- Integration research: [Serena Integration Research For AI Agents](agent-integration-research.md)
