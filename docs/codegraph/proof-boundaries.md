# CodeGraph Proof Boundaries

CodeGraph is discovery evidence only.

Use it for:

- architecture questions
- multi-file source-code flow
- static impact orientation
- Swift/Objective-C/React Native/Expo bridge discovery

Do not use it as proof for:

- exact symbol identity when Serena/LSP is available
- literal/resource lookups
- syntax migrations
- build success
- runtime correctness
- simulator or device behavior

The gateway enforces these boundaries by redirecting obvious wrong-route requests and by labeling every result as `proof_level: discovery`.
