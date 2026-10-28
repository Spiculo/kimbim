// SPDX-License-Identifier: GPL-3.0-or-later
//! Git-backed record store for KimBim (docs/03-versioning.md, D39).
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
    #[error("not a KimBim project (no .git found): {0}")]
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
    #[error("invalid author identity (empty, or contains '<', '>' or a line break): {0:?}")]
    InvalidSignature(String),
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

/// A milestone: an annotated tag on a version.
#[derive(Debug, Clone)]
pub struct TagInfo {
    pub name: String,
    /// The tagged commit.
    pub target: String,
    pub message: String,
    pub tagger_name: String,
    /// Seconds since the Unix epoch, UTC.
    pub time: i64,
}

pub struct Repo {
    git_dir: PathBuf,
}

fn git_err(e: impl std::fmt::Display) -> Error {
    Error::Git(e.to_string())
}

fn oid(hex: &str) -> Result<gix::ObjectId> {
    gix::ObjectId::from_hex(hex.as_bytes()).map_err(|_| Error::InvalidOid(hex.to_string()))
}

fn tree_entries(repo: &gix::Repository, id: gix::ObjectId) -> Result<Vec<gix::objs::tree::Entry>> {
    let tree = repo.find_tree(id).map_err(git_err)?;
    let mut out = Vec::new();
    for entry in tree.iter() {
        let entry = entry.map_err(git_err)?;
        out.push(gix::objs::tree::Entry {
            mode: entry.mode(),
            filename: entry.filename().to_owned(),
            oid: entry.oid().to_owned(),
        });
    }
    Ok(out)
}

fn collect_tree(repo: &gix::Repository, id: gix::ObjectId, prefix: &str, old: bool,
                out: &mut Vec<(String, Option<String>, Option<String>)>) -> Result<()> {
    for entry in tree_entries(repo, id)? {
        let path = format!("{prefix}{}", entry.filename);
        if entry.mode.is_tree() {
            collect_tree(repo, entry.oid, &format!("{path}/"), old, out)?;
        } else {
            let oid = Some(entry.oid.to_string());
            out.push(if old { (path, oid, None) } else { (path, None, oid) });
        }
    }
    Ok(())
}

