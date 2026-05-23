# Agent Self-Install Playbook

This playbook is for an AI coding agent that has been asked to install the
Swift/iOS routing policy into a local repo. It is intentionally conservative:
the default scripted path is read-only, and any file-writing step requires an
explicit `--apply`.

The goal is to install the policy, not to change Xcode state, run builds, run
tests, alter global developer paths, or overwrite an existing project setup.

## What Gets Installed

The system has four layers:

1. Project policy:
   `templates/AGENTS.md`
2. Agent skill or reusable instruction:
   `templates/codebase-tool-router/SKILL.md`
3. Swift/iOS project context:
   `buildServer.json` created by `xcode-build-server`
4. Verification discipline:
   benchmark validation plus explicit proof boundaries

The routing rule is:

```text
Known Swift symbol:
  SourceKit-LSP / Serena first.

High-fanout Swift symbol:
  LSP grouped counts first.
  Never dump full references.

Literal/resource/generated lookup:
  rg / fd first.

Structural Swift pattern:
  ast-grep first.

Build/test/runtime proof:
  Xcode/plugin/build system only.
```

## Non-Mutating First Pass

From the toolkit repo:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/ios-repo \
  --agent codex \
  --dry-run
```

This checks:

- toolkit files exist;
- local commands are available;
- benchmark manifest is valid;
- target repo exists;
- project policy destination status;
- Codex skill destination status when `--agent codex` is used;
- optional `buildServer.json` command shape when project/workspace and scheme are provided.

It does not copy files, create `buildServer.json`, edit git excludes, install
packages, invoke `sudo`, run Xcode builds, run tests, or start simulators.

## Apply The Safe Install

Use `--apply` only after the dry run is clean.

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/ios-repo \
  --agent codex \
  --apply
```

Apply mode is still non-destructive:

- if the target repo has no `AGENTS.md`, the template is copied to `AGENTS.md`;
- if `AGENTS.md` already exists, it is left unchanged and the template is
  written to `.agent-code-router/AGENTS.fragment.md` for manual review;
- if the Codex skill destination does not exist, the skill is copied there;
- if the Codex skill destination exists and differs, the script refuses to
  overwrite it unless `--overwrite` is provided;
- no build, test, simulator, or Xcode GUI action is performed.

## Optional buildServer.json

To include the `xcode-build-server` step, provide a project or workspace and a
scheme, then opt into build-server configuration:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/ios-repo \
  --agent codex \
  --workspace YourApp.xcworkspace \
  --scheme "Your Scheme" \
  --configure-build-server \
  --apply
```

or:

```bash
./scripts/setup/agent-self-install.sh \
  --target-repo /path/to/ios-repo \
  --agent codex \
  --project YourApp.xcodeproj \
  --scheme "Your Scheme" \
  --configure-build-server \
  --apply
```

This creates or updates `buildServer.json` by calling:

```bash
xcode-build-server config -workspace YourApp.xcworkspace -scheme "Your Scheme"
```

or:

```bash
xcode-build-server config -project YourApp.xcodeproj -scheme "Your Scheme"
```

It does not run `xcodebuild`, does not build, and does not test. After this
step, build once through the user's normal Xcode/plugin/CI proof layer when
runtime or compile proof is actually needed.

## Agent Rules During Install

An AI agent installing this system should follow these rules:

1. Start with `--dry-run`.
2. Do not run package managers unless the user explicitly asks.
3. Do not use `sudo`.
4. Do not change the global Xcode developer path.
5. Do not overwrite existing `AGENTS.md`, skill files, or agent config.
6. Do not run build/test/simulator commands as part of install.
7. Keep `buildServer.json` machine-local unless the repo intentionally tracks it.
8. Report exactly what was changed and what was only checked.

## Exact Agent Prompt

Use this prompt when asking an agent to install the system:

```text
Install agent-code-router-kit into this Swift/iOS repo safely.

Rules:
- Start with scripts/setup/agent-self-install.sh --dry-run.
- Do not use sudo.
- Do not change global Xcode developer path.
- Do not overwrite existing project or agent config.
- Do not run builds, tests, or simulators during install.
- If AGENTS.md exists, create a review fragment instead of replacing it.
- Configure buildServer.json only when project/workspace and scheme are explicit.
- After install, report changed files, skipped files, verification checks, and next manual step.
```

## Completion Checklist

The install is complete only when:

- prerequisites were checked;
- benchmark manifest validation passed;
- project policy was installed or a review fragment was created;
- Codex skill or agent instruction was installed or clearly skipped;
- optional `buildServer.json` was created only when explicitly requested;
- no build/runtime proof was claimed;
- the final report separates modified files from read-only checks.
