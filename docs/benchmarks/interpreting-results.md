# Interpreting Results

The benchmark is a routing regression check.

## Clean Result

A clean result means:

- commands exited successfully;
- no command timed out;
- parsers had no errors;
- manifest categories matched expected routing;
- large outputs were flagged as warnings, not ignored.

## Warnings

Warnings can be useful. A high-fanout warning means:

```text
This output is too large for live agent context.
Use summary-first behavior.
```

## Failures

Failures mean the benchmark package is no longer clean:

- missing tool;
- bad command syntax;
- timeout;
- parser failure;
- routing-policy mismatch.

Fix those before using the result as evidence.

