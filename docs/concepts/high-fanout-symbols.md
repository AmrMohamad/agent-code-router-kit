# High-Fanout Symbols

High-fanout symbols are names that appear across many modules or architectural layers.

Common examples:

- `Resolver`
- `Router`
- `Service`
- `Manager`
- `ViewModel`
- `Factory`
- `Coordinator`
- `Repository`
- `Store`

These names are often real semantic hubs. They are also context explosion traps.

## Why They Flood Context

Raw search can return hundreds of matching lines. LSP can return many real references. Both can flood an AI agent if the agent asks for every reference snippet.

The important distinction:

```text
LSP is more semantically correct.
It is not automatically smaller.
```

## Mandatory Rule

```text
For high-fanout symbols:
1. Find the symbol semantically.
2. Request grouped counts by file/module/containing symbol.
3. Narrow by overload/method/property/initializer/protocol/module.
4. Read only focused ranges.
5. Use rg only as recall, never as proof.
```

## Good Workflow

1. Ask LSP for symbol candidates.
2. Select the exact symbol or overload.
3. Ask for grouped references, not full snippets.
4. Pick relevant files or containing symbols.
5. Read minimal ranges.
6. Use `rg --count` or `rg --files-with-matches` as a recall check.

## Bad Workflow

```text
rg -n "Resolver"
Read every match.
Infer relationships from text.
```

or:

```text
Ask LSP for every Resolver reference.
Paste the whole answer into context.
```

Both are wasteful. The right behavior is summary-first.

