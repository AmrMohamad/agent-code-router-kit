# SourceKit-LSP Setup For Swift/iOS Agents

SourceKit-LSP is the Swift semantic engine. It gives an agent definitions, references, symbols, hover/type information, and diagnostics.

General flow:

```text
Codex/Agent
  -> Serena or SourceKit-LSP tool wrapper
  -> SourceKit-LSP
  -> buildServer.json from xcode-build-server
  -> Xcode project context
```

## Install Tools

```bash
brew install xcode-build-server fd ripgrep ast-grep
```

If you use Serena as the agent-facing semantic layer, install it using its current official instructions.

## Configure Xcode Project Context

For a project:

```bash
xcode-build-server config \
  -project YourApp.xcodeproj \
  -scheme "Your Scheme"
```

For a workspace:

```bash
xcode-build-server config \
  -workspace YourApp.xcworkspace \
  -scheme "Your Scheme"
```

This writes `buildServer.json` in the workspace root.

## Keep buildServer.json Local

`buildServer.json` is often machine-local. Keep it out of commits unless your team intentionally shares it.

```bash
mkdir -p .git/info
grep -qxF 'buildServer.json' .git/info/exclude 2>/dev/null || \
  printf '\nbuildServer.json\n.compile/\n' >> .git/info/exclude
```

## Freshness

If LSP results look stale:

1. Check `buildServer.json`.
2. Check scheme and workspace/project selection.
3. Build or index through your Xcode/plugin/build layer.
4. Retry the targeted LSP query.