fn walk_diff(repo: &gix::Repository, a: gix::ObjectId, b: gix::ObjectId, prefix: &str,
             out: &mut Vec<(String, Option<String>, Option<String>)>) -> Result<()> {
    if a == b {
        return Ok(());
    }
    let mut ae = tree_entries(repo, a)?.into_iter().peekable();
    let mut be = tree_entries(repo, b)?.into_iter().peekable();
    let push_only = |entry: gix::objs::tree::Entry, old: bool, out: &mut Vec<_>| -> Result<()> {
        let path = format!("{prefix}{}", entry.filename);
        if entry.mode.is_tree() {
            collect_tree(repo, entry.oid, &format!("{path}/"), old, out)
        } else {
            let oid = Some(entry.oid.to_string());
            out.push(if old { (path, oid, None) } else { (path, None, oid) });
            Ok(())
        }
    };
    loop {
        let (next_a, next_b) = (ae.peek(), be.peek());
        match (next_a, next_b) {
            (None, None) => break,
            (Some(_), None) => push_only(ae.next().unwrap(), true, out)?,
            (None, Some(_)) => push_only(be.next().unwrap(), false, out)?,
            (Some(x), Some(y)) => {
                let (name_a, name_b) = (&x.filename, &y.filename);
                match name_a.cmp(name_b) {
                    std::cmp::Ordering::Less => push_only(ae.next().unwrap(), true, out)?,
                    std::cmp::Ordering::Greater => push_only(be.next().unwrap(), false, out)?,
                    std::cmp::Ordering::Equal => {
                        let (x, y) = (ae.next().unwrap(), be.next().unwrap());
                        let path = format!("{prefix}{}", x.filename);
                        if x.mode.is_tree() && y.mode.is_tree() {
                            walk_diff(repo, x.oid, y.oid, &format!("{path}/"), out)?;
                        } else if x.oid != y.oid || x.mode != y.mode {
                            out.push((path, Some(x.oid.to_string()), Some(y.oid.to_string())));
                        }
                    }
                }
            }
        }
    }
    Ok(())
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
        let unknown = || Error::UnknownRev(rev.to_string());
        let id = repo.rev_parse_single(rev).map_err(|_| unknown())?;
        let commit = id.object().map_err(git_err)?.peel_to_commit().map_err(|_| unknown())?;
        Ok(commit.id.to_string())
    }

    pub fn tree_entries(&self, rev: &str) -> Result<BTreeMap<String, String>> {
        let repo = self.gix()?;
        let tree = repo.find_commit(oid(&self.resolve(rev)?)?).map_err(git_err)?.tree().map_err(git_err)?;
        let mut rec = gix::traverse::tree::Recorder::default();
        tree.traverse().breadthfirst(&mut rec).map_err(git_err)?;
        Ok(rec
            .records
            .into_iter()
            .filter(|e| e.mode.is_blob())
            .map(|e| (e.filepath.to_string(), e.oid.to_string()))
            .collect())
    }

    /// The paths whose blobs differ between two revisions, as (path, old oid, new oid). Identical
    /// subtrees are skipped by their tree id, so the cost follows the change, not the tree size.
    pub fn diff_entries(&self, a_rev: &str, b_rev: &str) -> Result<Vec<(String, Option<String>, Option<String>)>> {
        let repo = self.gix()?;
        let a = repo.find_commit(oid(&self.resolve(a_rev)?)?).map_err(git_err)?.tree().map_err(git_err)?.id;
        let b = repo.find_commit(oid(&self.resolve(b_rev)?)?).map_err(git_err)?.tree().map_err(git_err)?.id;
        let mut out = Vec::new();
        walk_diff(&repo, a, b, "", &mut out)?;
        out.sort_by(|x, y| x.0.cmp(&y.0));
        Ok(out)
    }

    /// One blob by its path in a revision's tree, without listing the whole tree (settings, meta).
    pub fn read_blob_at(&self, rev: &str, path: &str) -> Result<Option<Vec<u8>>> {
        let repo = self.gix()?;
        let mut id = repo.find_commit(oid(&self.resolve(rev)?)?).map_err(git_err)?
            .tree().map_err(git_err)?.id;
        let parts: Vec<&str> = path.split('/').collect();
        for (i, part) in parts.iter().enumerate() {
            let entry = tree_entries(&repo, id)?.into_iter()
                .find(|e| e.filename.to_string() == *part);
            let Some(entry) = entry else { return Ok(None) };
            if i + 1 == parts.len() {
                if !entry.mode.is_blob() {
                    return Ok(None);
                }
                let object = repo.find_object(entry.oid).map_err(git_err)?;
                return Ok(Some(object.data.clone()));
            }
            if !entry.mode.is_tree() {
                return Ok(None);
            }
            id = entry.oid;
        }
        Ok(None)
    }

    pub fn read_blobs(&self, oids: &[String]) -> Result<Vec<Vec<u8>>> {
        let ids = oids.iter().map(|h| oid(h)).collect::<Result<Vec<_>>>()?;
        let repo = self.gix()?;
        // Load every pack index on this thread before the threads share the store. gix loads indices
        // lazily, and when several threads race to load them one can be told "not found" for an object
        // whose index another thread is loading (intermittent, ~1 read in 500 on Windows).
        repo.objects.packed_object_count().map_err(git_err)?;
        let sync = repo.into_sync();
        ids.par_iter()
            .map_init(
                || sync.to_thread_local(),
                |r, id| r.find_object(*id).map(|o| o.data.clone()).map_err(git_err),
            )
            .collect()
    }

    pub fn commit(&self, changes: &BTreeMap<String, Option<Vec<u8>>>, message: &str, author: &Signature) -> Result<String> {
        self.commit_merge(changes, message, author, &[])
    }

    /// A commit on the current branch whose extra parents are `merged` (a merge commit when non-empty).
    pub fn commit_merge(
        &self,
        changes: &BTreeMap<String, Option<Vec<u8>>>,
        message: &str,
        author: &Signature,
        merged: &[String],
    ) -> Result<String> {
        let merged = merged.iter().map(|r| self.resolve(r)).collect::<Result<Vec<_>>>()?;
        for path in changes.keys() {
            validate_path(path)?;
        }
        validate_signature(author)?;
        let branch = self.current_branch()?;
        let parent = self.head()?;
        let mut child = self
            .git()
            .args(["fast-import", "--quiet", "--done"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()?;
        {
            let mut w = std::io::BufWriter::with_capacity(1 << 20, child.stdin.take().expect("piped stdin"));
            let who = format!("{} <{}> {} +0000", author.name, author.email, author.time);
            write!(w, "commit refs/heads/{branch}\nauthor {who}\ncommitter {who}\ndata {}\n", message.len())?;
            w.write_all(message.as_bytes())?;
            w.write_all(b"\n")?;
            if let Some(p) = &parent {
                writeln!(w, "from {p}")?;
            }
            for m in &merged {
                writeln!(w, "merge {m}")?;
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
        let mut next = Some(oid(&self.resolve(rev)?)?);
        let mut out = Vec::new();
        while let Some(id) = next {
            if out.len() >= limit {
                break;
            }
            let c = repo.find_commit(id).map_err(git_err)?;
            let author = c.author().map_err(git_err)?;
            let parents: Vec<String> = c.parent_ids().map(|p| p.to_string()).collect();
            next = parents.first().map(|p| oid(p)).transpose()?;
            out.push(CommitInfo {
                id: id.to_string(),
                author_name: author.name.to_string(),
                author_email: author.email.to_string(),
                time: author.time().map_err(git_err)?.seconds,
                message: c.message_raw_sloppy().to_string(),
                parents,
            });
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

    /// The best common ancestor of two versions, if any.
    pub fn merge_base(&self, a: &str, b: &str) -> Result<Option<String>> {
        let (a, b) = (self.resolve(a)?, self.resolve(b)?);
        let out = self.git().args(["merge-base", &a, &b]).output()?;
        if !out.status.success() {
            return Ok(None); // no common history
        }
        Ok(Some(String::from_utf8_lossy(&out.stdout).trim().to_string()))
    }

    /// Move the current branch forward to `rev` (which must contain its head).
    pub fn fast_forward(&self, rev: &str) -> Result<String> {
        let target = self.resolve(rev)?;
        let branch = self.current_branch()?;
        let head = self.head()?.ok_or_else(|| Error::Git("nothing to fast-forward".into()))?;
        if self.merge_base(&head, &target)?.as_deref() != Some(head.as_str()) {
            return Err(Error::Git(format!("{rev} does not contain the current version")));
        }
        self.run(self.git().args(["update-ref", &format!("refs/heads/{branch}"), &target, &head]))?;
        Ok(target)
    }

    pub fn delete_branch(&self, name: &str) -> Result<()> {
        if !self.branches()?.iter().any(|b| b == name) {
            return Err(Error::UnknownBranch(name.to_string()));
        }
        if self.current_branch()? == name {
            return Err(Error::Git(format!("{name} is the current branch")));
        }
        self.run(self.git().args(["branch", "-D", "--", name]))
    }

    /// An annotated tag (a milestone) on `rev`, signed by `tagger` at its time.
    pub fn create_tag(&self, name: &str, rev: &str, message: &str, tagger: &Signature) -> Result<()> {
        validate_signature(tagger)?;
        if name.starts_with('-') || name.trim().is_empty() {
            return Err(Error::Git(format!("invalid tag name {name:?}")));
        }
        let target = self.resolve(rev)?;
        let mut c = self.git();
        c.env("GIT_COMMITTER_NAME", &tagger.name)
            .env("GIT_COMMITTER_EMAIL", &tagger.email)
            .env("GIT_COMMITTER_DATE", format!("{} +0000", tagger.time))
            .args(["tag", "-a", "-m", message, name, &target]);
        self.run(&mut c)
    }

    /// Annotated and lightweight tags, sorted by name.
    pub fn tags(&self) -> Result<Vec<TagInfo>> {
        let out = self
            .git()
            .args([
                "for-each-ref",
                "refs/tags",
                "--format=%(refname:strip=2)%1f%(*objectname)%1f%(objectname)%1f%(taggername)%1f%(taggerdate:unix)%1f%(contents)%1e",
            ])
            .output()?;
        if !out.status.success() {
            return Err(Error::Git(String::from_utf8_lossy(&out.stderr).into_owned()));
        }
        let text = String::from_utf8_lossy(&out.stdout);
        let mut tags = Vec::new();
        for record in text.split('\x1e') {
            let f: Vec<&str> = record.trim_start_matches('\n').split('\x1f').collect();
            if f.len() < 6 {
                continue;
            }
            tags.push(TagInfo {
                name: f[0].to_string(),
                target: if f[1].is_empty() { f[2] } else { f[1] }.to_string(),
                tagger_name: f[3].to_string(),
                time: f[4].trim().parse().unwrap_or(0),
                message: f[5].to_string(),
            });
        }
        tags.sort_by(|a, b| a.name.cmp(&b.name));
        Ok(tags)
    }

    pub fn delete_tag(&self, name: &str) -> Result<()> {
        if !self.tags()?.iter().any(|t| t.name == name) {
            return Err(Error::UnknownRev(name.to_string()));
        }
        self.run(self.git().args(["tag", "-d", "--", name]))
    }

    fn run(&self, c: &mut Command) -> Result<()> {
        let st = c.output()?;
        if !st.status.success() {
            return Err(Error::Git(String::from_utf8_lossy(&st.stderr).into_owned()));
        }
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

/// fast-import idents are `Name <email> time tz`: these characters would corrupt the stream.
fn validate_signature(s: &Signature) -> Result<()> {
    let bad = |v: &str| v.trim().is_empty() || v.contains(['<', '>', '\n', '\r']);
    if bad(&s.name) || bad(&s.email) {
        return Err(Error::InvalidSignature(format!("{} <{}>", s.name, s.email)));
    }
    Ok(())
}

fn validate_path(p: &str) -> Result<()> {
    let bad = p.is_empty()
        || p.starts_with('/')
        || p.contains('\n')
        || p.contains('\\')
        || p.split('/').any(|c| c.is_empty() || c == "." || c == ".." || c == ".git");
    if bad { Err(Error::InvalidPath(p.to_string())) } else { Ok(()) }
}
