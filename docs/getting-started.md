# Getting Started

Use this page to validate a local machine and install the routing policy into a
target project. The deeper Android and real-agent benchmark commands live in
separate runbooks so this page can stay focused.

## 1. Check The Target Repo

Run the Serena doctor first. It is read-only and checks prerequisites for
agent-facing semantic access, duplicate process risk, project metadata, and
proof-boundary wording.

```bash
python3 scripts/setup/serena-doctor.py \
  --target-repo /path/to/repo \
  --profile swift-ios|android|python|generic \
  --json
```

For Swift/iOS work, also check the local prerequisites used by the public
fixture benchmark:

```bash
bash scripts/setup/check-swift-ios-prereqs.sh
```

For Android/Kotlin work, use the Android prerequisite gate:

```bash
bash scripts/setup/check-android-prereqs.sh \
  --target-repo /path/to/android-repo
```

That gate reports missing required `local.properties` keys by name only. It
does not print or create secret values.

## 2. Install Agent Instructions

Preview the install before writing anything:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/repo \
  --agent codex|claude|cursor|generic \
  --profile swift-ios|android|python|all \
  --dry-run
```

Then rerun with `--apply` only after reviewing the proposed file changes.

The install uses:

- `templates/AGENTS.md` for project instructions;
- `templates/codebase-tool-router/SKILL.md` for portable tool routing;
- `templates/android-codebase-tool-router/SKILL.md` for Android/Kotlin routing;
- `templates/codex/`, `templates/cursor/`, and `templates/claude/` for agent-specific setup notes.

See [`docs/agents/agent-self-install.md`](agents/agent-self-install.md) for the
full install behavior.

## 3. Prepare Swift/iOS Semantic Access

For Xcode projects, create a machine-local `buildServer.json` so
SourceKit-LSP can understand schemes, SDKs, targets, imports, and generated
files:

```bash
./scripts/setup/create-build-server-json.sh \
  --project YourApp.xcodeproj \
  --scheme "Your Scheme"
```

or:

```bash
./scripts/setup/create-build-server-json.sh \
  --workspace YourApp.xcworkspace \
  --scheme "Your Scheme"
```

Use SourceKit-LSP or Serena for definitions, references, symbols, hover/type
information, diagnostics, and semantic navigation. Use Xcode only for build,
test, simulator, screenshot, UI, and runtime proof.

## 4. Prepare Android/Kotlin Semantic Access

Create a Serena project with Kotlin and JSON language servers:

```bash
cd /path/to/android-repo

serena project create \
  --language kotlin \
  --language json

serena project health-check .
```

Start with Kotlin and JSON. Include `--language java` only when Java semantic
proof is needed and Gradle/Android Studio sync is known healthy.

Or use the wrapper:

```bash
./scripts/setup/create-android-serena-project.sh \
  --target-repo /path/to/android-repo
```

For Android, prove one real `.kt` source declaration before running full Serena
indexing. Generic health checks can accidentally target `build.gradle.kts`,
which may return no symbols even when Kotlin LSP is working.

For Android operations beyond setup, see
[`docs/android/android-benchmark-operations.md`](android/android-benchmark-operations.md).

## 5. Validate This Repository

Run the portable validation checks:

```bash
python3 scripts/benchmarks/shared/benchmark_runner.py --validate \
  --cases benchmarks/ios/cases.example.tsv
python3 scripts/benchmarks/shared/benchmark_runner.py --validate \
  --cases benchmarks/android/cases.sample.tsv
python3 scripts/benchmarks/run_real_agent_benchmark.py \
  --dry-run \
  --agent codex \
  --repo "$PWD" \
  --tasks benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv \
  --arms A-search-only,D-full-router \
  --task-limit 2 \
  --repeats 1 \
  --out /tmp/agent-code-router-kit-rarb
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/benchmarks/shared/check_public_sanitization.py
```

Dry-run results prove harness behavior only. They do not prove correctness,
token savings, or live agent behavior.

## Minimal Agent Prompt

```text
Use the codebase tool router.

Classify the task before searching:
- known Swift symbol -> SourceKit-LSP / Serena
- known Kotlin/Java symbol -> Serena / Kotlin or Java LSP
- high-fanout symbol -> grouped counts first
- literal/resource -> rg/fd
- structural Swift/Kotlin pattern -> ast-grep
- build/runtime proof -> Xcode/plugin/build system
- Android build/runtime proof -> Gradle/Android Studio/emulator/CI
- GraphQL -> GraphQL tools + rg/fd first, then LSP for generated source

Do not dump high-fanout references.
Do not claim runtime proof from LSP or search.
```
