# Proven Benchmark Boundaries

The sanitized benchmark package preserves the public-safe conclusions of the
private validation work.

It proves:

- known Swift symbols should start with SourceKit-LSP / Serena;
- known Kotlin/Java symbols should start with Serena / Kotlin or Java LSP after
  a project readiness smoke test;
- high-fanout symbols must use grouped counts before reference expansion;
- literals, resources, generated surfaces, localization, and file discovery
  should start with `rg` / `fd`;
- syntax-shaped Swift/Kotlin work should start with `ast-grep`;
- build and runtime truth remain outside the search/LSP benchmark.

It does not prove:

- runtime behavior;
- future compile success;
- LSP will never be stale;
- generated files are fully semantic through LSP;
- XIB/storyboard/localization/resource behavior is represented by symbols;
- an agent will obey the policy without instructions.

Representative sanitized iOS fixture numbers:

- 53 cases;
- 159 measured rows;
- 0 failures;
- 0 timeouts;
- 0 parser errors;
- 24 expected warnings;
- high-fanout raw output around 55-93 KB;
- high-fanout JSON output around 177-299 KB;
- disciplined file/count summaries around 11-15 KB.
