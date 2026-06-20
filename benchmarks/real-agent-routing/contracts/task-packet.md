# RARB Task Packet v1

Run ID: `{run_id}`
Agent: `{agent}`
Route Profile: `{profile}`
Repo: `{repo}`
Task Family: `{task_family}`
Time Budget Seconds: `{timeout_seconds}`
Edit Allowed: `{edit_allowed}`
Build Allowed: `{build_allowed}`
Completion Sentinel: `{done_sentinel}`

## Objective

{prompt}

## Scope

In scope:

- answer the task from evidence;
- follow the route profile;
- state proof layer and files inspected.

Out of scope:

- hidden file edits;
- destructive commands;
- business runtime claims without required proof.

## Routing Constraints

{routing_constraints}

## Expected Proof

{expected_proof_layer}

## Response Contract

Return the `RARB Response v1` shape and end with the sentinel exactly:

```text
{done_sentinel}
```
