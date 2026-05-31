# Cursor Usage

Use this policy in Cursor rules or project instructions.

Suggested rule:

```text
For Swift/iOS:
- Known symbols require semantic navigation through SourceKit-LSP or the editor language server.
- High-fanout symbols must be summarized before reading references.
- Literal and resource lookup starts with search.
- Syntax-shaped patterns use ast-grep.
- Build/runtime claims require the project build or test layer.

For Android/Kotlin:
- Known Kotlin/Java symbols require semantic navigation through Kotlin/Java LSP or the IDE language server.
- High-fanout symbols must be summarized before reading references.
- Resources, XML, generated files, and literals start with rg/fd.
- GraphQL operations/schemas start with GraphQL tools plus rg/fd.
- Syntax-shaped Kotlin patterns use ast-grep.
- Build/runtime claims require Gradle, Android Studio, emulator/device, or CI proof.
```

Cursor search is useful, but same-name Swift symbols, protocols, overloads, and extensions still need semantic navigation.
