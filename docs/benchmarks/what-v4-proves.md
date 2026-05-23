# What The Sanitized V4 Benchmark Proves

The sanitized benchmark package preserves the public-safe conclusions of the private validation work.

It proves:

- known Swift symbols should start with SourceKit-LSP / Serena;
- high-fanout symbols must use grouped counts before reference expansion;
- literals, resources, generated surfaces, localization, and file discovery should start with `rg` / `fd`;
- syntax-shaped Swift work should start with `ast-grep`;
- build and runtime truth remain outside the search/LSP benchmark.

It does not prove:

- runtime behavior;
- future compile success;
- LSP will never be stale;
- generated files are fully semantic through LSP;
- XIB/storyboard/localization behavior is represented by Swift symbols;
- an agent will obey the policy without instructions.

The sanitized reference numbers are:

- 53 cases;
- 159 measured rows;
- 0 failures;
- 0 timeouts;
- 0 parser errors;
- 24 expected warnings;
- high-fanout raw output around 55-93 KB;
- high-fanout JSON output around 177-299 KB;
- disciplined file/count summaries around 11-15 KB.

