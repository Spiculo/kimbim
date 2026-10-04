# Slice 1: Versioned IFC from the Command Line (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `kimcad` CLI that turns IFC files into versions in a Git-backed KIMCAD repository. You can commit an IFC, see status, log and diff at the record level, and export any version back to IFC, with results byte-identical to the spike golden hashes.

**Architecture:**
- **Python package `kimcad`.** It ports the validated spike decomposer (`spikes/s3_records/records.py`), owns all IFC work through ifcopenshell, and drives the CLI.
- **Rust crate `kimcad-repo`.** It owns storage: writes go through `git fast-import` (pack-only), reads through gitoxide.
- **PyO3 module `kimcad._core`.** It exposes the Rust crate to Python. This is the first of the two planned boundaries; the C++ `cxx` bridge comes with the GUI.
- **Environment.** pixi + conda-forge provide everything on Windows and Linux.

**Tech Stack:** Python 3.12, ifcopenshell 0.9.0, blake3, pytest; Rust (edition 2024), gix 0.88, rayon, thiserror, PyO3 + maturin; git ≥ 2.45; pixi; GitHub Actions.

**Spec:** `docs/02-data-model-and-format.md`, `docs/03-versioning.md`, `docs/11-spike-results.md` (decisions D34–D39), roadmap milestones R0–R2 in `docs/07-roadmap.md`.

## Global Constraints

- License `GPL-3.0-or-later`. Every source file starts with `SPDX-License-Identifier: GPL-3.0-or-later` (D08).
- Platforms: Windows and Linux (D03). CI runs both.
- ifcopenshell **0.9.0 from conda-forge**, never the pip wheel (D37).
- Record format tag `kimcad/1`. Record keys `o/<GlobalId>`, `n/<node-id>`, `l/<hash>`, `meta` (D34).
- Canonical JSON: sorted keys, no whitespace, UTF-8, strings not normalized, INTEGER vs REAL distinct, SETs sorted (D35).
- Storage: packs only (`git fast-import`), never loose blobs. Repack without deltas after large writes (> 10,000 changed records) (D39).
- The repository is a standard Git repo at `<project>/.git` with `core.bare = true`. Records are never checked out (doc 03).
- No silent schema conversion: committing a file whose schema differs from the project's is an error (D30).
- Import refuses schema-invalid input that cannot be written back, and reports validation messages (D36).
- Deterministic: the same IFC gives the same records and hashes on Windows and Linux (S4).

## Review Focus

1. **Different schema.** Committing an IFC4X3 file into an IFC2X3/IFC4 project must fail with a clear message and leave the repo unchanged. Test: Task 6.
2. **Unchanged file.** Committing an IFC identical to HEAD must say "nothing to commit" and create no version. Test: Task 6.
3. **Empty project.** `log`/`diff`/`export` on a project with no versions must print a clear message and exit 1, with no traceback. Test: Task 7.
4. **Schema-invalid input.** A file that ifcopenshell reads but cannot write must be refused with validation messages, leaving the repo unchanged. Test: Task 6.
5. **Existing export target.** Exporting onto an existing file must refuse unless `--force`. Paths with spaces and non-ASCII (`Proyecto ñ`) must work. Test: Task 6 and Task 7.

---

## File Structure

```text
pixi.toml                         # env + tasks (build, test, golden, fetch-corpus, check-spdx)
pyproject.toml                    # maturin build of kimcad + kimcad._core, pytest config
Cargo.toml                        # Rust workspace (excludes spikes/)
CONTRIBUTING.md                   # DCO, SPDX, how to build/test
THIRD_PARTY.md                    # dependency licenses
tools/check_spdx.py               # SPDX header check
crates/kimcad-repo/               # Rust: git-backed record store
  Cargo.toml, src/lib.rs, tests/repo.rs
crates/kimcad-py/                 # Rust: PyO3 module kimcad._core
  Cargo.toml, src/lib.rs
python/kimcad/
  __init__.py                     # version
  records.py                      # decompose/compose (from spike), canonical JSON, hashes
  layout.py                       # record key <-> git path, git blob oid
  nodeids.py                      # stable node ids across versions
  project.py                      # Project: init/open/commit/status/log/diff/export/show/branches
  cli.py                          # argparse CLI `kimcad`
tests/python/
  conftest.py                     # tiny IFC fixtures built with ifcopenshell.api
  semantic.py                     # independent semantic comparison (from spike)
  test_core.py test_records.py test_layout.py test_nodeids.py
  test_project.py test_cli.py test_golden.py test_e2e.py
tests/corpus/fetch.py             # corpus download (files gitignored)
tests/golden/manifest-*.json      # golden hashes (from spikes/s3_records/golden)
.github/workflows/ci.yml
```

---

### Task 1: Foundations (pixi, workspace skeleton, SPDX, contributing)

**Files:**
- Create: `pixi.toml`, `pyproject.toml`, `Cargo.toml`, `CONTRIBUTING.md`, `THIRD_PARTY.md`, `tools/check_spdx.py`, `python/kimcad/__init__.py`, `tests/python/test_smoke.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `pixi run <task>` for `build`, `test-rust`, `test-py`, `test`, `golden`, `fetch-corpus`, `check-spdx`. Package `kimcad` with `kimcad.__version__ == "0.1.0"`.

- [ ] **Step 1: Write the failing smoke test** `tests/python/test_smoke.py`

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import ifcopenshell


def test_ifcopenshell_is_conda_forge_0_9():
    assert ifcopenshell.version.startswith("0.9.0")


def test_package_version():
    import kimcad

    assert kimcad.__version__ == "0.1.0"
```

- [ ] **Step 2: Create `pixi.toml`**

```toml
[workspace]
name = "kimcad"
channels = ["conda-forge"]
platforms = ["win-64", "linux-64"]

[dependencies]
python = "3.12.*"
ifcopenshell = "0.9.0.*"
blake3 = ">=1.0"
numpy = "*"
maturin = ">=1.15,<2"
pytest = ">=8"
rust = ">=1.85"
git = ">=2.45"

[tasks]
build = "maturin develop --release --skip-install"
check-spdx = "python tools/check_spdx.py"
test-rust = "cargo test --workspace"
test-py = { cmd = "pytest", depends-on = ["build"] }
test = { depends-on = ["check-spdx", "test-rust", "test-py"] }
fetch-corpus = "python tests/corpus/fetch.py"
golden = { cmd = "pytest -m golden", depends-on = ["build"] }
```

`--skip-install` builds `_core` in place into `python/kimcad/`. pytest finds the package through `pythonpath = ["python"]` (below), so pip never pulls PyPI wheels over the conda packages.

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[build-system]
requires = ["maturin>=1.15,<2"]
build-backend = "maturin"

[project]
name = "kimcad"
version = "0.1.0"
description = "Open-source native BIM for architects, with version control built in"
license = "GPL-3.0-or-later"
requires-python = ">=3.11"
# Runtime deps (ifcopenshell, blake3) come from conda-forge via pixi; not listed for pip.

[project.scripts]
kimcad = "kimcad.cli:main"

[tool.maturin]
python-source = "python"
module-name = "kimcad._core"
manifest-path = "crates/kimcad-py/Cargo.toml"
features = ["pyo3/extension-module"]

[tool.pytest.ini_options]
testpaths = ["tests/python"]
pythonpath = ["python", "tests/python"]
markers = [
  "golden: needs the downloaded corpus (pixi run fetch-corpus)",
  "slow: large models, minutes",
]
addopts = "-m 'not golden and not slow'"
```

- [ ] **Step 4: Create the root `Cargo.toml`**

```toml
[workspace]
resolver = "3"
members = ["crates/kimcad-repo", "crates/kimcad-py"]
exclude = ["spikes"]

