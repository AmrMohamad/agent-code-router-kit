# Xcode / Plugin Proof Layer

Build, test, simulator, and runtime evidence belong to the project proof layer.

That proof layer can be:

- Xcode;
- an Xcode automation plugin;
- CI;
- a platform build system;
- a simulator or device test harness.

## Use It For

- compile success;
- unit and UI tests;
- simulator launch;
- screenshots;
- runtime logs;
- crash reproduction;
- result bundle inspection.

## Do Not Use It For Everything

The proof layer does not replace LSP semantic navigation. A build result will not tell an agent every real reference to a protocol or which overload a call selected.

Use both:

```text
LSP -> semantic identity
Xcode/plugin/build -> build/runtime proof
```

