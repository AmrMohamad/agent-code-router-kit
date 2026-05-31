# Android Operational Completion

Android completion is defined by gates, not historical milestone names.

The Android package is considered operationally complete only when:

- process-state strictness is clean or explicitly project-aware;
- Serena/Kotlin symbol identity and diagnostics pass on the target project;
- Serena reference disagreements are fixed or formally replaced by Android
  Studio usages for the affected symbol patterns;
- Android Studio declaration/usages pass a correctness-based symbol matrix;
- generated-source flows separate discovery, mapping, semantic proof, and build
  proof;
- high-fanout output budget enforcement is active;
- Serena transport mode is chosen with measured evidence;
- Kotlin LSP memory is chosen by measurement;
- Gradle build/install/launch smoke passes when runtime proof is required;
- a second Android repo or an explicitly accepted single-repo scope is covered.

Build/install/launch smoke is not business-flow correctness. LSP and Studio
semantic results are not runtime proof.

See:

- `docs/android/operational-gates.md`
- `docs/android/reference-triage.md`
- `docs/android/studio-symbol-matrix.md`
- `docs/android/readiness-audit.md`