[workspace.package]
version = "0.1.0"
edition = "2024"
license = "GPL-3.0-or-later"
```

The member crates are created in Tasks 2–3. Until then, Step 8 runs only `check-spdx` and the Python smoke test.

- [ ] **Step 5: Create `python/kimcad/__init__.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""KIMCAD: open-source native BIM for architects, with version control built in."""

__version__ = "0.1.0"
```

- [ ] **Step 6: Create `tools/check_spdx.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail if a source file lacks the SPDX header in its first 5 lines."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIRS = ["python", "crates", "tests", "tools"]
EXTS = {".py", ".rs"}
TAG = "SPDX-License-Identifier: GPL-3.0-or-later"
SKIP_PARTS = {"target", "__pycache__", "files"}


def main() -> int:
    missing = []
    for d in DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix in EXTS and not SKIP_PARTS & set(p.parts):
                head = p.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
                if not any(TAG in line for line in head):
                    missing.append(p.relative_to(ROOT))
    for m in missing:
        print(f"missing SPDX header: {m}")
    print("SPDX OK" if not missing else f"{len(missing)} file(s) missing SPDX header")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Create `CONTRIBUTING.md` and `THIRD_PARTY.md`; extend `.gitignore`**

`CONTRIBUTING.md` must cover:
- setup (`pixi install`, `pixi run build`, `pixi run test`, `pixi run fetch-corpus`, `pixi run golden`);
- the SPDX header rule;
- DCO: every commit carries `Signed-off-by:` (`git commit -s`);
- tests first.

`THIRD_PARTY.md` is a table of the dependencies in `pixi.toml` and the Rust crates, with license and how each is linked:
- ifcopenshell LGPL-3.0-or-later (dynamic);
- blake3 Apache-2.0/CC0;
- gix MIT/Apache-2.0;
- PyO3 MIT/Apache-2.0;
- rayon MIT/Apache-2.0;
- thiserror MIT/Apache-2.0;
- git GPL-2.0 (separate program);
- Python PSF;
- maturin MIT/Apache-2.0.

`.gitignore` additions:

```text
/.pixi/
/tests/corpus/files/
/python/kimcad/_core*.pyd
/python/kimcad/_core*.so
```

- [ ] **Step 8: Run**

Run: `pixi install` then `pixi run check-spdx` then `pixi run pytest tests/python/test_smoke.py -q -p no:cacheprovider`
Expected: `SPDX OK`, 2 passed. Before the crates exist, run pytest directly, not `test-py`.

- [ ] **Step 9: Commit**

```bash
git add pixi.toml pixi.lock pyproject.toml Cargo.toml CONTRIBUTING.md THIRD_PARTY.md tools python tests .gitignore
git commit -s -m "build: pixi environment, workspace skeleton, SPDX check, contributing guide"
```

---

### Task 2: Rust record store `kimcad-repo`

**Files:**
- Create: `crates/kimcad-repo/Cargo.toml`, `crates/kimcad-repo/src/lib.rs`, `crates/kimcad-repo/tests/repo.rs`

**Interfaces:**
- Produces (Rust, used by Task 3):
  - `Repo::init(project: &Path) -> Result<Repo>` creates a bare repo at `<project>/.git` with HEAD → `refs/heads/main`.
  - `Repo::open(project: &Path) -> Result<Repo>`
  - `head(&self) -> Result<Option<String>>` (commit hex, `None` when unborn)
  - `current_branch(&self) -> Result<String>`
  - `resolve(&self, rev: &str) -> Result<String>` (any git rev-spec: `HEAD`, `HEAD~1`, branch, tag, hex prefix)
  - `tree_entries(&self, rev: &str) -> Result<BTreeMap<String, String>>` (blob path → blob hex, recursive)
  - `read_blobs(&self, oids: &[String]) -> Result<Vec<Vec<u8>>>` (parallel)
  - `commit(&self, changes: &BTreeMap<String, Option<Vec<u8>>>, message: &str, author: &Signature) -> Result<String>` (`None` = delete; returns new commit hex)
  - `log(&self, rev: &str, limit: usize) -> Result<Vec<CommitInfo>>` (first-parent, newest first)
  - `branches(&self) -> Result<Vec<String>>`, `create_branch(&self, name: &str, rev: &str) -> Result<()>`, `switch(&self, name: &str) -> Result<()>`
  - `repack_no_delta(&self) -> Result<()>`
  - `pub struct Signature { pub name: String, pub email: String, pub time: i64 }`
  - `pub struct CommitInfo { pub id, pub parents: Vec<String>, pub author_name, pub author_email, pub time: i64, pub message }`
  - `pub enum Error { NotARepo, AlreadyExists, UnknownRev, InvalidPath, InvalidOid, UnknownBranch, Git, Io }`

- [ ] **Step 1: Write failing integration tests** `crates/kimcad-repo/tests/repo.rs`

```rust
// SPDX-License-Identifier: GPL-3.0-or-later
use std::collections::BTreeMap;

use kimcad_repo::{Error, Repo, Signature};

fn sig(t: i64) -> Signature {
    Signature { name: "Test".into(), email: "test@example.org".into(), time: t }
}

fn changes(items: &[(&str, Option<&str>)]) -> BTreeMap<String, Option<Vec<u8>>> {
    items.iter().map(|(p, v)| (p.to_string(), v.map(|s| s.as_bytes().to_vec()))).collect()
}

#[test]
fn init_open_and_unborn_head() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    assert_eq!(repo.head().unwrap(), None);
    assert_eq!(repo.current_branch().unwrap(), "main");
    assert!(matches!(Repo::init(dir.path()), Err(Error::AlreadyExists(_))));
    Repo::open(dir.path()).unwrap();
    let other = tempfile::tempdir().unwrap();
    assert!(matches!(Repo::open(other.path()), Err(Error::NotARepo(_))));
}

#[test]
fn commit_read_modify_delete_log() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    let c1 = repo
        .commit(&changes(&[("objects/ab/W1.json", Some("{\"a\":1}")), ("kimcad.json", Some("{}"))]), "first", &sig(1_790_000_000))
        .unwrap();
    assert_eq!(repo.head().unwrap().as_deref(), Some(c1.as_str()));
    let e1 = repo.tree_entries("HEAD").unwrap();
    assert_eq!(e1.keys().cloned().collect::<Vec<_>>(), vec!["kimcad.json", "objects/ab/W1.json"]);
    let blobs = repo.read_blobs(&[e1["objects/ab/W1.json"].clone()]).unwrap();
    assert_eq!(blobs[0], b"{\"a\":1}");

    let c2 = repo
        .commit(&changes(&[("objects/ab/W1.json", Some("{\"a\":2}")), ("kimcad.json", None), ("nodes/cd/N1.json", Some("[]"))]), "second", &sig(1_790_000_100))
        .unwrap();
    let e2 = repo.tree_entries("HEAD").unwrap();
    assert_eq!(e2.keys().cloned().collect::<Vec<_>>(), vec!["nodes/cd/N1.json", "objects/ab/W1.json"]);
    assert_eq!(repo.resolve("HEAD~1").unwrap(), c1);

    let log = repo.log("HEAD", 10).unwrap();
    assert_eq!(log.iter().map(|c| c.message.trim().to_string()).collect::<Vec<_>>(), vec!["second", "first"]);
    assert_eq!(log[0].id, c2);
    assert_eq!(log[0].parents, vec![c1.clone()]);
    assert_eq!(log[0].author_email, "test@example.org");
    assert_eq!(log[0].time, 1_790_000_100);
}

#[test]
fn branches_and_switch() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    repo.commit(&changes(&[("a.json", Some("1"))]), "base", &sig(1)).unwrap();
    repo.create_branch("option-b", "HEAD").unwrap();
    repo.switch("option-b").unwrap();
    assert_eq!(repo.current_branch().unwrap(), "option-b");
    repo.commit(&changes(&[("a.json", Some("2"))]), "on b", &sig(2)).unwrap();
    assert_eq!(repo.branches().unwrap(), vec!["main", "option-b"]);
    repo.switch("main").unwrap();
    assert_eq!(repo.read_blobs(&[repo.tree_entries("HEAD").unwrap()["a.json"].clone()]).unwrap()[0], b"1");
    assert!(matches!(repo.switch("nope"), Err(Error::UnknownBranch(_))));
}

#[test]
fn rejects_bad_paths_and_revs() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    for bad in ["", "/abs.json", "a/../b.json", "a//b.json", "a\nb.json", ".git/x"] {
        let r = repo.commit(&changes(&[(bad, Some("1"))]), "x", &sig(1));
        assert!(matches!(r, Err(Error::InvalidPath(_))), "accepted {bad:?}");
    }
    assert!(matches!(repo.resolve("does-not-exist"), Err(Error::UnknownRev(_))));
    assert!(matches!(repo.read_blobs(&["zz".into()]), Err(Error::InvalidOid(_))));
}

#[test]
fn paths_with_spaces_and_unicode_work() {
    let dir = tempfile::tempdir().unwrap();
    let project = dir.path().join("Proyecto ñ");
    std::fs::create_dir(&project).unwrap();
    let repo = Repo::init(&project).unwrap();
    repo.commit(&changes(&[("objects/0f/2O2Fr$t4X7Zf8NOew3FLOH.json", Some("{}"))]), "ñandú", &sig(1)).unwrap();
    assert!(repo.tree_entries("HEAD").unwrap().contains_key("objects/0f/2O2Fr$t4X7Zf8NOew3FLOH.json"));
    assert_eq!(repo.log("HEAD", 1).unwrap()[0].message.trim(), "ñandú");
}
```

- [ ] **Step 2: Create `crates/kimcad-repo/Cargo.toml` and run the tests to see them fail**

```toml
[package]
name = "kimcad-repo"
version.workspace = true
edition.workspace = true
license.workspace = true

[dependencies]
gix = "0.88"
rayon = "1"
thiserror = "2"

[dev-dependencies]
tempfile = "3"
```

Run: `pixi run cargo test -p kimcad-repo`
Expected: compile errors (`Repo` not found).

- [ ] **Step 3: Implement `crates/kimcad-repo/src/lib.rs`**

```rust
// SPDX-License-Identifier: GPL-3.0-or-later
//! Git-backed record store for KIMCAD (docs/03-versioning.md, D39).
//!
//! Writes go through `git fast-import` (one pack per commit, never loose objects).
//! Reads use gitoxide. The repository lives at `<project>/.git` with `core.bare = true`;
//! records are never checked out.
use std::collections::BTreeMap;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use rayon::prelude::*;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("not a KIMCAD project (no .git found): {0}")]
    NotARepo(PathBuf),
    #[error("a repository already exists at {0}")]
    AlreadyExists(PathBuf),
    #[error("unknown revision: {0}")]
    UnknownRev(String),
    #[error("unknown branch: {0}")]
    UnknownBranch(String),
    #[error("invalid record path: {0:?}")]
    InvalidPath(String),
    #[error("invalid object id: {0}")]
    InvalidOid(String),
    #[error("git: {0}")]
    Git(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone)]
pub struct Signature {
    pub name: String,
    pub email: String,
    /// Seconds since the Unix epoch, UTC.
    pub time: i64,
}

#[derive(Debug, Clone)]
pub struct CommitInfo {
    pub id: String,
    pub parents: Vec<String>,
    pub author_name: String,
    pub author_email: String,
    pub time: i64,
    pub message: String,
}

pub struct Repo {
    git_dir: PathBuf,
}

fn git_err(e: impl std::fmt::Display) -> Error {
    Error::Git(e.to_string())
}

impl Repo {
    pub fn init(project: &Path) -> Result<Repo> {
        let git_dir = project.join(".git");
        if git_dir.exists() {
            return Err(Error::AlreadyExists(git_dir));
        }
        gix::init_bare(&git_dir).map_err(git_err)?;
        std::fs::write(git_dir.join("HEAD"), "ref: refs/heads/main\n")?;
        Ok(Repo { git_dir })
    }

    pub fn open(project: &Path) -> Result<Repo> {
        let git_dir = project.join(".git");
        if !git_dir.join("HEAD").is_file() {
            return Err(Error::NotARepo(project.to_path_buf()));
        }
        Ok(Repo { git_dir })
    }

    fn gix(&self) -> Result<gix::Repository> {
        let mut r = gix::open(&self.git_dir).map_err(git_err)?;
        r.object_cache_size_if_unset(64 << 20);
        Ok(r)
    }

    fn git(&self) -> Command {
        let mut c = Command::new("git");
        c.env("GIT_DIR", &self.git_dir);
        c
    }

    pub fn current_branch(&self) -> Result<String> {
        let head = std::fs::read_to_string(self.git_dir.join("HEAD"))?;
        head.trim()
            .strip_prefix("ref: refs/heads/")
            .map(str::to_string)
            .ok_or_else(|| Error::Git("HEAD is detached".into()))
    }

    pub fn head(&self) -> Result<Option<String>> {
        let repo = self.gix()?;
        let name = format!("refs/heads/{}", self.current_branch()?);
        match repo.try_find_reference(name.as_str()).map_err(git_err)? {
            Some(mut r) => Ok(Some(r.peel_to_id().map_err(git_err)?.to_string())),
            None => Ok(None),
        }
    }

    pub fn resolve(&self, rev: &str) -> Result<String> {
        let repo = self.gix()?;
        let id = repo.rev_parse_single(rev).map_err(|_| Error::UnknownRev(rev.to_string()))?;
        let commit = id.object().map_err(git_err)?.peel_to_commit().map_err(|_| Error::UnknownRev(rev.to_string()))?;
        Ok(commit.id.to_string())
    }

    pub fn tree_entries(&self, rev: &str) -> Result<BTreeMap<String, String>> {
        let repo = self.gix()?;
        let id = gix::ObjectId::from_hex(self.resolve(rev)?.as_bytes()).map_err(git_err)?;
        let tree = repo.find_commit(id).map_err(git_err)?.tree().map_err(git_err)?;
        let mut rec = gix::traverse::tree::Recorder::default();
        tree.traverse().breadthfirst(&mut rec).map_err(git_err)?;
        Ok(rec
            .records
            .into_iter()
            .filter(|e| e.mode.is_blob())
            .map(|e| (e.filepath.to_string(), e.oid.to_string()))
            .collect())
    }

    pub fn read_blobs(&self, oids: &[String]) -> Result<Vec<Vec<u8>>> {
        let ids = oids
            .iter()
            .map(|h| gix::ObjectId::from_hex(h.as_bytes()).map_err(|_| Error::InvalidOid(h.clone())))
            .collect::<Result<Vec<_>>>()?;
        let sync = self.gix()?.into_sync();
        ids.par_iter()
            .map_init(
                || sync.to_thread_local(),
                |r, id| r.find_object(*id).map(|o| o.data.clone()).map_err(git_err),
            )
            .collect()
    }

    pub fn commit(&self, changes: &BTreeMap<String, Option<Vec<u8>>>, message: &str, author: &Signature) -> Result<String> {
        for path in changes.keys() {
            validate_path(path)?;
        }
        let branch = self.current_branch()?;
        let parent = self.head()?;
        let mut child = self
            .git()
            .args(["fast-import", "--quiet", "--done"])
            .stdin(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        {
            let mut w = std::io::BufWriter::with_capacity(1 << 20, child.stdin.take().unwrap());
            let who = format!("{} <{}> {} +0000", author.name, author.email, author.time);
            write!(w, "commit refs/heads/{branch}\nauthor {who}\ncommitter {who}\ndata {}\n", message.len())?;
            w.write_all(message.as_bytes())?;
            w.write_all(b"\n")?;
            if let Some(p) = &parent {
                writeln!(w, "from {p}")?;
            }
            for (path, data) in changes {
                match data {
                    None => writeln!(w, "D {path}")?,
                    Some(bytes) => {
                        write!(w, "M 100644 inline {path}\ndata {}\n", bytes.len())?;
                        w.write_all(bytes)?;
                        w.write_all(b"\n")?;
                    }
                }
            }
            w.write_all(b"\ndone\n")?;
        }
        let out = child.wait_with_output()?;
        if !out.status.success() {
            return Err(Error::Git(String::from_utf8_lossy(&out.stderr).into_owned()));
        }
        self.head()?.ok_or_else(|| Error::Git("commit did not update the branch".into()))
    }

    pub fn log(&self, rev: &str, limit: usize) -> Result<Vec<CommitInfo>> {
        let repo = self.gix()?;
        let mut next = Some(gix::ObjectId::from_hex(self.resolve(rev)?.as_bytes()).map_err(git_err)?);
        let mut out = Vec::new();
        while let Some(id) = next {
            if out.len() >= limit {
                break;
            }
            let c = repo.find_commit(id).map_err(git_err)?;
            let author = c.author().map_err(git_err)?;
            let parents: Vec<String> = c.parent_ids().map(|p| p.to_string()).collect();
            out.push(CommitInfo {
                id: id.to_string(),
                author_name: author.name.to_string(),
                author_email: author.email.to_string(),
                time: author.time().map_err(git_err)?.seconds,
                message: c.message_raw_sloppy().to_string(),
                parents: parents.clone(),
            });
            next = parents.first().map(|p| gix::ObjectId::from_hex(p.as_bytes()).unwrap());
        }
        Ok(out)
    }

    pub fn branches(&self) -> Result<Vec<String>> {
        let repo = self.gix()?;
        let refs = repo.references().map_err(git_err)?;
        let mut names: Vec<String> = refs
            .local_branches()
            .map_err(git_err)?
            .filter_map(|r| r.ok())
            .map(|r| r.name().shorten().to_string())
            .collect();
        names.sort();
        Ok(names)
    }

    pub fn create_branch(&self, name: &str, rev: &str) -> Result<()> {
        let target = self.resolve(rev)?;
        let st = self.git().args(["branch", "--", name, &target]).output()?;
        if !st.status.success() {
            return Err(Error::Git(String::from_utf8_lossy(&st.stderr).into_owned()));
        }
        Ok(())
    }

    pub fn switch(&self, name: &str) -> Result<()> {
        if !self.branches()?.iter().any(|b| b == name) {
            return Err(Error::UnknownBranch(name.to_string()));
        }
        std::fs::write(self.git_dir.join("HEAD"), format!("ref: refs/heads/{name}\n"))?;
        Ok(())
    }

    pub fn repack_no_delta(&self) -> Result<()> {
        let st = self.git().args(["repack", "-adf", "--window=0", "-q"]).output()?;
        if !st.status.success() {
            return Err(Error::Git(String::from_utf8_lossy(&st.stderr).into_owned()));
        }
        Ok(())
    }
}

fn validate_path(p: &str) -> Result<()> {
    let bad = p.is_empty()
        || p.starts_with('/')
        || p.contains('\n')
        || p.contains('\\')
        || p.split('/').any(|c| c.is_empty() || c == "." || c == ".." || c == ".git");
    if bad { Err(Error::InvalidPath(p.to_string())) } else { Ok(()) }
}
```

The gix 0.88 method names above (`try_find_reference`, `peel_to_id`, `rev_parse_single`, `author().time()`, `message_raw_sloppy`, `references().local_branches()`) follow the spike's usage and the gix docs. If one differs, fix it to the compiler's suggestion without changing behavior.

- [ ] **Step 4: Run the tests until they pass**

Run: `pixi run cargo test -p kimcad-repo`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add crates/kimcad-repo Cargo.lock
git commit -s -m "feat(repo): git-backed record store (fast-import writes, gix reads)"
```

---

### Task 3: PyO3 module `kimcad._core`

**Files:**
- Create: `crates/kimcad-py/Cargo.toml`, `crates/kimcad-py/src/lib.rs`, `tests/python/test_core.py`

**Interfaces:**
- Consumes: Task 2 `kimcad_repo::Repo`.
- Produces (Python): `kimcad._core.Repo` with:
  - `init(path)`, `open(path)` (static)
  - `head() -> str | None`, `current_branch() -> str`, `resolve(rev) -> str`
  - `tree_entries(rev) -> dict[str, str]`, `read_blobs(list[str]) -> list[bytes]`
  - `commit(changes: dict[str, bytes | None], message, author_name, author_email, time: int) -> str`
  - `log(rev, limit) -> list[Commit]`, `branches() -> list[str]`, `create_branch(name, rev)`, `switch(name)`, `repack_no_delta()`
- `kimcad._core.Commit` has attributes `id, parents, author_name, author_email, time, message`.
- `kimcad._core.RepoError(Exception)`.

- [ ] **Step 1: Write the failing test** `tests/python/test_core.py`

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from kimcad import _core


def test_roundtrip_through_rust(tmp_path):
    repo = _core.Repo.init(str(tmp_path))
    assert repo.head() is None
    c1 = repo.commit({"objects/ab/W.json": b'{"a":1}', "kimcad.json": b"{}"}, "first", "T", "t@example.org", 1790000000)
    entries = repo.tree_entries("HEAD")
    assert sorted(entries) == ["kimcad.json", "objects/ab/W.json"]
    assert repo.read_blobs([entries["objects/ab/W.json"]]) == [b'{"a":1}']
    c2 = repo.commit({"kimcad.json": None}, "second", "T", "t@example.org", 1790000001)
    log = repo.log("HEAD", 10)
    assert [c.id for c in log] == [c2, c1]
    assert log[0].parents == [c1]
    assert log[1].message.strip() == "first"


def test_errors_are_repo_errors(tmp_path):
    with pytest.raises(_core.RepoError, match="not a KIMCAD project"):
        _core.Repo.open(str(tmp_path))
    repo = _core.Repo.init(str(tmp_path))
    with pytest.raises(_core.RepoError, match="unknown revision"):
        repo.resolve("nope")
```

- [ ] **Step 2: Create `crates/kimcad-py/Cargo.toml`**

```toml
[package]
name = "kimcad-py"
version.workspace = true
edition.workspace = true
license.workspace = true

[lib]
name = "_core"
crate-type = ["cdylib"]

[dependencies]
kimcad-repo = { path = "../kimcad-repo" }
pyo3 = "0.27"
```

(Use the latest PyO3 that `cargo search pyo3` shows. The API below is the Bound API from PyO3 ≥ 0.23.)

- [ ] **Step 3: Implement `crates/kimcad-py/src/lib.rs`**

```rust
// SPDX-License-Identifier: GPL-3.0-or-later
//! PyO3 bindings: `kimcad._core` (first of the two engine boundaries; the C++ `cxx` bridge comes with the GUI).
use std::collections::BTreeMap;
use std::path::PathBuf;

use pyo3::create_exception;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

create_exception!(_core, RepoError, pyo3::exceptions::PyException);

fn err(e: kimcad_repo::Error) -> PyErr {
    RepoError::new_err(e.to_string())
}

#[pyclass(get_all, frozen)]
struct Commit {
    id: String,
    parents: Vec<String>,
    author_name: String,
    author_email: String,
    time: i64,
    message: String,
}

#[pyclass(frozen)]
struct Repo {
    inner: kimcad_repo::Repo,
}

#[pymethods]
impl Repo {
    #[staticmethod]
    fn init(path: PathBuf) -> PyResult<Self> {
        Ok(Repo { inner: kimcad_repo::Repo::init(&path).map_err(err)? })
    }
    #[staticmethod]
    fn open(path: PathBuf) -> PyResult<Self> {
        Ok(Repo { inner: kimcad_repo::Repo::open(&path).map_err(err)? })
    }
    fn head(&self) -> PyResult<Option<String>> {
        self.inner.head().map_err(err)
    }
    fn current_branch(&self) -> PyResult<String> {
        self.inner.current_branch().map_err(err)
    }
    fn resolve(&self, rev: &str) -> PyResult<String> {
        self.inner.resolve(rev).map_err(err)
    }
    fn tree_entries(&self, rev: &str) -> PyResult<BTreeMap<String, String>> {
        self.inner.tree_entries(rev).map_err(err)
    }
    fn read_blobs<'py>(&self, py: Python<'py>, oids: Vec<String>) -> PyResult<Vec<Bound<'py, PyBytes>>> {
        let blobs = py.detach(|| self.inner.read_blobs(&oids)).map_err(err)?;
        Ok(blobs.iter().map(|b| PyBytes::new(py, b)).collect())
    }
    fn commit(
        &self,
        py: Python<'_>,
        changes: BTreeMap<String, Option<Vec<u8>>>,
        message: &str,
        author_name: String,
        author_email: String,
        time: i64,
    ) -> PyResult<String> {
        let sig = kimcad_repo::Signature { name: author_name, email: author_email, time };
        py.detach(|| self.inner.commit(&changes, message, &sig)).map_err(err)
    }
    fn log(&self, rev: &str, limit: usize) -> PyResult<Vec<Commit>> {
        Ok(self
            .inner
            .log(rev, limit)
            .map_err(err)?
            .into_iter()
            .map(|c| Commit {
                id: c.id,
                parents: c.parents,
                author_name: c.author_name,
                author_email: c.author_email,
                time: c.time,
                message: c.message,
            })
            .collect())
    }
    fn branches(&self) -> PyResult<Vec<String>> {
        self.inner.branches().map_err(err)
    }
    fn create_branch(&self, name: &str, rev: &str) -> PyResult<()> {
        self.inner.create_branch(name, rev).map_err(err)
    }
    fn switch(&self, name: &str) -> PyResult<()> {
        self.inner.switch(name).map_err(err)
    }
    fn repack_no_delta(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.inner.repack_no_delta()).map_err(err)
    }
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Repo>()?;
    m.add_class::<Commit>()?;
    m.add("RepoError", m.py().get_type::<RepoError>())?;
    Ok(())
}
```

(In PyO3 versions before 0.26, `py.detach` is named `py.allow_threads`.)

- [ ] **Step 4: Build and run**

Run: `pixi run build` then `pixi run pytest tests/python/test_core.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add crates/kimcad-py Cargo.lock tests/python/test_core.py
git commit -s -m "feat(py): PyO3 module kimcad._core exposing the record store"
```

---

### Task 4: Canonical records (`kimcad.records`) from the spike

**Files:**
- Create: `python/kimcad/records.py` (copied from `spikes/s3_records/records.py`, then modified as below), `tests/python/semantic.py` (copied from `spikes/s3_records/semantic.py`, with `from kimcad.records import ...`), `tests/python/conftest.py`, `tests/python/test_records.py`, `tests/python/test_golden.py`, `tests/corpus/fetch.py` (copied from `spikes/corpus/fetch.py`; `OUT` stays `HERE / "files"`), `tests/golden/manifest-windows.json`, `tests/golden/manifest-linux.json`, `tests/golden/README.md` (copied from `spikes/s3_records/golden/`)

**Interfaces:**
- Produces:
  - `FORMAT = "kimcad/1"`
  - `decompose(f, *, format_tag: str = FORMAT, resolve_node_id: Callable[[str, bytes], str | None] | None = None) -> tuple[dict[str, bytes], Decomposer]`. `resolve_node_id(ifc_type, canonical_bytes)` returns an existing id or `None` (meaning use the content hash).
  - `compose(records: dict[str, bytes]) -> ifcopenshell.file`
  - `state_hash(records) -> str`, `canon(obj) -> bytes`, `h(bytes) -> str`
  - `Decomposer.issues: list[str]`, `Decomposer.fresh_ids: dict[str, str]` (node id → content hash for nodes that got a new id)
  - `body_text(path) -> str` (IFC text from `DATA;`)

**Modifications to the copied spike `records.py`:**
1. SPDX header. `FORMAT = "kimcad/1"`. Module docstring references `docs/02-data-model-and-format.md`.
2. `Decomposer.__init__(self, f, format_tag=FORMAT, resolve_node_id=None)` replaces `prev`. Remove `self.prev` and the spike-only `while f"n/{key}" in self.records` loop.
3. `node()` becomes:

```python
    def node(self, e) -> str:
        eid = e.id()
        c = self.ckey[eid]  # memo per content class: duplicates encode once
        key = self.node_key.get(c)
        if key is None:
            b = canon(self.entity_value(e))
            fresh = h(b)
            key = (self.resolve_node_id(e.is_a(), b) if self.resolve_node_id else None) or fresh
            if key == fresh:
                self.fresh_ids[key] = fresh
            self.node_key[c] = key
            self.records[f"n/{key}"] = b
        self.inst_node_key[eid] = key
        return key
```

4. `run()` writes `self.records["meta"] = canon({"k": self.format_tag, "schema": self.f.schema_identifier})`.
5. Add `body_text(path)` (moved from the spike `run.py`).

- [ ] **Step 1: Write the failing tests** `tests/python/conftest.py` and `tests/python/test_records.py`

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small IFC models built with ifcopenshell.api (no downloaded corpus needed)."""
import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import numpy as np
import pytest


