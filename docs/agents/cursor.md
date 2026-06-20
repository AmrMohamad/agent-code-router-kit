# Cursor Usage

Cursor can use this routing policy through project rules.

## Install

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/repo \
  --agent cursor \
  --profile android|swift-ios|python|all \
  --dry-run
```

Then apply after review:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/repo \
  --agent cursor \
  --profile all \
  --apply
```

The installer writes `.cursor/rules/agent-code-router.mdc` unless a differing
file already exists.

Use `templates/cursor/mcp.example.json` as a `.cursor/mcp.json` starting point
for a project-local Serena server. Cursor also supports `AGENTS.md`, and it
discovers portable Agent Skills from `.agents/skills/`.

Use Serena's `ide` context for Cursor so Serena does not duplicate more of the
editor's built-in tooling than necessary.

## Required Behavior

Cursor search is useful discovery. It is not semantic proof for same-name
symbols, overloads, protocols, extensions, generated types, or package/module
ownership.

Use the Serena/editor language server for source symbols after readiness is
clear, use `rg` / `fd` for literals and resources, use GraphQL tools for
GraphQL truth, and use the project build/runtime layer for behavior claims.
