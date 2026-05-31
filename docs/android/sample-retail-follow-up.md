# Android Sample Retail Follow-Up

Sample Retail is now the second-repo operational follow-up for the Android
hardening track. It is no longer only a planned follow-up: Android Studio
semantic matrix, Gradle build, install, and launch smoke now pass on Sample Retail.

## Current Result

Latest Sample Retail follow-up audit:

```text
status: followup-operational-equivalent
assertions:
  pass: 8
  warn: 2
  fail: 0
```

Evidence:

```text
results/android/sample_retail-followup/android-sample_retail-followup-summary-2026-05-30-072618.json
results/android/sample_retail-followup/android-sample_retail-followup-assertions-2026-05-30-072618.json
```

The gate manifest is:

```text
benchmarks/android/sample-retail-followup-gates.tsv
```

The Sample Retail Android Studio matrix manifest is:

```text
benchmarks/android/studio-symbol-matrix.sample-retail.tsv
```

It defines 12 Sample Retail symbol cases across Android activity/service code, KMP
ViewModels, Compose navigation, Room DAO/database symbols, repository binding,
and generated/config boundaries. It passed through Android Studio project name
`sample_retail`.

The aggregation script is:

```text
scripts/benchmarks/android/sample_retail_followup_audit.py
```

## What Passed

### Gradle Project Model

Sample Retail `./gradlew help --no-daemon` passed when the project-model timeout was
raised above the first-use Gradle 9 configuration cost:

```text
status: pass
gradle_distribution: gradle-9.1.0-bin
wrapper: executable
missing_local_properties: []
wall_seconds: 11.284097
assertions: pass=1, warn=0, fail=0
```

Evidence:

```text
results/android/project-model/android-project-model-summary-2026-05-29-211212.json
```

An earlier 180s project-model run timed out while the direct Gradle command
later completed in about 3m40s. This is now classified as timeout sizing, not
missing local keys.

### Generated-Source Discovery

Sample Retail generated-source discovery passed:

```text
assertions: pass=6, warn=0, fail=0
generated_dir_count: 250
apollo: present
ksp: present
room: present
build_config: present
```

Evidence:

```text
results/android/generated-sources-sample_retail/android-generated-source-summary-2026-05-29-211338.json
```

### High-Fanout Guard

Sample Retail high-fanout summaries passed with expected warnings:

```text
assertions: pass=5, warn=5, fail=0

UseCase:
  files: 326
  matches: 3535
  output_budget: warn

ViewModel:
  files: 153
  matches: 707
  output_budget: warn

Repository:
  files: 71
  matches: 226
  output_budget: pass
```

Evidence:

```text
results/android/high-fanout-summary-sample_retail/android-high-fanout-summary-2026-05-29-211338.json
```

The warnings are policy evidence: these broad symbols must stay summary-first.

### Serena Symbol Lookup

Sample Retail Serena ProjectServer symbol lookup passed for five symbols:

```text
find_symbol_pass: 5
overview_pass: 2
implementation_boundary: 1
```

Examples include `BaseViewModel`, `CartItemsDao`, `MainActivity`,
`MainNavHost`, and `SamplePushService`.

Evidence:

```text
results/android/serena-project-server/serena-project-server-summary-2026-05-29-210655.json
```

### Android Studio Semantic Matrix

Sample Retail Android Studio declaration/usages passed across 16 cases:

```text
trusted_studio_layer: true
case_count: 16
declaration_pass_count: 16
usage_pass_count: 16
assertions: pass=18, warn=0, fail=0
project: sample_retail
```

Evidence:

```text
results/android/studio-symbol-matrix-sample_retail/android-studio-symbol-matrix-summary-2026-05-30-072329.json
```

Current `android studio check` reports Sample Retail as READY:

```text
READY     sample_retail         /path/to/sample-repos/sample-retail-android-app
READY     SampleWholesaleAndroid  /path/to/sample-repos/sample-b2b-android-app
```

Earlier `check` output did not give an honest ready signal for Sample Retail, but direct
`analyze-file`, `find-declaration`, and `find-usages` still worked with project
name `sample_retail`. The current state is stronger: both `check` readiness and the
16-case matrix pass. The matrix remains the proof; do not rely only on the
display label from `check`.

### Build / Install / Launch Smoke

Sample Retail staging debug runtime smoke passed:

```text
project_model: pass
assemble_staging_debug: pass
install_staging_debug: pass
launch_smoke: pass
summary: pass=4, warn=0, fail=0
device: emulator-5554
package: com.example.sampleretail.staging
```

Evidence:

```text
results/android/sample_retail-operational/android-sample_retail-operational-summary-2026-05-30-030237.json
```

The launch smoke captured the launcher activity in `dumpsys activity`. It proves
install and launch readiness only; it does not prove login, checkout, API
connectivity, or business-flow correctness.

## Named Warnings

### Serena References Remain Empty

Sample Retail reference queries returned empty output:

```text
references_empty: 2
```

This aligns with the Sample B2B stable disagreement. Do not use Serena references as
sole reference proof for the affected Android/Kotlin patterns. For these
class-level reference shapes, Android Studio usages are the replacement
reference proof layer until Serena references are fixed.

### Serena Diagnostics Boundary

One Sample Retail diagnostics case returned empty:

```text
diagnostics_empty: 1
```

This is a boundary, not proof that diagnostics are globally unavailable.
Diagnostics need a focused follow-up after clean process state and/or indexing.

### Process-State Risk

The latest Sample Retail-targeted process-state probe saw:

```text
serena_mcp: 7
kotlin_lsp: 0
json_lsp: 0
java_jdtls: 0
classification: other_project_cwd=7
```

No cleanup was performed because those Serena MCP sessions belong to other
active Codex/Serena workspaces. The Sample Retail-targeted probe is project-aware clean;
clean-room strict mode remains a broader readiness hygiene question, not a Sample Retail
target-project stale-session finding.

## Interpretation

Sample Retail now provides equivalent second-repo stable evidence for:

```text
Gradle project-model readiness
generated-source discovery
high-fanout summary discipline
Serena symbol identity lookup
Android Studio declaration/usages matrix
build/install/launch smoke
```

Sample Retail still does not prove:

```text
Serena reference correctness
clean-room strict process mode across all workspaces
business-flow runtime correctness
```

This satisfies the second-repo operational-scope gate for Readiness readiness.
It still does not complete readiness by itself because readiness also requires process
strictness, a daily Serena transport recommendation, and live agent behavior
evidence or explicit proxy acceptance. The reference-disagreement policy is now
handled through Studio-usages replacement for the affected class-level patterns.
