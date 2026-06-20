# Claude Usage

Claude can use this routing policy through `CLAUDE.md` or a project instruction
fragment.

## Install

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/repo \
  --agent claude \
  --profile android|swift-ios|python|all \
  --dry-run
```

Then apply after review:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/repo \
  --agent claude \
  --profile all \
  --apply
```

If `CLAUDE.md` already exists, the installer writes
`.agent-code-router/CLAUDE.fragment.md` for manual merge.

Use `templates/claude/mcp.example.json` as a project-scoped `.mcp.json` starting
point. Prefer Serena's own setup command when available:

```bash
serena setup claude-code
```

Then verify in-session with `/mcp`.

The example uses `${CLAUDE_PROJECT_DIR:-.}`, which Claude Code provides to
stdio MCP servers for the current project root.

For sessions where Claude Code keeps preferring built-in tools over Serena,
Serena recommends starting Claude with its system-prompt override:

```bash
claude --system-prompt="$(serena prompts print-cc-system-prompt-override)"
```

Serena also provides hook commands such as `serena-hooks remind`,
`serena-hooks activate`, and `serena-hooks cleanup`. Treat these as nudges and
session hygiene, not as semantic readiness proof.

## Required Behavior

Claude should classify the task before searching:

- known source symbol: use Serena or the strongest available semantic layer after source-symbol smoke;
- high-fanout symbol: request grouped counts before reading references;
- literals/resources/generated files: use `rg` / `fd` first;
- GraphQL: use GraphQL tools plus search first;
- build/runtime claims: use the project build, test, simulator, emulator, device, or CI layer.

MCP connection, hooks, and local text matches are not Serena readiness proof.
