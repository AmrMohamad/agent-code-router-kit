# Terminal Agent Control Patterns

This review is based on the locally installed `cursor-agent-terminal-assistant`
skill at:

```text
~/.codex/skills/cursor-agent-terminal-assistant
```

The plan referenced `cursor-agent-terminal-assistant.zip`; the installed skill and zip are both present under `~/.codex/skills/`. The benchmark should reuse the control-plane ideas, not copy the Cursor-specific implementation.

## Patterns To Reuse

- Visible-first terminal control: the subject agent should run in a terminal or PTY session that can be inspected after the run.
- Stable session identity: each run needs a unique session/run id, workspace, agent id, route profile, transcript path, and telemetry path.
- Sentinel completion: every prompt must include a unique completion sentinel, and the bridge must treat missing sentinel as timeout or invalid completion.
- Response contract: the subject agent should return a machine-parseable block with status, tools used, proof layers, files opened, raw-dump incidents, policy adherence, and final answer.
- Timing ledger: record start/end timestamps, timeout state, completion reason, prompt hash, transcript hash, and answer hash.
- Permission profiles: route profiles should explicitly describe allowed tools, blocked tools, whether edits/builds are allowed, and whether a live run is safe.
- Redaction before export: transcripts and prompts must be scanned for secret-like values before reports are written.
- Advisor separation: another agent's answer is evidence to judge, not proof that the benchmark succeeded.

## Patterns To Generalize

- Cursor's `quick-ask`, `tmux-ask`, and `stream-ask` become a generic `TerminalAgentBridge` interface.
- Cursor's CRP response becomes `BENCHMARK_RESULT ... BENCHMARK_DONE`.
- Cursor permission profiles become RARB route profiles: `A-search-only`, `B-search-summary`, `C-lsp-naive`, and `D-full-router`.
- Cursor telemetry JSONL becomes normalized per-run telemetry with exact-token fields optional and proxy-token fields always present.
- Cursor session doctor becomes adapter `detect` and dry-run launch-plan checks for Codex, Claude Code, and Cursor Agent.

## What To Avoid

- Do not make the benchmark Cursor-only.
- Do not depend on macOS Terminal UI automation for dry-run or CI validation.
- Do not trust a subject agent to self-report correctness without an external judge record.
- Do not allow destructive commands or hidden subject-agent writes in the first version.
- Do not mix exact token telemetry with proxy token estimates silently.
- Do not treat a launch/build/runtime smoke as business-flow proof.

## Current Boundary

The implementation now has PTY and tmux-backed live bridge modes for Codex,
Claude Code, and Cursor Agent adapters, plus subprocess mode for deterministic
tests. `--terminal-mode tmux` creates a named tmux session, sends the prompt,
waits for the sentinel, keeps a short post-sentinel capture window for trailing
structured usage events, captures the pane transcript, and cleans up the
session.
Live execution is still gated behind explicit `--live`, command availability,
clean-repo checks unless overridden, per-run sentinels, and route isolation
records. Per-run `telemetry.jsonl` now includes non-secret lifecycle events for
process/session start, prompt delivery, output byte chunks, exits, tmux capture
changes, sentinel observation, post-sentinel capture completion, and timeouts.
Dry-run output remains harness proof only.
