# KimBim Documentation

KimBim is an open-source, native desktop BIM application for architects. It is IFC-native and local-first, and it has Git-style version control built in.

These documents guide development. They come from the original spec (`../doc.md`, v0.1), the answers to its review questions, and the review findings.

## Reading order

| # | Document | What it answers |
|---|----------|-----------------|
| 00 | [Vision and Scope](00-vision-and-scope.md) | What KimBim is, who it is for, what is in and out of scope |
| 01 | [Architecture](01-architecture.md) | Components, languages, process model, source layout |
| 02 | [Data Model and Canonical Format](02-data-model-and-format.md) | How BIM data is represented, identified, serialized and hashed |
| 03 | [Versioning](03-versioning.md) | Repository, commits, branches, diff, merge, import reconciliation |
| 04 | [Application Features](04-app-features.md) | The local BIM app: modeling, object data, cloning, libraries, cuts |
| 05 | [Geometry, Rendering and Drawings](05-geometry-rendering-drawings.md) | Geometry pipeline, viewport, sections, 2D drawings |
| 06 | [Reuse and Licensing](06-reuse-and-licensing.md) | What existing projects we build on, and the license rules |
| 07 | [Roadmap](07-roadmap.md) | Milestones and the order of work |
| 08 | [Future: Collaboration and Beyond](08-future.md) | Sync, live collaboration, P2P, host, security, AI (deferred) |
| 09 | [Testing and Quality](09-testing-and-quality.md) | Test corpus, round-trip, determinism, benchmarks |
| 10 | [Forge Feasibility](10-forge-feasibility.md) | An architect-oriented alternative to GitHub (future) |
| 11 | [Spike Results](11-spike-results.md) | What spikes S1–S5 measured and what they changed in the design |
| 12 | [M3 Exit](12-m3-exit.md) | The two-storey sample house, the automatic validity and interop checks, and the manual check in Bonsai + a commercial viewer |
| 13 | [Architect Feedback](13-architect-feedback.md) | The owner's first hands-on notes and what changed |
| 14 | [Tool Inventory](14-tool-inventory.md) | The tools Archicad, Revit, Vectorworks and Bonsai give architects, and which ones KimBim still lacks |
| 15 | [Scripting](15-scripting.md) | The Python console: the open model, selection, undoable edits, running scripts |
| 16 | [Parametric Objects](16-parametric-objects.md) | Customisable library objects as data: parameters, formulas, parts, anchors, the Object Editor |
| — | [Decision Log](decisions.md) | Every architectural decision and its status |
| — | [Open Questions](open-questions.md) | What is still undecided |
| — | [Glossary](glossary.md) | BIM / IFC / VCS terms |

## Status labels used in these docs

- **Decided**: agreed by the project owner. Change it only through a new entry in the decision log.
- **Proposed**: recommended and the default unless someone objects. Confirm or revise it before implementation starts.
- **Spike**: an unknown that needs a small experiment before we commit.
- **Future**: intentionally deferred. It is documented only enough to keep today's design from blocking it.

## Guiding rule

> **Reuse before build.** If an open-source project with a compatible license already does something well, KimBim integrates it, wraps it or ports from it. It does not rewrite it. See [06-reuse-and-licensing.md](06-reuse-and-licensing.md).