def build_model(schema="IFC4", walls=2):
    f = ifcopenshell.file(schema=schema)
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="Test")
    ifcopenshell.api.unit.assign_unit(f)
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    storey = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Level 1")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    ifcopenshell.api.aggregate.assign_object(f, products=[building], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[storey], relating_object=building)
    ifcopenshell.api.geometry.edit_object_placement(f, product=storey)
    made = []
    for i in range(walls):
        w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=f"Wall {i}")
        rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=4.0, height=3.0, thickness=0.2)
        ifcopenshell.api.geometry.assign_representation(f, product=w, representation=rep)
        m = np.eye(4)
        m[0][3] = 5.0 * i
        ifcopenshell.api.geometry.edit_object_placement(f, product=w, matrix=m, is_si=True)
        pset = ifcopenshell.api.pset.add_pset(f, product=w, name="Pset_WallCommon")
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"FireRating": "EI30", "IsExternal": True})
        made.append(w)
    ifcopenshell.api.spatial.assign_container(f, products=made, relating_structure=storey)
    return f


@pytest.fixture
def model():
    return build_model()


@pytest.fixture
def model_file(tmp_path, model):
    p = tmp_path / "model.ifc"
    model.write(str(p))
    return p
```

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import json

import ifcopenshell
from conftest import build_model
from semantic import compare

from kimcad.records import FORMAT, body_text, compose, decompose


def roundtrip(f, tmp_path, name="b.ifc"):
    r1, _ = decompose(f)
    b = compose(r1)
    pb = tmp_path / name
    b.write(str(pb))
    b2 = ifcopenshell.open(str(pb))
    r2, _ = decompose(b2)
    return r1, r2, b2, pb


def test_fixed_point_and_lossless(model, tmp_path):
    r1, r2, b2, _ = roundtrip(model, tmp_path)
    assert r1 == r2
    assert compare(model, b2) == []
    assert json.loads(r1["meta"]) == {"k": FORMAT, "schema": "IFC4"}


def test_export_is_deterministic(model, tmp_path):
    r1, _ = decompose(model)
    compose(r1).write(str(tmp_path / "x.ifc"))
    compose(r1).write(str(tmp_path / "y.ifc"))
    assert body_text(tmp_path / "x.ifc") == body_text(tmp_path / "y.ifc")


def test_storey_placement_is_anchored_not_copied(model):
    recs, _ = decompose(model)
    walls = [json.loads(v) for k, v in recs.items() if k.startswith("o/") and json.loads(v)["t"] == "IfcWall"]
    rel_to = walls[0]["a"]["ObjectPlacement"]["a"]["PlacementRelTo"]
    assert "@a" in rel_to and rel_to["@a"].endswith("/ObjectPlacement")


def test_loose_duplicates_keep_multiplicity(model, tmp_path):
    for _ in range(2):
        model.createIfcCartesianPoint((9.0, 9.0, 9.0))
    recs, _ = decompose(model)
    loose = [json.loads(v) for k, v in recs.items() if k.startswith("l/") and json.loads(v)["e"]["t"] == "IfcCartesianPoint"]
    assert [x["n"] for x in loose] == [2]
    _, r2, b2, _ = roundtrip(model, tmp_path)
    assert len([p for p in b2.by_type("IfcCartesianPoint") if b2.get_total_inverses(p) == 0]) == 2


def test_strings_are_not_normalized(model, tmp_path):
    decomposed = "Ñandú"  # 'Ñandú' with a combining tilde (NFD) for the Ñ
    model.by_type("IfcWall")[0].Name = decomposed
    _, _, b2, _ = roundtrip(model, tmp_path)
    assert decomposed in [w.Name for w in b2.by_type("IfcWall")]


def test_integer_and_real_stay_distinct(model, tmp_path):
    w = model.by_type("IfcWall")[0]
    pset = ifcopenshell.api.pset.add_pset(model, product=w, name="KIMCAD_Test")
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties={"I": model.createIfcInteger(1), "R": model.createIfcReal(1.0)})
    _, _, b2, _ = roundtrip(model, tmp_path)
    vals = {p.Name: p.NominalValue for p in b2.by_type("IfcPropertySingleValue") if p.Name in ("I", "R")}
    assert vals["I"].is_a() == "IfcInteger" and vals["R"].is_a() == "IfcReal"


def test_duplicate_globalids_get_ordinals(model, tmp_path):
    w = model.by_type("IfcWall")[0]
    dup = model.createIfcWall(w.GlobalId, None, "Dup")
    recs, d = decompose(model)
    assert f"o/{w.GlobalId}" in recs and f"o/{w.GlobalId}~1" in recs
    assert any("duplicate GlobalId" in i for i in d.issues)
    r1, r2, _, _ = roundtrip(model, tmp_path)
    assert r1 == r2


def test_ifc2x3_and_ifc4x3_models_roundtrip(tmp_path):
    for schema in ("IFC2X3", "IFC4X3_ADD2"):
        f = build_model(schema=schema, walls=1)
        r1, r2, b2, _ = roundtrip(f, tmp_path, name=f"{schema}.ifc")
        assert r1 == r2 and compare(f, b2) == []
```

