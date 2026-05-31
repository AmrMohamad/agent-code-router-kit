# Swift/iOS Router Benchmark

This benchmark helps you compare default discovery tools against the routing policy.

It is read-only. It does not run build, test, simulator, or runtime proof.

## Validate The Manifest

```bash
python3 scripts/benchmarks/shared/benchmark_runner.py --validate \
  --cases benchmarks/ios/cases.example.tsv
```

## Run The Public Fixture

```bash
python3 scripts/benchmarks/shared/benchmark_runner.py --run \
  --cases benchmarks/ios/cases.example.tsv \
  --repo sample=benchmarks/ios/fixtures/sample \
  --output /tmp/agent-code-router-kit-benchmark \
  --repeats 1 \
  --warmups 0 \
  --timeout 10 \
  --enforce-assertions
```

## Run On Your Repo

```bash
python3 scripts/benchmarks/shared/benchmark_runner.py --validate --run \
  --cases benchmarks/ios/cases.example.tsv \
  --repo sample=/path/to/your/swift-ios-repo \
  --output results/ios \
  --warmups 1 \
  --repeats 3 \
  --timeout 30 \
  --enforce-assertions
```

## Interpreting Results

- `rg` and `fd` results are discovery baselines.
- `ast-grep` results are syntax-shape baselines.
- LSP evidence must come from your semantic agent layer.
- High-fanout raw and JSON cases are benchmark-only; do not use them as live agent behavior.

The sample results are sanitized. Do not publish raw output from a private repository without review.
