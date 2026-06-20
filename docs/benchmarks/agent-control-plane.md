# Agent Control Plane

The control plane launches a subject agent, sends a task packet, waits for a sentinel, captures transcript and telemetry, normalizes metrics, and judges the result.

## Bridge Responsibilities

- build an adapter launch plan;
- create a unique run directory;
- write `task-packet.md`;
- capture transcript text;
- enforce timeout;
- write `telemetry.jsonl` with process/session lifecycle events;
- write normalized metrics;
- avoid destructive subject-agent routes by default.

## Adapter Responsibilities

Each adapter declares:

- agent id;
- command candidate;
- default arguments;
- environment variables;
- prompt delivery mode;
- telemetry source;
- shutdown behavior;
- live support status.

Dry-run adapters must work even if the agent CLI is not installed.

## Live Run Boundary

Live execution is only valid when:

- the adapter supports live mode;
- the route profile allows the requested proof layer;
- the repo state is recorded;
- the run has a timeout and sentinel;
- the output directory is unique.

Live telemetry records operational events without duplicating raw transcript
content: process start, spawn, prompt delivery, output byte chunks, process
exit, tmux session start/close, terminal capture changes, sentinel observation,
and timeouts. The transcript remains the source for actual agent text.
