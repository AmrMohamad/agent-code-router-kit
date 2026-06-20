# Serena Integration Research For AI Agents

This note captures the external documentation reviewed for optimizing Serena
integration across Codex, Claude Code, Cursor, and generic MCP clients.

## Sources Reviewed

- Serena client docs: <https://oraios.github.io/serena/02-usage/030_clients.html>
- Serena repository README: <https://github.com/oraios/serena>
- Codex MCP docs: <https://developers.openai.com/codex/mcp>
- Codex config docs: <https://developers.openai.com/codex/config-basic>
- Codex AGENTS.md docs: <https://developers.openai.com/codex/guides/agents-md>
- Codex skills docs: <https://developers.openai.com/codex/skills>
- Claude Code MCP docs: <https://code.claude.com/docs/en/mcp>
- Claude Code settings docs: <https://code.claude.com/docs/en/settings>
- Cursor MCP docs: <https://cursor.com/docs/mcp.md>
- Cursor rules docs: <https://cursor.com/docs/rules.md>
- Cursor skills docs: <https://cursor.com/docs/skills.md>
- MCP transport spec: <https://modelcontextprotocol.io/specification/2025-03-26/basic/transports>
- MCP security best practices: <https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices>

## Current Integration Findings

### Serena

Serena is strongest when treated as an IDE-like semantic layer rather than a
generic file/search layer. Its own docs distinguish clients with per-workspace
MCP configuration from clients with global configuration:

- Per-workspace clients should start Serena with `--project <path>` and a
  single-project context such as `claude-code` or `ide`.
- Global clients should use `activate_project`; Codex and Claude Desktop are
  examples where project activation must be explicit.
- Serena recommends selecting tool sets through Serena configuration/context,
  because its prompts adjust based on enabled tools.
- Some clients may not use Serena tools reliably without hook reminders.
- Environment variables needed by language servers should be set in the MCP
  server configuration when the client-spawned process does not inherit shell
  profile values.
- Serena currently recommends `serena setup codex` for Codex and
  `serena setup claude-code` for Claude Code.
- Serena's Codex docs still show the older `codex_hooks` feature flag, while
  current Codex docs document `[features].hooks`; this toolkit should use the
  current Codex key and keep Serena's hook commands as examples.

Practical implication for this toolkit: project-scoped clients should prefer
fixed project launch commands; global clients need a visible "activate exact
project" instruction and a readiness doctor.

### Codex

Codex stores MCP server config in `config.toml`; user config lives at
`~/.codex/config.toml`, and trusted projects may use `.codex/config.toml`.
The CLI and IDE extension share this config. Codex supports both STDIO and
Streamable HTTP MCP servers, reads MCP server instructions, and exposes useful
server controls:

- `[mcp_servers.<name>]` for server config.
- `command`, `args`, `env`, `env_vars`, and `cwd` for STDIO servers.
- `url`, bearer token, and header options for Streamable HTTP servers.
- `startup_timeout_sec`, `tool_timeout_sec`, `enabled`,
  `enabled_tools`, `disabled_tools`, and approval-mode controls.
- `/mcp` in the TUI to inspect active servers.

Codex also reads `AGENTS.md` before work and supports skills with progressive
disclosure. That makes the best Codex integration a three-layer setup:

1. `AGENTS.md` for always-on routing rules and Serena proof boundaries.
2. A focused `codebase-tool-router` skill for on-demand workflows.
3. Serena MCP config with explicit timeout/tool policy and local project
   activation guidance.

Use `startup_timeout_sec`, not `startup_timeout_ms`. Prefer
`serena setup codex` for local machine setup, then keep this repository's TOML
snippet as a reviewable public example.

### Claude Code

Claude Code has a richer MCP management surface than a plain JSON config:

- `claude mcp add` and related commands manage servers.
- Project-scoped MCP servers are stored in `.mcp.json`.
- User and local MCP configuration are stored under `~/.claude.json`.
- Environment-variable expansion works in `.mcp.json` for `command`, `args`,
  `env`, `url`, and `headers`.
- `/mcp` is the in-session inspection surface.
- Claude Code documents output warnings above 10,000 MCP-output tokens and a
  default maximum of 25,000 tokens, adjustable through `MAX_MCP_OUTPUT_TOKENS`.
- Tool Search exists to keep large MCP tool surfaces out of context until
  needed.
- Serena recommends launching Claude Code with
  `claude --system-prompt="$(serena prompts print-cc-system-prompt-override)"`
  when Claude Code over-prefers built-in tools.
- Serena also provides `serena-hooks remind`, `activate`, `cleanup`, and
  `auto-approve` commands for Claude Code hooks.

Practical implication: Claude Code should get a project-local Serena config for
repo work, plus a compact `CLAUDE.md` that says when to use Serena and when to
fall back to search/build/runtime proof. Large tool surfaces should be handled
through Tool Search or tight Serena context/tool selection, not by dumping more
instructions into `CLAUDE.md`.

### Cursor

Cursor supports project and global MCP config:

- Project config: `.cursor/mcp.json`.
- Global config: `~/.cursor/mcp.json`.
- STDIO, SSE, and Streamable HTTP transports are supported.
- Cursor supports MCP tools, prompts, resources, roots, elicitation, and Apps.
- Cursor can inspect and toggle MCP servers from settings; Cursor CLI also has
  `agent mcp list`, `agent mcp list-tools`, `agent mcp enable`, and
  `agent mcp disable`.

Cursor rules are first-class:

- Project rules live under `.cursor/rules` as `.mdc` files.
- Plain `.md` files in `.cursor/rules` are ignored.
- `AGENTS.md` is supported as a simpler alternative, including nested files.
- Project rules should stay focused, actionable, and generally under 500 lines.

Cursor also supports Agent Skills and discovers them from `.agents/skills/`,
`.cursor/skills/`, and compatibility locations such as `.codex/skills/` and
`.claude/skills/`.

Serena recommends the `ide` context for MCP-enabled IDEs and coding clients such
as Cursor to reduce duplication with the editor's built-in tools.

Practical implication: the strongest Cursor integration should install both a
short `.cursor/rules/*.mdc` rule and, when desired, the same portable
`SKILL.md` under `.agents/skills/codebase-tool-router/`.

### MCP-Level Constraints

The MCP spec defines STDIO and Streamable HTTP as standard transports. For local
Serena use, STDIO is simple and single-user. For multi-agent or shared-team
Serena deployments, Streamable HTTP is the better architectural target when the
client supports it.

Security matters because MCP servers can expose tools and data across trust
boundaries. For Serena integration this means:

- prefer least-privilege tool sets;
- avoid exposing write/edit tools when the task is read-only investigation;
- keep project roots explicit;
- avoid secrets in checked-in MCP configs;
- use environment-variable expansion or local/user config for private values;
- treat hooks as nudges or policy checks, not semantic proof.

## Optimization Recommendations

### 1. Split Setup By Client Scope

Use this decision table:

| Client | Preferred Serena Project Binding | Instruction Surface | MCP Config Surface |
| --- | --- | --- | --- |
| Codex | global/server config plus `activate_project`, or trusted project config with `cwd` | `AGENTS.md` + skill | `~/.codex/config.toml` or trusted `.codex/config.toml` |
| Claude Code | fixed `--project <repo>` | `CLAUDE.md` | `.mcp.json` for project scope |
| Cursor | fixed project config | `.cursor/rules/*.mdc` + optional skill | `.cursor/mcp.json` |
| Generic MCP client | explicit project path when possible | `AGENTS.md` or README fragment | client-specific |

### 2. Make Serena Readiness A Standard Preflight

Every agent should follow the same readiness ladder:

1. transport connected;
2. exact project active;
3. language list minimal and correct;
4. language server not obviously stale;
5. one real source-symbol smoke;
6. high-fanout references summarized before expansion.

`scripts/setup/serena-doctor.py` should remain read-only and should not kill
processes. Recovery scripts can stay separate.

### 3. Install Portable Skills, Not Only Rules

Because both Codex and Cursor support Agent Skills and Cursor also reads
`.agents/skills`, the toolkit should eventually install a project-scoped
portable skill:

```text
.agents/skills/codebase-tool-router/SKILL.md
```

Codex-specific installs can still mirror the skill into `$CODEX_HOME/skills`
for user-level reuse, but the project-scoped skill gives Cursor, Codex, and
future skill-aware agents the same workflow artifact.

### 4. Add Client-Native MCP Snippets

The current snippets should grow into client-native examples:

- Codex: TOML with `startup_timeout_sec`, optional `cwd`, tool allow/deny lists,
  and `/mcp` verification.
- Claude Code: `.mcp.json` example with `${CLAUDE_PROJECT_DIR:-.}` expansion
  and `serena setup claude-code` as the recommended path.
- Cursor: `.cursor/mcp.json` example with `type: "stdio"`, `command`, `args`,
  and `${workspaceFolder}` interpolation.

### 5. Keep Serena Context Small

For reliability and cost:

- make the routing rule short enough to be always-on;
- put detailed recovery in docs;
- put executable checks in scripts;
- use skills for deeper workflows;
- use Serena tool/context selection rather than exposing every possible tool to
  every agent session.

### 6. Prefer Streamable HTTP Only For Shared Multi-Agent Serena

STDIO should remain the default for local one-agent use. Streamable HTTP becomes
interesting when multiple agents or editors need to attach to the same Serena
server without spawning duplicate servers or stale language-server processes.

### 7. Treat Marketplace Serena Installs As Secondary

Serena's README warns that MCP/plugin marketplace commands can be outdated.
This toolkit should prefer Serena's official setup commands and direct config
snippets over marketplace copies.

## Next Implementation Backlog

1. Extend `agent-self-install.sh` to install `.agents/skills/codebase-tool-router/SKILL.md`.
2. Add doctor checks for client config snippets:
   - Codex `startup_timeout_sec`;
   - Claude `.mcp.json`;
   - Cursor `.cursor/mcp.json`;
   - project-local skill presence.
3. Add a Claude hooks example using Serena's `serena-hooks` commands.
4. Consider a Streamable HTTP profile for shared multi-agent Serena sessions.
