# xcode-build-server

`xcode-build-server` bridges Xcode project context into SourceKit-LSP.

Without project context, SourceKit-LSP may miss imports, generated modules, scheme-specific settings, SDK settings, and cross-module references.

## Create buildServer.json

Project:

```bash
xcode-build-server config \
  -project YourApp.xcodeproj \
  -scheme "Your Scheme"
```

Workspace:

```bash
xcode-build-server config \
  -workspace YourApp.xcworkspace \
  -scheme "Your Scheme"
```

## Local File Policy

Treat `buildServer.json` as local machine context unless your team has a reason to commit it.

Recommended:

```bash
printf '\nbuildServer.json\n.compile/\n' >> .git/info/exclude
```

## Agent Rule

If LSP results are wrong or incomplete, do not guess. Check:

- whether `buildServer.json` exists;
- whether it points to the intended project/workspace and scheme;
- whether Xcode indexing is fresh;
- whether generated files exist;
- whether the agent activated the right repository root.

