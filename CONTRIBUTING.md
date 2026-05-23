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
python3 -m py_compile scripts/benchmarks/benchmark_runner.py
bash -n scripts/setup/check-swift-ios-prereqs.sh
bash -n scripts/setup/create-build-server-json.sh
python3 scripts/benchmarks/benchmark_runner.py --help
python3 scripts/benchmarks/benchmark_runner.py --validate \
  --cases benchmarks/swift-ios-router/cases.example.tsv
find . -type l -maxdepth 5 -print
```

The symlink command should print nothing.

## Privacy Review

Before sharing benchmark results, inspect raw output and replace project-specific names with neutral examples.

