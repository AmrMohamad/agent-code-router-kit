# Benchmark Methodology

The benchmark compares routing evidence, not universal tool speed.

It measures:

- file discovery with `fd`;
- literal and count discovery with `rg`;
- JSON output size and parsing behavior for `rg --json`;
- syntax-shaped matching with `ast-grep`;
- policy assertions for expected first tool by category.

The LSP side is represented by a runbook and semantic evidence contract because LSP tools are usually exposed through editor, MCP, or agent integrations rather than a portable shell command.

## What The Runner Does

- reads `cases.example.tsv`;
- executes commands with `shell=False`;
- rejects known execution or mutation flags such as `fd --exec`, `rg --pre`,
  and `ast-grep --rewrite`;
- supports CLI/env repo paths;
- applies per-case timeouts;
- supports warmups and measured repeats;
- writes raw stdout/stderr;
- writes summary JSON;
- writes policy assertion JSON.

It is read-only and does not run build, test, or simulator commands.

The repository includes a small public fixture under
`benchmarks/swift-ios-router/fixtures/sample` so CI can run the example
manifest without depending on a private codebase.
