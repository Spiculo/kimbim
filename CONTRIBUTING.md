# Contributing to KimBim

Thank you for helping. KimBim is GPL-3.0-or-later. By contributing you agree your work is released under that license.

## Setup

KimBim uses [pixi](https://pixi.sh) and conda-forge for every dependency, on Windows and Linux. The conda-forge build of IfcOpenShell is required, because it is the one that ships shared libraries ([docs/11](docs/11-spike-results.md#s1--shared-in-memory-model-c--python)).

```bash
pixi install            # create the environment
pixi run build          # build the Rust extension (kimbim._core)
pixi run test           # SPDX check + Rust tests + Python tests
pixi run fetch-corpus   # download the IFC test corpus (~95 MB, not committed)
pixi run golden         # golden-hash tests against the corpus
pixi run kimbim --help  # the CLI
```

## Rules

- **Tests first.** Write the failing test, watch it fail, then implement. Every bug fix adds a test.
- **SPDX header** on every source file: `SPDX-License-Identifier: GPL-3.0-or-later` within the first 5 lines (`pixi run check-spdx`).
- **DCO sign-off.** Every commit carries `Signed-off-by: Your Name <email>` (use `git commit -s`). It certifies the [Developer Certificate of Origin](https://developercertificate.org/): you have the right to submit the work under the project license. There is no CLA.
- **Decisions** that change the architecture are recorded in [docs/decisions.md](docs/decisions.md) before they are implemented.
- **New dependencies** must have a compatible license ([docs/06](docs/06-reuse-and-licensing.md#compatibility-rules-for-new-dependencies)) and be added to [THIRD_PARTY.md](THIRD_PARTY.md).

## Layout

| Path | What |
|------|------|
| `python/kimbim/` | Python package: IFC ↔ canonical records, project API, CLI |
| `crates/kimbim-repo/` | Rust: Git-backed record store |
| `crates/kimbim-py/` | Rust: PyO3 module `kimbim._core` |
| `tests/` | Python tests, corpus fetcher, golden hashes |
| `docs/` | Design documents and plans |
| `spikes/` | Throwaway experiments (not production code) |
