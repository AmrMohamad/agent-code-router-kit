# Contributing

Contributions should keep this project practical, public-safe, and agent-neutral.

## Principles

- Keep examples generic.
- Do not include private repository names, local machine paths, screenshots, or raw proprietary output.
- Keep the tool-routing policy precise: semantic identity, literal discovery, structural matching, and runtime proof are different evidence layers.
- Prefer small, reviewable changes.
- Update docs and samples when changing benchmark behavior.

## Validation

Run:

```bash
python3 -m py_compile \
  scripts/benchmarks/benchmark_runner.py \
  scripts/benchmarks/sanitize_results.py \
  benchmarks/swift-ios-router/benchmark_runner.py
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/setup/check-swift-ios-prereqs.sh
bash -n scripts/setup/create-build-server-json.sh
bash -n scripts/setup/agent-self-install.sh
command -v rg
command -v fd
command -v ast-grep
python3 scripts/benchmarks/benchmark_runner.py --help
python3 scripts/benchmarks/benchmark_runner.py --validate \
  --cases benchmarks/swift-ios-router/cases.example.tsv
python3 scripts/benchmarks/benchmark_runner.py --run \
  --cases benchmarks/swift-ios-router/cases.example.tsv \
  --repo sample=benchmarks/swift-ios-router/fixtures/sample \
  --output /tmp/agent-code-router-kit-benchmark \
  --repeats 1 \
  --warmups 0 \
  --timeout 10 \
  --enforce-assertions
find . -type l -maxdepth 5 -print
```

The symlink command should print nothing.

## Privacy Review

Before sharing benchmark results, inspect raw output and replace project-specific names with neutral examples.