(`test_integer_and_real_stay_distinct` also needs `import ifcopenshell.api.pset` at the top.)

- [ ] **Step 2: Run the tests to see them fail**

Run: `pixi run pytest tests/python/test_records.py -q`
Expected: `ModuleNotFoundError: kimcad.records`.

- [ ] **Step 3: Copy and modify the spike code** as listed in **Modifications** above. Copy `semantic.py` and change its import to `from kimcad.records import Schema, agg_info, norm_float`.

- [ ] **Step 4: Run the tests until they pass**

Run: `pixi run pytest tests/python/test_records.py -q`
Expected: 8 passed.

- [ ] **Step 5: Golden test** `tests/python/test_golden.py`. It proves the port is byte-identical to the validated spike on the real corpus.

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden hashes from spikes S3/S4 (tests/golden). Needs `pixi run fetch-corpus`."""
import json
import pathlib

import blake3
import ifcopenshell
import pytest

from kimcad.records import body_text, compose, decompose, state_hash

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests" / "corpus" / "files"
GOLDEN = json.loads((ROOT / "tests" / "golden" / "manifest-windows.json").read_text())
LARGE = 5_000_000  # bytes; larger files only run with -m slow
CASES = sorted(k for k, v in GOLDEN.items() if v[0])


@pytest.mark.golden
@pytest.mark.parametrize("rel", CASES)
def test_matches_spike_golden_hashes(rel, tmp_path, request):
    path = CORPUS / rel
    if not path.exists():
        pytest.skip("corpus not downloaded (pixi run fetch-corpus)")
    if path.stat().st_size > LARGE and "slow" not in request.config.getoption("-m"):
        pytest.skip("large file: run with -m 'golden and slow'")
    want_state, want_export = GOLDEN[rel]
    recs, _ = decompose(ifcopenshell.open(str(path)), format_tag="kimcad-spike/1")
    assert state_hash(recs) == want_state
    out = tmp_path / "b.ifc"
    compose(recs).write(str(out))
    assert blake3.blake3(body_text(out).encode()).hexdigest()[:32] == want_export
```

Copy `spikes/s3_records/golden/*` to `tests/golden/` and `spikes/corpus/fetch.py` to `tests/corpus/fetch.py` (add the SPDX header). Run `pixi run fetch-corpus`, then `pixi run golden`.
Expected: every small corpus file passes. If the conda-forge build ever disagrees with the golden values, stop and report it; that would be a real S4 finding, not something to paper over.

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/records.py tests/python tests/corpus/fetch.py tests/golden
git commit -s -m "feat(records): canonical record decomposition ported from spike S3, golden-hash tests"
```

---

### Task 5: Record layout and stable node ids across versions

**Files:**
- Create: `python/kimcad/layout.py`, `python/kimcad/nodeids.py`, `tests/python/test_layout.py`, `tests/python/test_nodeids.py`

**Interfaces:**
- Produces:
  - `layout.key_to_path(key: str) -> str`
  - `layout.path_to_key(path: str) -> str`
  - `layout.blob_oid(data: bytes) -> str` (Git SHA-1 blob id)
  - `layout.META_PATH = "kimcad.json"`
  - `nodeids.decompose_against_head(f, head_entries: dict[str, str], read_blobs: Callable[[list[str]], list[bytes]], *, format_tag=FORMAT, max_rounds=5) -> tuple[dict[str, bytes], Decomposer]`
- Consumes: Task 4 `decompose`.

Layout:
- `o/<id>` → `objects/<first 2 hex of blake3(id)>/<id>.json`
- `n/<id>` → `nodes/<id[:2]>/<id>.json`
- `l/<h>` → `loose/<h[:2]>/<h>.json`
- `meta` → `kimcad.json`

One shard level for now. Adaptive sharding (D39) is deferred until models above 64k records need it, and the layout is isolated in this module so it can change.

Node-id algorithm (doc 02 rule 5):
- A node whose canonical bytes match a HEAD node blob (same Git oid) keeps that id.
- Otherwise it gets its content hash, and its fresh id must not collide with an existing HEAD node id: re-hash `h(fresh + "~")` until it is free.
- After a full pass, the unmatched new nodes and unmatched HEAD nodes are paired when an IFC type has exactly one of each (`IfcOwnerHistory`, a single context, …).
- Pairs are fed back as forced ids, and the pass repeats until no new pairs appear (`max_rounds`).

- [ ] **Step 1: Write the failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later  (tests/python/test_layout.py)
import subprocess

import pytest

from kimcad.layout import META_PATH, blob_oid, key_to_path, path_to_key


@pytest.mark.parametrize("key", ["o/2O2Fr$t4X7Zf8NOew3FLOH", "o/2O2Fr$t4X7Zf8NOew3FLOH~1", "n/0123abcd", "l/ffee00", "meta"])
def test_key_path_roundtrip(key):
    p = key_to_path(key)
    assert path_to_key(p) == key
    assert not p.startswith("/") and ".." not in p


def test_meta_path():
    assert key_to_path("meta") == META_PATH == "kimcad.json"


def test_blob_oid_matches_git():
    data = "{\"t\":\"IfcWall\",\"ñ\":1}".encode()
    out = subprocess.run(["git", "hash-object", "--stdin"], input=data, capture_output=True, check=True)
    assert blob_oid(data) == out.stdout.decode().strip()
```

```python
# SPDX-License-Identifier: GPL-3.0-or-later  (tests/python/test_nodeids.py)
from conftest import build_model

from kimcad.layout import blob_oid, key_to_path
from kimcad.nodeids import decompose_against_head
from kimcad.records import decompose


def as_head(records):
    by_oid = {blob_oid(v): v for v in records.values()}
    entries = {key_to_path(k): blob_oid(v) for k, v in records.items()}
    return entries, lambda oids: [by_oid[o] for o in oids]


def changed(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def test_unchanged_model_reuses_every_id():
    f = build_model()
    base, _ = decompose(f)
    entries, read = as_head(base)
    again, _ = decompose_against_head(f, entries, read)
    assert again == base


def test_edited_shared_node_keeps_its_id():
    f = build_model(walls=3)
    base, _ = decompose(f)
    entries, read = as_head(base)
    ctx = [c for c in f.by_type("IfcGeometricRepresentationContext") if not c.is_a("IfcGeometricRepresentationSubContext")][0]
    ctx.Precision = 0.0001  # shared node referenced by every representation
    new, _ = decompose_against_head(f, entries, read)
    diff = changed(base, new)
    assert len(diff) == 1 and diff[0].startswith("n/")


def test_new_node_never_reuses_an_old_id():
    f = build_model(walls=2)
    base, _ = decompose(f)
    entries, read = as_head(base)
    f.by_type("IfcWall")[0].Name = "Renamed"
    new, _ = decompose_against_head(f, entries, read)
    assert changed(base, new) == [k for k in changed(base, new) if k.startswith("o/")]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `pixi run pytest tests/python/test_layout.py tests/python/test_nodeids.py -q`
Expected: `ModuleNotFoundError: kimcad.layout`.

- [ ] **Step 3: Implement `python/kimcad/layout.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where records live inside a KIMCAD Git tree (docs/03-versioning.md)."""
import hashlib

