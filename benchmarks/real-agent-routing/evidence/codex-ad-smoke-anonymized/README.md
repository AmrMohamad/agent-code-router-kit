# Anonymized Codex A/D Live Smoke Results

This bundle publishes private live smoke numbers without company names, repository names, local paths, raw prompts, transcripts, final answers, or exact private repository commits.

## Scope

- Agent: Codex live subject-agent path.
- Compared arms: `A-search-only` versus `D-full-router`.
- Task family: known-symbol definition lookup.
- Cells: 2 private targets x 2 arms x 1 repeat = 4 live cells.
- Claim boundary: full-router system effect smoke evidence only, not LSP-only attribution and not a publishable general benchmark conclusion.

## Target Nature

- **Commerce Web Frontend**: Private production commerce web frontend codebase. The smoke task was a known-symbol definition lookup. No build, browser, or runtime behavior was claimed. Surface: TypeScript/Vue-family frontend.
- **Native iOS Commerce App**: Private production native iOS commerce app codebase. The smoke task was a known-symbol definition lookup. No Xcode build, simulator, or runtime behavior was claimed. Surface: Swift/UIKit-family iOS app.

## Exact Uncached Token Results

| Anonymous Target | A exact uncached | D exact uncached | Uncached tokens avoided | Uncached-token reduction |
|---|---:|---:|---:|---:|
| Commerce Web Frontend | 88,819 | 41,788 | 47,031 | 52.95% |
| Native iOS Commerce App | 87,878 | 70,597 | 17,281 | 19.66% |
| Descriptive total | 176,697 | 112,385 | 64,312 | 36.40% |

The descriptive total is only a compact description of these two smoke cells. It should not be reported as a universal token-saving estimate.

## Trade-Offs

In these smoke runs, `D-full-router` reduced uncached token use and model-visible tool output, but processed more total cached context and took roughly 2.6x as long. This is a context-efficiency result, not an overall compute or latency reduction.

| Anonymous Target | A exact total | D exact total | D total-token change | A wall_s | D wall_s | D/A wall time | Tool output reduction |
|---|---:|---:|---:|---:|---:|---:|---:|
| Commerce Web Frontend | 170,227 | 310,844 | +82.61% | 40.590 | 104.993 | 2.59x | 83.09% |
| Native iOS Commerce App | 169,286 | 319,685 | +88.84% | 44.933 | 117.506 | 2.62x | 30.77% |
| Descriptive total | 339,513 | 630,529 | +85.72% | 85.523 | 222.499 | 2.60x | 67.63% |

## Tool And Isolation Evidence

| Anonymous Target | Arm | Tool evidence | Observed task tools | Search count | Semantic tool count | Hard search-only isolation | Policy violations |
|---|---|---|---|---:|---:|---|---|
| Commerce Web Frontend | A-search-only | observed | rg, rg, rg, rg, rg, rg, sed, sed | 8 | 0 | yes | none |
| Commerce Web Frontend | D-full-router | observed | find_symbol, find_symbol, get_symbols_overview, get_symbols_overview | 0 | 4 | no | none |
| Native iOS Commerce App | A-search-only | observed | rg, rg, rg, rg, sed, sed | 6 | 0 | yes | none |
| Native iOS Commerce App | D-full-router | observed | find_symbol, find_symbol, find_symbol, find_symbol | 0 | 4 | no | none |

## Full Metric Table

| Anonymous Target | Arm | exact_input | cached_input | uncached_input | exact_output | reasoning_output | exact_total | exact_uncached_total | usage_events | wall_s | tool_calls | files_opened | tool_output_bytes | proxy_tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Commerce Web Frontend | A-search-only | 168,894 | 81,408 | 87,486 | 1,333 | 442 | 170,227 | 88,819 | 1 | 40.590 | 3 | 1 | 5,333 | 1,980 |
| Commerce Web Frontend | D-full-router | 306,522 | 269,056 | 37,466 | 4,322 | 3,373 | 310,844 | 41,788 | 1 | 104.993 | 1 | 1 | 902 | 874 |
| Native iOS Commerce App | A-search-only | 168,008 | 81,408 | 86,600 | 1,278 | 301 | 169,286 | 87,878 | 1 | 44.933 | 3 | 1 | 2,236 | 1,231 |
| Native iOS Commerce App | D-full-router | 314,652 | 249,088 | 65,564 | 5,033 | 3,810 | 319,685 | 70,597 | 1 | 117.506 | 1 | 0 | 1,548 | 1,074 |

## Sanitized Evidence Files

- `summary.sanitized.json`: headline metrics, target nature, scope, and trade-off fields.
- `runs.sanitized.jsonl`: one sanitized row per live cell.
- `route-isolation.sanitized.jsonl`: command shape and route-isolation controls with local paths removed.
- `claim-readiness.sanitized.json`: supported and blocked token-savings claim types.
- `audit.sanitized.json`: scoped smoke audit result and requirement statuses.
- `evidence-manifest.sanitized.json`: one-way hashes, run-order metadata, route-profile hashes, and not-captured version fields.

## Interpretation

These four live cells show that the benchmark can hard-isolate the search-only baseline, run a Serena-enabled full-router treatment, capture exact uncached token telemetry, and observe tool evidence. In both private smoke cells, the full-router arm consumed fewer exact uncached tokens than the hard-isolated search-only baseline.

This does not establish LSP-only causality, generalize across task families, or estimate run-to-run variance. A publishable study still needs more task families, more repeats, counterbalanced order, clean snapshots, tool/model version capture, and a larger sanitized evidence bundle.
