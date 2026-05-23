# agent-code-router-kit

A public toolkit for teaching AI coding agents how to route Swift/iOS codebase work to the right evidence layer.

The core idea is simple: an agent should not treat text search as code understanding. It should classify the task, choose the right tool, and keep semantic, structural, discovery, and runtime evidence separate.

## Problem

AI coding agents often start with broad search, read too many files, and infer relationships from matching text. That works for literal strings, but it is weak for Swift code identity:

- a class name can appear in comments, strings, generated files, or unrelated namespaces;
- protocols, conformances, overloads, and extension namespaces are semantic relationships, not just text;
- high-fanout names like `Resolver`, `Router`, `Service`, `Manager`, and `ViewModel` can flood the model context;
- XIB, storyboard, localization, generated, and resource surfaces are not fully represented by Swift symbol graphs;
- successful symbol lookup does not prove the app builds or runs.

## Solution

Route each task to the evidence layer that can actually prove it.

| Task | First tool | Why |
|---|---|---|
| Known Swift symbol | SourceKit-LSP / Serena | Proves semantic identity, definitions, references, protocols, overloads, extension namespaces, and diagnostics |
| High-fanout Swift symbol | LSP grouped counts first | Keeps semantic correctness without dumping every reference into context |
| Literal/resource lookup | `rg` / `fd` | Best for strings, logs, route keys, file discovery, localization, resources, and generated surfaces |
| Structural Swift pattern | `ast-grep` | Matches syntax-shaped patterns and migration candidates more safely than regex |
| Build/runtime truth | Xcode, plugin, CI, or build system | Proves compile, test, simulator, UI, and runtime behavior |

## Quick Start

```bash
git clone <your-fork-or-copy>
cd agent-code-router-kit

bash scripts/setup/check-swift-ios-prereqs.sh
python3 scripts/benchmarks/benchmark_runner.py --validate \
  --cases benchmarks/swift-ios-router/cases.example.tsv
```

For an Xcode project, create a machine-local `buildServer.json`:

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

## Install The Policy In An Agent

Use these templates:

- `templates/AGENTS.md` for project instructions.
- `templates/codebase-tool-router/SKILL.md` for Codex-style skill routing.
- `templates/codex/` for Codex setup notes.
- `templates/cursor/` for Cursor rules.
- `templates/claude/` for Claude-style instructions.

Minimal prompt:

```text
Use the codebase tool router.

Classify the task before searching:
- known Swift symbol -> SourceKit-LSP / Serena
- high-fanout symbol -> LSP grouped counts first
- literal/resource -> rg/fd
- structural Swift pattern -> ast-grep
- build/runtime proof -> Xcode/plugin/build system

Do not dump high-fanout references.
Do not claim runtime proof from LSP or search.
```

## Benchmark Summary

The benchmark package is sanitized and public-safe. It captures the routing conclusions without private project data.

Sanitized reference results:

| Metric | Result |
|---|---:|
| Benchmark cases | 53 |
| Measured command rows | 159 |
| Failures | 0 |
| Timeouts | 0 |
| Parser errors | 0 |
| Expected warnings | 24 |
| High-fanout raw search baseline | about 55-93 KB |
| High-fanout JSON search baseline | about 177-299 KB |
| Disciplined files/count summaries | about 11-15 KB |

The important result is not that LSP always uses less model context. It does not. The result is:

```text
LSP proves semantic identity.
rg/fd discover literals, files, resources, and generated surfaces.
ast-grep proves syntax-shaped patterns.
Xcode/plugin/build systems prove build and runtime truth.
High-fanout symbols require grouped-count discipline.
```

## Proof Boundaries

This toolkit does not claim that:

- LSP proves runtime behavior;
- `rg` proves all real symbol references;
- `ast-grep` proves types;
- Xcode/build output replaces semantic navigation;
- generated files, XIB/storyboard, localization, and resource behavior are fully semantic;
- future agent behavior will always follow the policy without instruction.

See `docs/concepts/proof-boundaries.md`.

## Documentation

- `docs/concepts/tool-routing-model.md`
- `docs/concepts/lsp-vs-search.md`
- `docs/concepts/high-fanout-symbols.md`
- `docs/concepts/proof-boundaries.md`
- `docs/swift-ios/sourcekit-lsp-setup.md`
- `docs/swift-ios/xcode-build-server.md`
- `docs/swift-ios/serena-sourcekit-lsp.md`
- `docs/swift-ios/xcode-plugin-proof-layer.md`
- `docs/agents/generic-agent-policy.md`
- `docs/benchmarks/methodology.md`
- `docs/benchmarks/interpreting-results.md`
- `docs/benchmarks/what-v4-proves.md`

## Public Safety

Do not publish raw benchmark output from private repositories without sanitizing paths, names, source snippets, credentials, and organization-specific details.
