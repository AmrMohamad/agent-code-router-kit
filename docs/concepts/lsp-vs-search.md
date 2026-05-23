# LSP vs Search

LSP and search answer different questions.

## Search Answers Text Questions

Use `rg` and `fd` for:

- "Where does this string appear?"
- "Which files contain this route key?"
- "Where are localization resources?"
- "Which generated files exist?"
- "Which files mention this log message?"

Search is fast, broad, and excellent for discovery.

## LSP Answers Semantic Questions

Use SourceKit-LSP / Serena for:

- "Where is this Swift symbol defined?"
- "Which references are real references?"
- "Which type conforms to this protocol?"
- "Which overload is being used?"
- "Is this extension about the type or a nested namespace?"

LSP is the semantic layer. It can reduce false confidence, even when search is faster.

## Do Not Replace One With The Other

Bad:

```text
Search found the name, therefore it is a reference.
```

Better:

```text
Search found candidates.
LSP proves semantic identity.
Build/test proves runtime correctness.
```

## Practical Rule

```text
If you know the Swift symbol, start with LSP.
If you only know a literal string, start with search.
```

