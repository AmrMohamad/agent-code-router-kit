# Kotlin / Android Serena LSP Setup

Serena language support is project-scoped. The language servers that start for a repo are controlled by that repo's `.serena/project.yml`.

## Recommended Android Languages

For a Kotlin Android repo:

```bash
cd /path/to/android-repo

serena project create \
  --language kotlin \
  --language json
```

Start with Kotlin and JSON even when a repo has a small amount of Java. Add
Java only after Kotlin source-symbol smoke tests pass and the task actually
needs Java semantic proof.

If Java source is a meaningful part of the repo:

```bash
serena project create \
  --language kotlin \
  --language java \
  --language json
```

Expected project config:

```yaml
languages:
- kotlin
- json
```

You can also use the toolkit wrapper from the `agent-code-router-kit` repo:

```bash
./scripts/setup/create-android-serena-project.sh \
  --target-repo /path/to/android-repo
```

For mixed Java/Kotlin:

```bash
./scripts/setup/create-android-serena-project.sh \
  --target-repo /path/to/android-repo \
  --include-java
```

or:

```yaml
languages:
- kotlin
- java
- json
```

## Java/JDTLS Guardrail

Serena's Java support uses a Java language server that can trigger Gradle
project synchronization. In Android repos, that can fail on local machine
requirements such as missing `local.properties` keys, SDK paths, generated
source prerequisites, or private Gradle configuration.

Default policy:

```text
First pass:
  kotlin + json

Add java only when:
  the repo is meaningfully Java-heavy, or
  the task needs Java symbol proof, and
  Gradle/Android Studio sync is known healthy.
```

If adding Java makes Serena slow or unstable, remove `java` from
`.serena/project.yml`, restart the Serena MCP server, and use Android
Studio/JetBrains or `rg/fd` for the Java surface until Gradle sync is repaired.

## Why JSON But Not GraphQL

Current Serena language support includes Kotlin and JSON, but not GraphQL as a native language key. Treat GraphQL as a separate evidence surface:

```text
.graphql / .gql / schema files -> fd / rg + GraphQL validation tools
schema.json / introspection JSON -> JSON tooling + GraphQL validation tools
generated Kotlin models -> Serena / Kotlin LSP
```

## Team-Safe Metadata

If a team does not want `.serena/` inside the repository, configure Serena to store project metadata centrally by editing:

```text
~/.serena/serena_config.yml
```

Example:

```yaml
project_serena_folder_location: "/path/to/user/.serena/projects/$projectFolderName/.serena"
```

Then create Serena projects as usual. Keep this as a personal machine setting unless the team agrees to version Serena project files.

## Health Check

Run:

```bash
serena project health-check /path/to/android-repo
```

Then do a source-symbol smoke test from the agent:

```text
Activate this Android repo with Serena.
Pick one real .kt source file.
Resolve a known class/function declaration and one call-site declaration.
Do not use rg as proof.
```

Serena's generic `health-check` may choose a Gradle Kotlin DSL file such as `build.gradle.kts`; if it reports "No symbols found" for that file, that does not by itself prove Kotlin LSP failed. Confirm with a real `.kt` source file.

Run full indexing only after basic LSP startup/source-symbol proof is clean:

```bash
serena project index /path/to/android-repo
```

## ProjectServer Semantic Probe

If the Codex MCP transport is unavailable but Serena CLI works, use Serena's
read-only ProjectServer to run semantic probes:

```bash
python3 scripts/benchmarks/android/serena_project_server_probe.py \
  --validate --run \
  --cases benchmarks/android/serena-project-server-cases.sample.tsv \
  --repo sample_b2b_android=/path/to/sample-b2b-android-app \
  --repo sample_retail_android=/path/to/sample-retail-android-app \
  --output results/android/serena-project-server \
  --warmups 1 \
  --repeats 3
```

This starts `serena start-project-server`, runs read-only tools such as
`find_symbol`, `find_referencing_symbols`, `get_symbols_overview`, and
`get_diagnostics_for_file`, runs an unrecorded warmup when requested, records
timing and token proxy for measured passes, adds per-case status-stability
assertions, then terminates the server. Follow with the process-state probe to
ensure no stale Serena or language-server processes remain.

If Kotlin symbol results are missing or stale, check:

- Gradle sync/build freshness;
- required machine-local `local.properties` keys;
- duplicate Serena MCP or Kotlin LSP processes that can leave Codex attached
  to a stale server or cause Kotlin LSP workspace ownership conflicts;
- generated sources from KSP/KAPT/Hilt/Dagger/GraphQL;
- module boundaries and included builds;
- Android Studio/IntelliJ semantic state;
- whether JetBrains backend is more appropriate for this repo.

Use the toolkit repair helper to inspect stale sessions without stopping
anything:

```bash
./scripts/setup/repair-serena-android-sessions.sh --dry-run
```

Only after closing or intentionally reconnecting active Codex/Serena sessions,
stop stale language-server processes explicitly:

```bash
./scripts/setup/repair-serena-android-sessions.sh --kill
```

Then restart Codex from the target Android repo and rerun the source-symbol
smoke test.

## Gradle / Local Properties Readiness

Android semantic tools are only as good as the project model they can load.
Before blaming Kotlin LSP or Serena, verify the target repo can configure with
the correct Gradle distribution and local machine keys.

Use:

```bash
bash scripts/setup/check-android-prereqs.sh \
  --target-repo /path/to/android-repo
```

The check reports:

- required command-line tools;
- Serena/Kotlin/JSON process state;
- installed Android Studio apps and Preview/Quail availability;
- whether `android studio check` sees the exact target repo as open;
- Gradle wrapper/cache state;
- required `local.properties` keys by name only;
- Serena project languages with YAML spacing tolerated.

It does not print secret values and it does not create dummy credentials. If a
key such as `sample_analytics_id`, `staging.sample.map.api.key`, or
`production.sample.map.api.key` is required by build logic, add the real
team-approved value locally before expecting Android Studio, Serena JetBrains,
or Kotlin LSP to behave like the fully indexed iOS setup.

## Android Studio / JetBrains Backend

For serious Android projects, Android Studio often has stronger semantic
knowledge than portable Kotlin LSP because it owns Gradle sync, Android Gradle
Plugin state, generated sources, resources, Compose, and IDE indexes.

Use this hierarchy:

```text
1. Serena/Kotlin LSP for portable Kotlin semantic proof after smoke tests pass.
2. Android Studio CLI for IDE readiness and file diagnostics when Quail is open.
3. Serena JetBrains backend/plugin for the strongest IDE-backed symbol layer,
   when installed and configured.
```

Do not assume Android Studio CLI `find-declaration` / `find-usages` work just
because `android studio check` is ready. Run a source-symbol smoke test first.

## Sources

- Serena language support: https://oraios.github.io/serena/01-about/020_programming-languages.html
- Serena project workflow: https://oraios.github.io/serena/02-usage/040_workflow.html
- Serena JetBrains plugin: https://oraios.github.io/serena/02-usage/025_jetbrains_plugin.html
- Kotlin Language Server: https://kotlinlang.org/docs/kotlin-lsp.html
