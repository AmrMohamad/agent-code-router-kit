# Codex Setup

Codex can use this routing policy through project instructions, reusable skills,
and a Serena MCP server.

## Install

Dry-run first:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/repo \
  --agent codex \
  --profile android|swift-ios|python|all \
  --dry-run
```

Apply only after reviewing the dry-run:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/repo \
  --agent codex \
  --profile all \
  --apply
```

The installer adds project policy, Codex skills, and reviewable Serena MCP/hook
snippets under `.agent-code-router/`.

## Serena MCP Shape

Prefer Serena's machine-local setup command when configuring a real workstation:

```bash
serena setup codex
```

Use the snippet in `templates/codex/config-snippets.toml` as the starting point:

```toml
[mcp_servers.serena]
command = "serena"
args = ["start-mcp-server", "--context=codex", "--project-from-cwd"]
startup_timeout_sec = 30
```

Launch Codex from the target repository when using `--project-from-cwd`, or use
an explicit project path in private local config.

Codex also supports `enabled_tools`, `disabled_tools`, tool approval modes, and
`tool_timeout_sec` in MCP config. Keep those controls in private/local config
when they depend on machine or team policy.

Use `/mcp` in the Codex TUI to verify the server is connected. In the Codex app,
ask Codex to activate the current project with Serena when the app did not start
the server from the repo directory.

## Readiness

Ask Codex to confirm:

1. the exact project is active;
2. `.serena/project.yml` has the smallest correct language set;
3. a real source-symbol smoke has passed;
4. `rg`, `fd`, and `ast-grep` are available for non-semantic discovery;
5. build/runtime proof is routed to Xcode, Gradle, emulator/device, CI, or the project build system.

Use the read-only doctor for preflight:

```bash
python3 scripts/setup/serena-doctor.py \
  --target-repo /path/to/repo \
  --profile android|swift-ios|python|generic \
  --json
```

Do not claim build, test, install, launch, runtime, screenshot, or backend/schema
proof from Serena.
