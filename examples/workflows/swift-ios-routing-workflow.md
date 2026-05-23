# Swift/iOS Routing Workflow

1. Classify the task.
2. Select the first tool:
   - LSP/Serena for known Swift symbols.
   - LSP grouped counts for high-fanout symbols.
   - rg/fd for literals/resources/generated surfaces.
   - ast-grep for syntax-shaped patterns.
   - Xcode/plugin/build layer for runtime proof.
3. Gather a small inventory.
4. Read focused ranges.
5. Edit only after the match set is understood.
6. Verify with the correct proof layer.
7. State what was verified and what was not.

