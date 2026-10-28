# 08 — Future: Collaboration and Beyond

**Status: Future.** Nothing here is built now (owner answer 6). Each section exists so that today's design doesn't block it, and states the **constraint it puts on current work**.

## Sync between repositories

**Cheapest path:** the repository is already Git ([03](03-versioning.md)), so sync is `git fetch` / `git push` to any Git remote: a self-hosted Forgejo/Gitea, GitLab, GitHub, or a bare repo on a shared drive or LAN machine.

- `kimbim pull` today = fetch + **fast-forward** (a diverged option is refused; combine it in a design option). A merge-aware pull that runs KimBim's record merge (never Git's text merge) is the next step.
- Partial clone / sparse fetch (Git `--filter=blob:none`) lets clients download geometry blobs lazily.

**Constraint on current work:** keep everything in standard Git objects and refs, and keep no state outside the repo that collaborators need.

## Collaboration modes

**Decided (owner answer 2):** users choose a mode per project or branch.

| Mode | How it works | Conflicts |
|------|--------------|-----------|
| **Branch & merge** (Git-style) | Each person works on their own branch or clone and combines through merge | Resolved by the user at merge time ([03](03-versioning.md#merge-combine-options)) |
| **Live** (real-time) | Several people edit the same branch at once; operations stream between sessions | **Auto-merged**: last-writer-wins per attribute/property, ordered by hybrid logical clock; deletes win over edits on the same object, with a notification |

How Live fits into Git-style history:

- Live operations are **ephemeral**. Durable history is still made of commits. The session periodically (or on demand) writes a **checkpoint commit** to the shared branch, with every participant listed as co-author.
- Live ops carry **resulting values** (`SetProperty(id, pset, prop, value)`, `SetPlacement(id, matrix)`), never commands to re-execute ([02](02-data-model-and-format.md#2-replicate-results-never-re-execute-operations)). This keeps peers bit-identical.
- Presence, cursors, selections and cameras travel on the same channel and are **never** stored (spec §22).
- Candidate CRDT libraries: **Loro** or **Automerge** (MIT), mapping one map entry per (object, attribute). Alternatively, a simple server-ordered op log if a host is present.

**Constraint on current work:** every edit must already be a command that produces a change set of *resulting values* ([01](01-architecture.md#engine-boundaries)). That is exactly the payload a live op needs.

## P2P and host

- **LAN:** mDNS discovery plus direct QUIC.
- **Internet:** **iroh** (MIT/Apache, QUIC with hole-punching and relay fallback) instead of building NAT traversal ourselves.
- **Optional host / super-peer:** an always-on peer that provides a Git remote, relay, backup, indexing and validation workers. It is not the source of truth. Planned license: AGPL-3.0-or-later ([06](06-reuse-and-licensing.md#kimbim-license)).
- Transport for durable sync can be the Git protocol tunneled over the P2P connection.

## Security and permissions

**Decided (owner answer 5):** security is not a goal for now.

- The spec item "the host cannot read encrypted data" is **dropped**.
- Fine-grained permissions do not fit a model where every peer holds a full copy. Permissions are instead:
  - **local checks**: configurable pre-commit rules, for example "only change objects of discipline X";
  - **push-time checks**: server-side hooks on the remote that reject commits violating rules.
- Later, possibly: signed commits (Git already supports SSH/GPG signing), device identities, and encrypted transport (QUIC/TLS is encrypted by default).

**Constraint on current work:** none beyond keeping commits standard Git commits, which makes signing possible later.

## Validation pipelines ("BIM CI")

- Run on push at the host, or locally: schema validation, then IDS, property checks, clash, quantity checks, then a report attached to the commit (spec §40). Reports can be stored as Git notes.
- Whether failures block a merge is configurable.

## BCF issues

- Issues reference KimBim ID + GlobalId + commit + viewpoint (spec §41).
- Issues could be stored in the repo (as records or a separate ref), so they sync with the model.
- Reuse IfcOpenShell's `bcf` library (LGPL).

## AI assistance

Spec §36–38 still applies:

- AI uses **tools** over the deterministic engines (`query`, `run_ids`, `get_history`, `diff`, `propose_operations`). It is never the source of truth.
- AI changes are **proposed commands**. They go through the same command → validation → commit path, appear as a reviewable diff, and are attributed as AI-assisted.
- Execution policy: local only / company model / external / disabled.

**Constraint on current work:** the command API and the CLI are the future AI tool surface, so keep them complete and scriptable.

## Federation and linked models

- Discipline models (architecture, structure, MEP) live in separate repositories. A federation manifest pins each one to a commit (like Git submodules, but presented as "linked models").
- Cross-model references use (repository ID, KimBim ID).
- Owner request (2026-10-07), out of scope for now: open several separate models together (site, building, structure), each with its own history, and switch between them. Show one model inside another as a reference, and copy, model or modify elements across models, as with Revit links or Archicad hotlinks.
- Open questions for research:
  - One `.kim` per model, linked by path and pinned version? Or one project `.kim` that holds all models?
  - Is a referenced model read-only, or can it be edited in place?
  - What happens to copied elements' identity and history when they are copied between models?
  - How are references to a model's newer versions offered: automatically, or when the user chooses?

## Architect-oriented forge

See [10-forge-feasibility.md](10-forge-feasibility.md). Recommended: KimBim Hub as a service on top of unmodified Forgejo.

## Large assets

Point clouds, scans, images, PDFs and raw source IFCs are stored through **Git LFS** or a content-addressed side store. They are referenced from records by hash and are never inlined.

## Scale (1M+ objects)

- Renderer upgrade to Qt RHI with GPU-driven culling and LOD ([05](05-geometry-rendering-drawings.md#later-renderer-only-if-s2-or-real-usage-demands-it)).
- Partial loading by storey or zone, plus partial clone.
- Engine moved to a separate process with worker processes ([01](01-architecture.md#process-model)).
