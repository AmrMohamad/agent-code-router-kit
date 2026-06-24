# Benchmark Methodology

CodeGraph benchmarking lives in a separate study namespace:

- `benchmarks/real-agent-routing/studies/codegraph-router-v1/`

This keeps the frozen `router-effect-v1` study unchanged.

Initial graph-specific arms:

- `CG-A-control`
- `CG-B-policy-only`
- `CG-C-capability-only`
- `CG-D-bounded-router`

Optional exploratory arm:

- `CG-X-raw-codegraph`

Negative controls must confirm that literal, exact-symbol, structural, and runtime tasks usually avoid the gateway.