import blake3

META_PATH = "kimcad.json"


def key_to_path(key: str) -> str:
    if key == "meta":
        return META_PATH
    kind, ident = key.split("/", 1)
    if kind == "o":
        return f"objects/{blake3.blake3(ident.encode('utf-8')).hexdigest()[:2]}/{ident}.json"
    if kind == "n":
        return f"nodes/{ident[:2]}/{ident}.json"
    if kind == "l":
        return f"loose/{ident[:2]}/{ident}.json"
    raise ValueError(f"unknown record key {key!r}")


_DIRS = {"objects": "o", "nodes": "n", "loose": "l"}


def path_to_key(path: str) -> str:
    if path == META_PATH:
        return "meta"
    top, _shard, name = path.split("/", 2)
    if top not in _DIRS or not name.endswith(".json"):
        raise ValueError(f"not a record path: {path!r}")
    return f"{_DIRS[top]}/{name[:-5]}"


def blob_oid(data: bytes) -> str:
    """Git blob id (SHA-1), so unchanged records are detected without reading the repository."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
```

- [ ] **Step 4: Implement `python/kimcad/nodeids.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stable ids for shared nodes across versions (docs/02 rule 5, spike S3)."""
import json
from typing import Callable

from .layout import path_to_key
from .records import FORMAT, decompose, h


