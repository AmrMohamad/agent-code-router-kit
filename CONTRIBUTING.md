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
  scripts/benchmarks/shared/benchmark_runner.py \
  scripts/benchmarks/shared/sanitize_results.py \
  scripts/benchmarks/ios/benchmark_runner.py \
  scripts/benchmarks/android/run_benchmark_suite.py
python3 -m unittest discover -s tests -p 'test_*.py'
bash -n scripts/setup/check-swift-ios-prereqs.sh
bash -n scripts/setup/check-android-prereqs.sh
bash -n scripts/setup/create-build-server-json.sh
bash -n scripts/setup/create-android-serena-project.sh
bash -n scripts/setup/repair-serena-android-sessions.sh
bash -n scripts/setup/agent-self-install.sh
command -v rg
command -v fd
command -v ast-grep
python3 scripts/benchmarks/shared/benchmark_runner.py --help
python3 scripts/benchmarks/shared/benchmark_runner.py --validate \
  --cases benchmarks/ios/cases.example.tsv
python3 scripts/benchmarks/shared/benchmark_runner.py --validate \
  --cases benchmarks/android/cases.sample.tsv
python3 scripts/benchmarks/shared/benchmark_runner.py --run \
  --cases benchmarks/ios/cases.example.tsv \
  --repo sample=benchmarks/ios/fixtures/sample \
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
