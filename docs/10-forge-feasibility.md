# 10 — Feasibility: an architect-oriented forge ("KimBim Hub")

**Status: Future.** This is not part of the MVP. It is a feasibility study to choose a direction early, so that MVP decisions don't block it.

## The idea

GitHub and GitLab are built for software developers: code review of text, CI pipelines, issues about bugs. Architects need a web place where a project's model lives and where the people around it can work:

- Architects, consultants, clients and contractors, most of whom will never install KimBim.
- **See** the model and drawings in the browser.
- **Review** design options ("proposals") visually, with comments pinned to objects and viewpoints.
- **Approve** milestones (Concept → Schematic → DD → Tender → Construction).
- **Issue** drawing sets (transmittals, sheet register, revisions).
- **Coordinate** with BCF issues, IDS reports and clash results.
- **Control** who may change what (discipline rules, enforced at push time; see [08](08-future.md#security-and-permissions)).

The KimBim desktop app stays the primary authoring interface ([00](00-vision-and-scope.md)). The forge is a **web portal for collaboration and review**. That doesn't conflict with the "native, not web" principle, which applies to authoring.

## Options compared

### A. Fork GitLab (owner's suggestion)

| Aspect | Assessment |
|--------|------------|
| License | Community Edition is **MIT**. The `ee/` directory is proprietary ("source available") and must be excluded (`FOSS_ONLY=1`). Our additions could be licensed AGPL. |
| What you get | A very complete forge: merge requests, CI/CD, issues, wikis, LFS, groups, permissions, API |
| Technology | Ruby on Rails monolith + Vue frontend + Go services (Gitaly, Workhorse) + PostgreSQL + Redis + Sidekiq |
| Size and pace | One of the largest open-source Rails codebases; GitLab ships a release every month |
| Hosting cost | Heavy. It needs a dedicated server with multiple cores and several GB of RAM, even for small teams |
| Fork maintenance | **Very high.** Every custom change must be rebased onto monthly upstream releases across a huge, fast-moving codebase. The only sustained precedent (JiHu, GitLab's China edition) is run by a funded company with GitLab's cooperation. |
| Architect UX | The whole UI is developer-oriented. Making it feel like an architecture tool means changing most screens, which makes the maintenance problem worse |
| Fit with KimBim | Poor. It uses a different stack (Ruby) from our team's (Rust/C++/Python), it's centralized and heavy, and some features we'd want are EE-only and off-limits |

**Verdict: technically possible, but not recommended.** It's the most expensive option to build and by far the most expensive to keep alive.

### B. Fork Forgejo

| Aspect | Assessment |
|--------|------------|
| License | **GPL-3.0-or-later** (since v9). It matches KimBim's license and copyleft goal ([06](06-reuse-and-licensing.md)) |
| What you get | Repos, pull requests, issues, milestones, wikis, LFS, Actions-compatible CI, API, organizations/teams, server hooks |
| Technology | Go, single binary, Go templates + light JS; SQLite/PostgreSQL/MySQL |
| Hosting cost | Very light. It runs on a small VPS or an office NAS, which suits small architecture practices |
| Governance | Community-owned, stewarded by Codeberg e.V. (non-profit) |
| Philosophy fit | **Federation (ActivityPub/ForgeFed)** is being developed. That matches KimBim's decentralized, local-first design ([08](08-future.md)) |
| Fork maintenance | Moderate, and far smaller than GitLab. Changes can also be **upstreamed** when they are generally useful |

**Verdict: the right base if a fork is ever needed.**

### C. No fork: KimBim Hub as an add-on service on an unmodified forge (recommended first step)

```text
┌─────────────────────┐   API + webhooks   ┌──────────────────────────┐
│ Forgejo (unmodified)│◄──────────────────►│ KimBim Hub (our service) │
│ repos, auth, PRs,   │                    │ architect web UI         │
│ issues, LFS, hooks  │                    │ 3D/drawing viewer        │
└─────────┬───────────┘                    │ workers: semantic diff,  │
          │ git push/pull                  │ previews, IDS, clash     │
┌─────────▼───────────┐                    └──────────────────────────┘
│ KimBim desktop app  │
└─────────────────────┘
```

- The forge does what forges do well: storage, auth, permissions, transport, hooks.
- **KimBim Hub** is a separate web app (AGPL-3.0, per [06](06-reuse-and-licensing.md#kimbim-license)) that provides the architect experience. It reads repos through the forge API and runs KimBim's Rust engine in **workers** to produce:
  - semantic diffs ("12 walls moved, 3 doors changed fire rating");
  - viewer-ready geometry and drawing PDFs per commit (cached, keyed by tree hash);
  - IDS and clash reports, stored as Git notes or Hub data and shown as status on proposals.
- It can work with **Forgejo first**, and later also with GitLab or GitHub through their APIs, because it never modifies the forge.
- Fork Forgejo (option B) only for things the API cannot do. Before forking, try to upstream those changes.

**Verdict: recommended — Decided (D33).** It has the lowest maintenance, needs no fork, and reuses the KimBim engine. Any piece can later move into a Forgejo fork if needed.

## Architect-oriented features (Hub backlog sketch)

| Feature | Built on |
|---------|----------|
| Browser 3D viewer of any version | IFC exported per commit + **web-ifc / That Open Engine** (MPL-2.0) or IfcOpenShell WASM |
| Visual compare of two versions (colored added/changed/removed) | KimBim semantic diff (Rust worker) |
| Proposals (pull requests) with visual review and approvals | Forge PRs + Hub UI |
| Comments pinned to objects / viewpoints | **BCF** (IfcOpenShell `bcf`), stored in repo |
| Project phases and approvals (Concept, Schematic, DD, Tender…) | Forge milestones + signed tags |
| Drawing register, sheet revisions, transmittals / issue sets | Drawing PDFs generated per tag |
| Validation status on proposals (IDS, clash, schema) | Forge commit statuses + Hub workers |
| Discipline / ownership rules enforced on push | Forge server hooks running `kimbim` checks |
| Read-only share links for clients | Hub |
| Spanish / English UI | Same i18n policy as the app (D29) |

## What the MVP must do to keep this possible

These are already true:

- Projects are standard Git repos ([03](03-versioning.md)), so any forge can host them today.
- The `kimbim` CLI and engine run headless, so they can run as forge hooks and workers.
- Validation reports and issues are kept in-repo or in Git notes, not in app-local state.

Additional rule: **keep the Rust engine free of desktop dependencies** (no Qt in `crates/`), so it can run on a Linux server.

## Rough effort (no timeline, relative sizes)

| Option | Initial build | Ongoing maintenance |
|--------|---------------|---------------------|
| A. GitLab fork | Very large | Very large (monthly rebases on a huge codebase) |
| B. Forgejo fork | Large | Moderate |
| C. Hub on unmodified Forgejo | Medium | Low (stable public API) |

## Recommendation

1. MVP: host the project and test repos on **GitHub** as plain Git (D32).
2. After the MVP: build **KimBim Hub** as option C on unmodified **Forgejo**.
3. Fork Forgejo (B) only for proven needs the API can't meet, and upstream what's generally useful.
4. Don't fork GitLab.