def decompose_against_head(f, head_entries: dict[str, str], read_blobs: Callable[[list[str]], list[bytes]], *, format_tag: str = FORMAT, max_rounds: int = 5):
    head_nodes = {path_to_key(p)[2:]: oid for p, oid in head_entries.items() if p.startswith("nodes/")}
    id_by_oid = {oid: nid for nid, oid in head_nodes.items()}
    taken = set(head_nodes)
    forced: dict[str, str] = {}  # fresh content hash -> old node id

    def resolver(ifc_type: str, b: bytes):
        from .layout import blob_oid

        nid = id_by_oid.get(blob_oid(b))
        if nid:
            return nid
        fresh = h(b)
        if fresh in forced:
            return forced[fresh]
        while fresh in taken:  # never collide with an existing node id
            fresh = h((fresh + "~").encode())
        return fresh

    head_types: dict[str, str] = {}
    for _ in range(max_rounds):
        recs, d = decompose(f, format_tag=format_tag, resolve_node_id=resolver)
        new_ids = {k[2:] for k in recs if k.startswith("n/")}
        unmatched_old = sorted(taken - new_ids)
        unmatched_new = sorted(i for i in new_ids if i not in taken)
        if not unmatched_old or not unmatched_new:
            return recs, d
        need = [i for i in unmatched_old if i not in head_types]
        for nid, blob in zip(need, read_blobs([head_nodes[i] for i in need])):
            head_types[nid] = json.loads(blob)["t"]
        old_by_type: dict[str, list[str]] = {}
        for i in unmatched_old:
            old_by_type.setdefault(head_types[i], []).append(i)
        new_by_type: dict[str, list[str]] = {}
        for i in unmatched_new:
            new_by_type.setdefault(json.loads(recs[f"n/{i}"])["t"], []).append(i)
        added = 0
        for t, olds in old_by_type.items():
            news = new_by_type.get(t, [])
            if len(olds) == 1 and len(news) == 1:
                fresh_hash = h(recs[f"n/{news[0]}"])
                if forced.get(fresh_hash) != olds[0]:
                    forced[fresh_hash] = olds[0]
                    added += 1
        if not added:
            return recs, d
    return recs, d
```

- [ ] **Step 5: Run the tests until they pass**

Run: `pixi run pytest tests/python/test_layout.py tests/python/test_nodeids.py -q`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add python/kimcad/layout.py python/kimcad/nodeids.py tests/python/test_layout.py tests/python/test_nodeids.py
git commit -s -m "feat: record layout and stable shared-node ids across versions"
```

---

### Task 6: `Project`: commit, status, log, diff, export, show, branches

**Files:**
- Create: `python/kimcad/project.py`, `tests/python/test_project.py`

**Interfaces:**
- Consumes: `_core.Repo` (Task 3), `decompose_against_head` (Task 5), `compose`, `body_text` (Task 4), `key_to_path`/`path_to_key`/`blob_oid` (Task 5).
- Produces:
  - Exceptions: `KimcadError(Exception)` and its subclasses `NotAProject`, `NothingToCommit`, `SchemaMismatch`, `InvalidInput`, `NoVersions`, `UnknownRevision`, `TargetExists`.
  - `@dataclass Change(kind: str /*added|modified|removed*/, key: str, ifc_type: str, name: str | None)`
  - `@dataclass Changes(items: list[Change])` with properties `added`, `modified`, `removed` and `__bool__`.
  - `Project.init(path) -> Project`, `Project.open(path) -> Project`
  - `commit(ifc_path, message, *, author=None, time=None) -> tuple[str, Changes]`
  - `status(ifc_path) -> Changes`
  - `log(rev="HEAD", limit=50) -> list[_core.Commit]`
  - `diff(rev_a=None, rev_b="HEAD") -> Changes`
  - `export(out_path, rev="HEAD", overwrite=False) -> pathlib.Path`
  - `show(key, rev="HEAD") -> dict`
  - `branches() -> list[str]`, `current_branch() -> str`, `create_branch(name, rev="HEAD")`, `switch(name)`
  - `schema() -> str | None`

- [ ] **Step 1: Write the failing tests** `tests/python/test_project.py`

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import ifcopenshell
import pytest
from conftest import build_model

from kimcad.project import NoVersions, NothingToCommit, Project, SchemaMismatch, InvalidInput, TargetExists, NotAProject
from kimcad.records import body_text, decompose

AUTHOR = ("Test", "test@example.org")


def write(f, path):
    f.write(str(path))
    return path


@pytest.fixture
def project(tmp_path):
    return Project.init(tmp_path / "Proyecto ñ")


def test_first_commit_then_nothing_to_commit(project, tmp_path):
    src = write(build_model(), tmp_path / "a.ifc")
    cid, changes = project.commit(src, "first", author=AUTHOR, time=1790000000)
    assert len(cid) == 40 and changes.added and not changes.modified
    assert project.schema() == "IFC4"
    with pytest.raises(NothingToCommit):
        project.commit(src, "again", author=AUTHOR)
    assert len(project.log()) == 1


def test_property_edit_is_a_tiny_diff(project, tmp_path):
    f = build_model(walls=3)
    project.commit(write(f, tmp_path / "a.ifc"), "first", author=AUTHOR, time=1)
    pset = [p for p in f.by_type("IfcPropertySet") if p.Name == "Pset_WallCommon"][0]
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"FireRating": "EI60"})
    status = project.status(write(f, tmp_path / "b.ifc"))
    assert [c.ifc_type for c in status.modified] == ["IfcPropertySet"] and not status.added and not status.removed
    project.commit(tmp_path / "b.ifc", "EI60", author=AUTHOR, time=2)
    d = project.diff()
    assert [(c.kind, c.ifc_type) for c in d.items] == [("modified", "IfcPropertySet")]


def test_export_reproduces_versions(project, tmp_path):
    f = build_model()
    project.commit(write(f, tmp_path / "a.ifc"), "first", author=AUTHOR, time=1)
    f.by_type("IfcWall")[0].Name = "Renamed"
    project.commit(write(f, tmp_path / "b.ifc"), "rename", author=AUTHOR, time=2)
    out1 = project.export(tmp_path / "v1.ifc", rev="HEAD~1")
    out2 = project.export(tmp_path / "v2.ifc")
    assert "Renamed" not in body_text(out1) and "Renamed" in body_text(out2)
    assert decompose(ifcopenshell.open(str(out2)))[0] == decompose(f)[0] or True
    with pytest.raises(TargetExists):
        project.export(out2)
    project.export(out2, overwrite=True)
    assert not project.status(out2)  # exported HEAD == HEAD


def test_schema_mismatch_refused(project, tmp_path):
    project.commit(write(build_model("IFC4"), tmp_path / "a.ifc"), "first", author=AUTHOR, time=1)
    with pytest.raises(SchemaMismatch, match="IFC4X3_ADD2"):
        project.commit(write(build_model("IFC4X3_ADD2"), tmp_path / "b.ifc"), "x", author=AUTHOR)
    assert len(project.log()) == 1


INVALID_IFC = """ISO-10303-21;
HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','',(''),(''),'','','');FILE_SCHEMA(('IFC4'));ENDSEC;
DATA;
#1=IFCCARTESIANPOINTLIST3D(((0.,0.,0.),(1.,0.,0.),(0.,1.,0.)),$);
#2=IFCTRIANGULATEDFACESET(#1,$,.T.,((1,2,3)),((1,2,3)));
ENDSEC;
END-ISO-10303-21;
"""


def test_invalid_input_refused(project, tmp_path):
    bad = tmp_path / "bad.ifc"
    bad.write_text(INVALID_IFC)
    with pytest.raises(InvalidInput) as e:
        project.commit(bad, "bad", author=AUTHOR)
    assert e.value.messages
    assert project.log() == []


def test_empty_project_and_unknown_dir(project, tmp_path):
    assert project.log() == []
    with pytest.raises(NoVersions):
        project.diff()
    with pytest.raises(NoVersions):
        project.export(tmp_path / "x.ifc")
    with pytest.raises(NotAProject):
        Project.open(tmp_path / "nowhere")


def test_branches(project, tmp_path):
    f = build_model()
    project.commit(write(f, tmp_path / "a.ifc"), "base", author=AUTHOR, time=1)
    project.create_branch("option-b")
    project.switch("option-b")
    f.by_type("IfcWall")[0].Name = "B"
    project.commit(write(f, tmp_path / "b.ifc"), "b", author=AUTHOR, time=2)
    assert project.current_branch() == "option-b" and project.branches() == ["main", "option-b"]
    project.switch("main")
    assert len(project.log()) == 1
```

(Also add `import ifcopenshell.api.pset` at the top. Remove the `or True` placeholder assertion in `test_export_reproduces_versions` once it runs: assert `decompose(...)[0] == decompose(f)[0]` directly.)

- [ ] **Step 2: Run the tests to see them fail**

Run: `pixi run pytest tests/python/test_project.py -q`
Expected: `ModuleNotFoundError: kimcad.project`.

- [ ] **Step 3: Implement `python/kimcad/project.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""A KIMCAD project: IFC versions stored as canonical records in Git (docs/03-versioning.md)."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time as _time
from dataclasses import dataclass, field

import ifcopenshell
import ifcopenshell.validate

from . import _core
from .layout import META_PATH, blob_oid, key_to_path, path_to_key
from .nodeids import decompose_against_head
from .records import compose

REPACK_THRESHOLD = 10_000  # changed records; D39


class KimcadError(Exception):
    pass


class NotAProject(KimcadError):
    pass


class NothingToCommit(KimcadError):
    pass


class SchemaMismatch(KimcadError):
    pass


class NoVersions(KimcadError):
    pass


class UnknownRevision(KimcadError):
    pass


class TargetExists(KimcadError):
    pass


class InvalidInput(KimcadError):
    def __init__(self, message: str, messages: list[str]):
        super().__init__(message)
        self.messages = messages


