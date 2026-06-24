# CodeGraph Evidence Contract

Every successful gateway response returns a compact discovery payload with:

- `schema_version`
- `status`
- `provider`
- `intent`
- `scope_id`
- `proof_level`
- `freshness`
- `summary`
- `anchors`
- `relationships`
- `uncertainties`
- `recommended_next_step`
- `budget`
- `telemetry`

Allowed confidence values:

- `extracted`
- `heuristic`
- `ambiguous`
- `unknown`

Heuristic mobile bridge edges must remain heuristic.
