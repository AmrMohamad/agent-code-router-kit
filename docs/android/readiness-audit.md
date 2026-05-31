# Android Readiness Audit

The readiness audit aggregates the latest Android benchmark artifacts into one
promotion signal. It keeps operational evidence separate from runtime/business
claims.

Run it with:

```bash
python3 scripts/benchmarks/android/readiness_audit.py \
  --results-root results/android \
  --enforce-stable
```

The audit reads the latest artifacts for:

- operational gate;
- project-aware process state;
- reference triage;
- direct MCP reference triage;
- Studio symbol matrix;
- generated-source mapping;
- high-fanout summaries;
- Serena transport and lifecycle probes;
- Kotlin LSP memory matrix;
- agent behavior observations;
- second-repo follow-up evidence.

The output schema uses stable field names:

```text
stable_status
readiness_status
stable_counts
readiness_counts
gates[].stable_gate
gates[].readiness
```

Readiness is satisfied only when the required gates pass or when a documented
project-aware boundary is explicitly accepted. A template-only artifact does not
count as readiness evidence.

The audit does not prove business-flow correctness. Build/install/launch smoke
is runtime smoke only.