@dataclass
class Change:
    kind: str  # "added" | "modified" | "removed"
    key: str
    ifc_type: str
    name: str | None


@dataclass
class Changes:
    items: list[Change] = field(default_factory=list)

    def of(self, kind):
        return [c for c in self.items if c.kind == kind]

    @property
    def added(self):
        return self.of("added")

    @property
    def modified(self):
        return self.of("modified")

    @property
    def removed(self):
        return self.of("removed")

    def __bool__(self):
        return bool(self.items)


def _describe(key: str, blob: bytes) -> tuple[str, str | None]:
    if key == "meta":
        return "(project metadata)", None
    v = json.loads(blob)
    if key.startswith("l/"):
        v = v["e"]
    return v["t"], v.get("a", {}).get("Name")


def _author() -> tuple[str, str]:
    name = os.environ.get("KIMCAD_AUTHOR_NAME") or _git_config("user.name") or "KIMCAD User"
    email = os.environ.get("KIMCAD_AUTHOR_EMAIL") or _git_config("user.email") or "user@localhost"
    return name, email


def _git_config(key: str) -> str | None:
    try:
        out = subprocess.run(["git", "config", "--get", key], capture_output=True, text=True)
        return out.stdout.strip() or None
    except OSError:
        return None


class Project:
    def __init__(self, path: pathlib.Path, repo):
        self.path = path
        self.repo = repo

    @classmethod
    def init(cls, path) -> Project:
        path = pathlib.Path(path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            return cls(path, _core.Repo.init(str(path)))
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None

    @classmethod
    def open(cls, path) -> Project:
        path = pathlib.Path(path)
        try:
            return cls(path, _core.Repo.open(str(path)))
        except _core.RepoError as e:
            raise NotAProject(str(e)) from None

    # ---- helpers ----
    def _rev(self, rev: str) -> str:
        if self.repo.head() is None:
            raise NoVersions("this project has no versions yet (use `kimcad commit <file.ifc>`)")
        try:
            return self.repo.resolve(rev)
        except _core.RepoError:
            raise UnknownRevision(f"unknown version: {rev}") from None

    def _entries(self, rev: str) -> dict[str, str]:
        return self.repo.tree_entries(self._rev(rev))

    def _records(self, rev: str) -> dict[str, bytes]:
        entries = self._entries(rev)
        paths = sorted(entries)
        blobs = self.repo.read_blobs([entries[p] for p in paths])
        return {path_to_key(p): b for p, b in zip(paths, blobs)}

    def schema(self) -> str | None:
        if self.repo.head() is None:
            return None
        meta = self.repo.read_blobs([self._entries("HEAD")[META_PATH]])[0]
        return json.loads(meta)["schema"]

    def _changes(self, old_entries: dict[str, str], new: dict[str, bytes]) -> tuple[Changes, dict[str, bytes | None]]:
        new_paths = {key_to_path(k): v for k, v in new.items()}
        writes: dict[str, bytes | None] = {}
        added, modified, removed = [], [], []
        for p, data in new_paths.items():
            old = old_entries.get(p)
            if old is None:
                added.append(p)
                writes[p] = data
            elif old != blob_oid(data):
                modified.append(p)
                writes[p] = data
        for p in old_entries:
            if p not in new_paths:
                removed.append(p)
                writes[p] = None
        old_blobs = dict(zip(removed, self.repo.read_blobs([old_entries[p] for p in removed]))) if removed else {}
        items = []
        for kind, paths in (("added", added), ("modified", modified), ("removed", removed)):
            for p in sorted(paths):
                key = path_to_key(p)
                t, n = _describe(key, new_paths[p] if kind != "removed" else old_blobs[p])
                items.append(Change(kind, key, t, n))
        return Changes(items), writes

    def _decompose_file(self, ifc_path) -> dict[str, bytes]:
        f = ifcopenshell.open(str(ifc_path))
        current = self.schema()
        if current and f.schema_identifier != current:
            raise SchemaMismatch(
                f"{ifc_path} is {f.schema_identifier} but this project is {current}; "
                "KIMCAD never converts schemas silently (docs/02, D30)"
            )
        head = self.repo.head()
        entries = self.repo.tree_entries(head) if head else {}
        records, _ = decompose_against_head(f, entries, self.repo.read_blobs)
        try:
            compose(records)  # records must be writable back to IFC (lossless guarantee, D36)
        except RuntimeError as e:
            log = ifcopenshell.validate.json_logger()
            ifcopenshell.validate.validate(f, log)
            messages = [str(s.get("message", s)) for s in log.statements] or [str(e)]
            raise InvalidInput(f"{ifc_path} is not valid {f.schema_identifier} and cannot be stored losslessly", messages) from None
        return records

    # ---- commands ----
    def status(self, ifc_path) -> Changes:
        records = self._decompose_file(ifc_path)
        head = self.repo.head()
        changes, _ = self._changes(self.repo.tree_entries(head) if head else {}, records)
        return changes

    def commit(self, ifc_path, message: str, *, author=None, time=None):
        records = self._decompose_file(ifc_path)
        head = self.repo.head()
        changes, writes = self._changes(self.repo.tree_entries(head) if head else {}, records)
        if not changes:
            raise NothingToCommit("nothing to commit: the file matches the current version")
        name, email = author or _author()
        cid = self.repo.commit(writes, message, name, email, int(time if time is not None else _time.time()))
        if len(writes) > REPACK_THRESHOLD:
            self.repo.repack_no_delta()
        return cid, changes

    def log(self, rev: str = "HEAD", limit: int = 50):
        if self.repo.head() is None:
            return []
        return self.repo.log(self._rev(rev), limit)

    def diff(self, rev_a: str | None = None, rev_b: str = "HEAD") -> Changes:
        b = self._rev(rev_b)
        if rev_a is None:
            parents = self.repo.log(b, 1)[0].parents
            old = self.repo.tree_entries(parents[0]) if parents else {}
        else:
            old = self._entries(rev_a)
        changes, _ = self._changes(old, self._records(b))
        return changes

    def export(self, out_path, rev: str = "HEAD", overwrite: bool = False) -> pathlib.Path:
        out = pathlib.Path(out_path)
        records = self._records(rev)
        if out.exists() and not overwrite:
            raise TargetExists(f"{out} already exists (use --force to overwrite)")
        compose(records).write(str(out))
        return out

    def show(self, key: str, rev: str = "HEAD") -> dict:
        entries = self._entries(rev)
        p = key_to_path(key)
        if p not in entries:
            raise KimcadError(f"no record {key} in {rev}")
        return json.loads(self.repo.read_blobs([entries[p]])[0])

    def branches(self) -> list[str]:
        return self.repo.branches()

    def current_branch(self) -> str:
        return self.repo.current_branch()

    def create_branch(self, name: str, rev: str = "HEAD"):
        self.repo.create_branch(name, self._rev(rev))

    def switch(self, name: str):
        try:
            self.repo.switch(name)
        except _core.RepoError as e:
            raise KimcadError(str(e)) from None
```

Note on `diff()`: `_changes` compares old entries against new records. For historical diffs the "new" side is read from the repo, which is correct but reads every record of `rev_b`. Optimizing this to compare tree entries only, reading just the changed blobs, is a follow-up once diff speed matters (R3).

- [ ] **Step 4: Run the tests until they pass**

Run: `pixi run pytest tests/python/test_project.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add python/kimcad/project.py tests/python/test_project.py
git commit -s -m "feat: Project API (commit/status/log/diff/export/show/branches)"
```

---

### Task 7: `kimcad` CLI

**Files:**
- Create: `python/kimcad/cli.py`, `python/kimcad/__main__.py`, `tests/python/test_cli.py`

**Interfaces:**
- Consumes: `Project` and the exceptions from Task 6.
- Produces: `main(argv: list[str] | None = None) -> int`. Exit 0 on success, 1 on `KimcadError` (message on stderr as `kimcad: error: …`), 2 on usage errors. Commands:
  - `init [DIR]`
  - `commit FILE -m MSG`
  - `status FILE`
  - `log [-n N] [REV]`
  - `diff [REV_A] [REV_B] [--json]`
  - `export OUT [--rev REV] [--force]`
  - `show KEY [--rev REV]`
  - `branch [NAME] [--rev REV]` (no name lists branches; the current one gets `*`)
  - `switch NAME`
  - Global `-C DIR` (project dir, default cwd).

- [ ] **Step 1: Write the failing tests** `tests/python/test_cli.py`

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import json

from conftest import build_model

from kimcad.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_full_cli_flow(tmp_path, capsys):
    proj = tmp_path / "Mi Proyecto ñ"
    f = build_model()
    a = tmp_path / "a.ifc"
    f.write(str(a))
    assert run(capsys, "init", str(proj))[0] == 0
    code, out, _ = run(capsys, "-C", str(proj), "commit", str(a), "-m", "first")
    assert code == 0 and "added" in out
    code, out, err = run(capsys, "-C", str(proj), "commit", str(a), "-m", "again")
    assert code == 1 and "nothing to commit" in err
    f.by_type("IfcWall")[0].Name = "Renamed"
    b = tmp_path / "b.ifc"
    f.write(str(b))
    code, out, _ = run(capsys, "-C", str(proj), "status", str(b))
    assert code == 0 and "IfcWall" in out and "Renamed" in out
    run(capsys, "-C", str(proj), "commit", str(b), "-m", "rename")
    code, out, _ = run(capsys, "-C", str(proj), "log")
    assert code == 0 and out.index("rename") < out.index("first")
    code, out, _ = run(capsys, "-C", str(proj), "diff", "--json")
    assert json.loads(out)["modified"][0]["ifc_type"] == "IfcWall"
    out_ifc = tmp_path / "out.ifc"
    assert run(capsys, "-C", str(proj), "export", str(out_ifc), "--rev", "HEAD~1")[0] == 0
    code, _, err = run(capsys, "-C", str(proj), "export", str(out_ifc))
    assert code == 1 and "--force" in err
    assert run(capsys, "-C", str(proj), "export", str(out_ifc), "--force")[0] == 0
    assert run(capsys, "-C", str(proj), "branch", "option-b")[0] == 0
    code, out, _ = run(capsys, "-C", str(proj), "branch")
    assert "* main" in out and "option-b" in out


def test_empty_project_messages(tmp_path, capsys):
    proj = tmp_path / "p"
    run(capsys, "init", str(proj))
    code, out, _ = run(capsys, "-C", str(proj), "log")
    assert code == 0 and "no versions" in out
    for argv in (["diff"], ["export", str(tmp_path / "x.ifc")]):
        code, _, err = run(capsys, "-C", str(proj), *argv)
        assert code == 1 and "no versions" in err and "Traceback" not in err


def test_not_a_project(tmp_path, capsys):
    code, _, err = run(capsys, "-C", str(tmp_path), "log")
    assert code == 1 and "not a KIMCAD project" in err
```

- [ ] **Step 2: Run to see it fail**

Run: `pixi run pytest tests/python/test_cli.py -q`
Expected: `ModuleNotFoundError: kimcad.cli`.

- [ ] **Step 3: Implement `python/kimcad/cli.py` and `python/kimcad/__main__.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""`kimcad` command line (docs/03-versioning.md#cli)."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from .project import Changes, KimcadError, Project

SYMBOL = {"added": "+", "modified": "~", "removed": "-"}


def _print_changes(changes: Changes, as_json: bool = False):
    if as_json:
        print(json.dumps({k: [vars(c) for c in changes.of(k)] for k in ("added", "modified", "removed")}, ensure_ascii=False, indent=1))
        return
    print(f"{len(changes.added)} added, {len(changes.modified)} modified, {len(changes.removed)} removed")
    for c in changes.items[:200]:
        name = f" {c.name!r}" if c.name else ""
        print(f"  {SYMBOL[c.kind]} {c.ifc_type}{name}  [{c.key}]")
    if len(changes.items) > 200:
        print(f"  … {len(changes.items) - 200} more (use --json for all)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kimcad", description="Versioned IFC projects.")
    p.add_argument("-C", dest="project", default=".", help="project directory (default: current)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="create a project")
    s.add_argument("dir", nargs="?")
    s = sub.add_parser("commit", help="save an IFC file as a new version")
    s.add_argument("file")
    s.add_argument("-m", "--message", required=True)
    s = sub.add_parser("status", help="show what committing an IFC file would change")
    s.add_argument("file")
    s = sub.add_parser("log", help="list versions")
    s.add_argument("rev", nargs="?", default="HEAD")
    s.add_argument("-n", type=int, default=50)
    s = sub.add_parser("diff", help="compare versions (default: last version vs its parent)")
    s.add_argument("rev_a", nargs="?")
    s.add_argument("rev_b", nargs="?", default="HEAD")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("export", help="write a version as IFC")
    s.add_argument("out")
    s.add_argument("--rev", default="HEAD")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("show", help="print one canonical record")
    s.add_argument("key")
    s.add_argument("--rev", default="HEAD")
    s = sub.add_parser("branch", help="list or create design options (branches)")
    s.add_argument("name", nargs="?")
    s.add_argument("--rev", default="HEAD")
    s = sub.add_parser("switch", help="switch to a design option (branch)")
    s.add_argument("name")
    return p


def run(args) -> int:
    if args.cmd == "init":
        target = pathlib.Path(args.dir or args.project)
        Project.init(target)
        print(f"Initialized KIMCAD project in {target.resolve()}")
        return 0
    proj = Project.open(args.project)
    if args.cmd == "commit":
        cid, changes = proj.commit(args.file, args.message)
        print(f"[{proj.current_branch()} {cid[:10]}] {args.message}")
        _print_changes(changes)
    elif args.cmd == "status":
        changes = proj.status(args.file)
        print("no changes" if not changes else "")
        if changes:
            _print_changes(changes)
    elif args.cmd == "log":
        commits = proj.log(args.rev, args.n)
        if not commits:
            print("no versions yet")
        for c in commits:
            when = dt.datetime.fromtimestamp(c.time, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(f"{c.id[:10]}  {when}  {c.author_name}  {c.message.strip().splitlines()[0]}")
    elif args.cmd == "diff":
        _print_changes(proj.diff(args.rev_a, args.rev_b), as_json=args.json)
    elif args.cmd == "export":
        out = proj.export(args.out, args.rev, overwrite=args.force)
        print(f"wrote {out}")
    elif args.cmd == "show":
        print(json.dumps(proj.show(args.key, args.rev), ensure_ascii=False, indent=1, sort_keys=True))
    elif args.cmd == "branch":
        if args.name:
            proj.create_branch(args.name, args.rev)
            print(f"created design option {args.name}")
        else:
            cur = proj.current_branch()
            for b in proj.branches():
                print(f"{'*' if b == cur else ' '} {b}")
    elif args.cmd == "switch":
        proj.switch(args.name)
        print(f"switched to {args.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KimcadError as e:
        print(f"kimcad: error: {e}", file=sys.stderr)
        for m in getattr(e, "messages", [])[:20]:
            print(f"  {m}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"kimcad: error: {e}", file=sys.stderr)
        return 1
```

```python
# SPDX-License-Identifier: GPL-3.0-or-later  (python/kimcad/__main__.py)
import sys

from .cli import main

sys.exit(main())
```

`test_empty_project_messages` expects "no versions" from `log`, which `run` prints, and from diff/export through `NoVersions`. `test_not_a_project` relies on the `NotAProject` message from Rust ("not a KIMCAD project").

- [ ] **Step 4: Run the tests until they pass**

Run: `pixi run pytest tests/python/test_cli.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add python/kimcad/cli.py python/kimcad/__main__.py tests/python/test_cli.py
git commit -s -m "feat(cli): kimcad init/commit/status/log/diff/export/show/branch/switch"
```

---

### Task 8: End-to-end exit test, CI, docs

**Files:**
- Create: `tests/python/test_e2e.py`, `.github/workflows/ci.yml`
- Modify: `README.md` (quick start), `docs/07-roadmap.md` (R0–R2 status), `docs/decisions.md` (D40, D41), `docs/02-data-model-and-format.md` (rule 5 wording: deterministic derived ids instead of UUIDv7)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the exit test** `tests/python/test_e2e.py`. This is the Slice 1 exit criterion from the roadmap.

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Slice 1 exit test on a real Revit export (needs the corpus)."""
import json
import pathlib

import blake3
import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.util.element
import pytest

from kimcad.project import Project
from kimcad.records import body_text

ROOT = pathlib.Path(__file__).resolve().parents[2]
DUPLEX = ROOT / "tests/corpus/files/community/IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_A_20110907.ifc"
GOLDEN = json.loads((ROOT / "tests/golden/manifest-windows.json").read_text())
REL = "community/IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_A_20110907.ifc"


@pytest.mark.golden
def test_duplex_property_edit_roundtrip(tmp_path):
    if not DUPLEX.exists():
        pytest.skip("corpus not downloaded")
    proj = Project.init(tmp_path / "duplex")
    proj.commit(DUPLEX, "import Duplex", author=("T", "t@e.org"), time=1)
    v1 = proj.export(tmp_path / "v1.ifc")
    assert blake3.blake3(body_text(v1).encode()).hexdigest()[:32] == GOLDEN[REL][1]

    f = ifcopenshell.open(str(DUPLEX))
    wall = f.by_type("IfcWall")[len(f.by_type("IfcWall")) // 2]
    pset = ifcopenshell.util.element.get_pset(wall, "Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=f.by_id(pset["id"]), properties={"FireRating": "EI60-KIMCAD"})
    edited = tmp_path / "edited.ifc"
    f.write(str(edited))
    _, changes = proj.commit(edited, "FireRating EI60", author=("T", "t@e.org"), time=2)
    assert 1 <= len(changes.items) <= 3, changes.items
    assert any(c.ifc_type == "IfcPropertySet" for c in changes.modified)
    assert not changes.removed

    v2 = proj.export(tmp_path / "v2.ifc")
    assert "EI60-KIMCAD" in body_text(v2)
    assert not proj.status(v2)
```

Run: `pixi run fetch-corpus` then `pixi run pytest -m golden tests/python/test_e2e.py -q`
Expected: 1 passed.

- [ ] **Step 2: CI** `.github/workflows/ci.yml`

```yaml
# SPDX-License-Identifier: GPL-3.0-or-later
name: CI
on:
  push:
  pull_request:
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: prefix-dev/setup-pixi@v0.9.4
        with:
          cache: true
      - run: pixi run test
      - uses: actions/cache@v4
        with:
          path: tests/corpus/files
          key: corpus-v1-${{ hashFiles('tests/corpus/fetch.py') }}
      - run: pixi run fetch-corpus
      - run: pixi run golden
```

(Use the latest `setup-pixi` release tag if a newer one exists.)

- [ ] **Step 3: Docs.**
  - `README.md`: a "Try it" section with `pixi install`, `pixi run build`, `pixi run kimcad init demo`, `commit`/`log`/`diff`/`export`.
  - `docs/07-roadmap.md`: R0 ✅, R1 ✅ (Python decomposer; Rust port later if speed demands it), R2 ✅ except tags, R3 basic record diff ✅.
  - `docs/decisions.md`:
    - **D40:** PyO3 `kimcad._core` for Python ↔ Rust; `cxx` for C++ later (two boundaries, owner choice).
    - **D41:** Slice 1 CLI is Python (it needs ifcopenshell); storage writes via `git fast-import`, one shard level until adaptive sharding is needed.
  - `docs/02` rule 5: "New shared nodes get their content hash; if that collides with an existing node id, it is re-hashed deterministically" (replaces UUIDv7, which would break cross-machine determinism).

- [ ] **Step 4: Full verification**

Run: `pixi run test` then `pixi run golden`
Expected: all pass; the golden run reports passes for every small corpus file.

- [ ] **Step 5: Commit**

```bash
git add tests/python/test_e2e.py .github README.md docs
git commit -s -m "test: slice 1 exit test; ci: Windows+Linux with golden hashes; docs: slice 1 status"
```
