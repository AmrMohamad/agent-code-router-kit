# Security Policy

This toolkit is designed for local codebase analysis and benchmark reporting. It should not receive or publish sensitive repository output by default.

## Reporting Issues

Open a public issue for problems in the toolkit itself. Do not include proprietary source code, internal paths, credentials, screenshots, or raw benchmark output from private repositories.

## Benchmark Output Safety

Raw benchmark output can contain:

- local filesystem paths;
- product or organization names;
- source code snippets;
- generated model names or schema names;
- file names that reveal private architecture.

Before publishing results:

1. Prefer summary JSON over raw stdout.
2. Remove local paths and repository names.
3. Replace product-specific symbols with generic examples.
4. Inspect high-fanout outputs manually.
5. Share only the minimum evidence needed to explain the routing result.

The sample results in this repository are sanitized examples.

## Optional Local Blocklist

The validation workflow supports an optional newline-separated
`PUBLIC_SAFETY_BLOCKLIST` environment variable. Use it in private forks or local
CI to scan tracked files for organization-specific names, local paths, or other
terms that must never appear in public artifacts.
