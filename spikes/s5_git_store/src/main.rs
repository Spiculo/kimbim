//! Spike S5: can a Git object database (via gitoxide) hold a KIMCAD model of N records?
//!
//! Measures, for N synthetic canonical records (default 1,000,000):
//!   1. initial import: write N blobs + sharded trees (objects/<aa>/<bb>/<id>.json) + commit
//!   2. one-record change: tree edit + commit (how many new objects, how long)
//!   3. full read-back of all records from the commit tree ("checkout to model")
//!
//! Usage: s5_git_store <repo-dir> [N] [record-bytes] [fastimport|loose]
//! Put <repo-dir> outside OneDrive/antivirus-scanned folders for meaningful numbers.

use std::collections::BTreeMap;
use std::time::Instant;

use gix::objs::tree::{Entry, EntryKind};
use gix::ObjectId;

fn record(i: u64, size: usize) -> (String, Vec<u8>) {
    // Deterministic pseudo-random record resembling a canonical KIMCAD JSON record.
    let id = blake3::hash(&i.to_le_bytes()).to_hex()[..32].to_string();
    let mut x = i.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
    let mut s = format!(
        "{{\"a\":{{\"GlobalId\":\"{}\",\"Name\":\"Wall-{}\",\"ObjectPlacement\":{{\"a\":{{\"Location\":[",
        &id[..22], i
    );
    while s.len() < size - 40 {
        x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        s.push_str(&format!("{:.4},", (x >> 33) as f64 / 1e5));
    }
    s.push_str("0.0]}}},\"t\":\"IfcWall\"}");
    (id, s.into_bytes())
}

fn sig() -> gix::actor::Signature {
    gix::actor::Signature {
        name: "KIMCAD spike".into(),
        email: "spike@kimcad.invalid".into(),
        time: gix::date::Time { seconds: 1_790_000_000, offset: 0 },
    }
}

type Shards = BTreeMap<String, BTreeMap<String, BTreeMap<String, ObjectId>>>;

fn write_tree(repo: &gix::Repository, entries: Vec<Entry>) -> ObjectId {
    let mut tree = gix::objs::Tree { entries };
    tree.entries.sort(); // git tree ordering
    repo.write_object(&tree).expect("write tree").detach()
}

fn import_loose(repo: &gix::Repository, n: u64, size: usize) -> (ObjectId, ObjectId) {
    // 1. blobs
    let t = Instant::now();
    let mut shards: Shards = BTreeMap::new();
    for i in 0..n {
        let (id, bytes) = record(i, size);
        let oid = repo.write_blob(&bytes).expect("blob").detach();
        shards
            .entry(id[0..2].to_string())
            .or_default()
            .entry(id[2..4].to_string())
            .or_default()
            .insert(format!("{id}.json"), oid);
    }
    let t_blobs = t.elapsed();

    // trees: objects/<aa>/<bb>/<id>.json
    let t = Instant::now();
    let mut top = Vec::new();
    let mut tree_count = 0;
    for (aa, mid) in &shards {
        let mut mid_entries = Vec::new();
        for (bb, leaf) in mid {
            let leaf_entries = leaf
                .iter()
                .map(|(name, oid)| Entry { mode: EntryKind::Blob.into(), filename: name.as_str().into(), oid: *oid })
                .collect();
            let leaf_id = write_tree(repo, leaf_entries);
            tree_count += 1;
            mid_entries.push(Entry { mode: EntryKind::Tree.into(), filename: bb.as_str().into(), oid: leaf_id });
        }
        let mid_id = write_tree(repo, mid_entries);
        tree_count += 1;
        top.push(Entry { mode: EntryKind::Tree.into(), filename: aa.as_str().into(), oid: mid_id });
    }
    let objects_id = write_tree(repo, top);
    let root = write_tree(repo, vec![Entry { mode: EntryKind::Tree.into(), filename: "objects".into(), oid: objects_id }]);
    tree_count += 2;
    let s = sig();
    let (mut b1, mut b2) = (gix::date::parse::TimeBuf::default(), gix::date::parse::TimeBuf::default());
    let c1 = repo
        .commit_as(s.to_ref(&mut b1), s.to_ref(&mut b2), "refs/heads/main", "Initial import", root, gix::commit::NO_PARENT_IDS)
        .expect("commit")
        .detach();
    let t_trees = t.elapsed();
    println!("import: blobs {:.1}s, {} trees + commit {:.1}s, root tree {root}", t_blobs.as_secs_f64(), tree_count, t_trees.as_secs_f64());

    (root, c1)
}

/// Bulk import through `git fast-import`: one packfile, no loose objects.
fn import_fast(dir: &std::path::Path, n: u64, size: usize) -> (gix::Repository, ObjectId, ObjectId) {
    use std::io::Write;
    let t = Instant::now();
    let mut child = std::process::Command::new("git")
        .args(["fast-import", "--quiet"])
        .current_dir(dir)
        .stdin(std::process::Stdio::piped())
        .spawn()
        .expect("git fast-import");
    {
        let mut w = std::io::BufWriter::with_capacity(1 << 20, child.stdin.take().unwrap());
        let msg = b"Initial import";
        write!(w, "commit refs/heads/main
committer KIMCAD spike <spike@kimcad.invalid> 1790000000 +0000
data {}
", msg.len()).unwrap();
        w.write_all(msg).unwrap();
        w.write_all(b"
").unwrap();
        for i in 0..n {
            let (id, bytes) = record(i, size);
            write!(w, "M 100644 inline objects/{}/{}/{id}.json
data {}
", &id[0..2], &id[2..4], bytes.len()).unwrap();
            w.write_all(&bytes).unwrap();
            w.write_all(b"
").unwrap();
        }
        w.write_all(b"done
").unwrap();
    }
    assert!(child.wait().unwrap().success());
    let repo = gix::open(dir).expect("open");
    let c1 = repo.find_reference("refs/heads/main").unwrap().id().detach();
    let root = repo.find_commit(c1).unwrap().tree_id().unwrap().detach();
    println!("import (fast-import, single pack): {:.1}s, root tree {root}", t.elapsed().as_secs_f64());
    (repo, root, c1)
}

/// Read every record of refs/heads/main: sequential, then parallel (thread-local repo handles).
fn read_only(dir: &std::path::Path) {
    use rayon::prelude::*;
    let mut repo = gix::open(dir).expect("open");
    repo.object_cache_size_if_unset(64 << 20);
    let c = repo.find_reference("refs/heads/main").unwrap().id().detach();
    let t = Instant::now();
    let mut rec = gix::traverse::tree::Recorder::default();
    {
        let tree = repo.find_commit(c).unwrap().tree().unwrap();
        tree.traverse().breadthfirst(&mut rec).unwrap();
    }
    let blobs: Vec<ObjectId> = rec.records.iter().filter(|e| e.mode.is_blob()).map(|e| e.oid).collect();
    println!("tree walk: {} blobs in {:.2}s", blobs.len(), t.elapsed().as_secs_f64());
    let t = Instant::now();
    let total: usize = blobs.iter().map(|o| repo.find_object(*o).unwrap().data.len()).sum();
    println!("sequential read: {:.1} MB in {:.1}s", total as f64 / 1e6, t.elapsed().as_secs_f64());
    let sync = repo.into_sync();
    let t = Instant::now();
    let total: usize = blobs
        .par_iter()
        .map_init(|| { let mut r = sync.to_thread_local(); r.object_cache_size_if_unset(16 << 20); r }, |r, o| r.find_object(*o).unwrap().data.len())
        .sum();
    println!("parallel read ({} threads): {:.1} MB in {:.1}s", rayon::current_num_threads(), total as f64 / 1e6, t.elapsed().as_secs_f64());
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let dir = std::path::PathBuf::from(args.get(1).expect("usage: s5_git_store <repo-dir> [N] [bytes]"));
    let n: u64 = args.get(2).map(|s| s.parse().unwrap()).unwrap_or(1_000_000);
    let size: usize = args.get(3).map(|s| s.parse().unwrap()).unwrap_or(700);
    if args.get(4).map(String::as_str) == Some("read") {
        read_only(&dir);
        return;
    }
    if dir.exists() {
        std::fs::remove_dir_all(&dir).unwrap();
    }
    let repo = gix::init_bare(&dir).expect("init");
    let args4 = args.get(4).cloned().unwrap_or_default();
    println!("mode = {}", if args4.is_empty() { "fastimport" } else { &args4 });
    println!("N = {n}, record ~{size} B, repo = {}", dir.display());

    let mode = args.get(4).map(String::as_str).unwrap_or("fastimport");
    let s = sig();
    let (mut b1, mut b2) = (gix::date::parse::TimeBuf::default(), gix::date::parse::TimeBuf::default());
    let (repo, root, c1) = if mode == "loose" {
        let (root, c1) = import_loose(&repo, n, size);
        (repo, root, c1)
    } else {
        import_fast(&dir, n, size)
    };

    // 2. change one record
    let t = Instant::now();
    let (id, mut bytes) = record(n / 2, size);
    bytes.extend_from_slice(b" ");
    let new_blob = repo.write_blob(&bytes).unwrap().detach();
    let mut editor = repo.edit_tree(root).expect("editor");
    editor
        .upsert(format!("objects/{}/{}/{id}.json", &id[0..2], &id[2..4]), EntryKind::Blob, new_blob)
        .expect("upsert");
    let root2 = editor.write().expect("write").detach();
    let c2 = repo
        .commit_as(s.to_ref(&mut b1), s.to_ref(&mut b2), "refs/heads/main", "Change one record", root2, [c1])
        .unwrap()
        .detach();
    println!("one-record commit: {:.1} ms ({c2})", t.elapsed().as_secs_f64() * 1e3);

    // 3. read back everything from the commit
    let t = Instant::now();
    let mut repo = repo;
    repo.object_cache_size_if_unset(64 << 20);
    let tree = repo.find_commit(c2).unwrap().tree().unwrap();
    let mut recorder = gix::traverse::tree::Recorder::default();
    tree.traverse().breadthfirst(&mut recorder).unwrap();
    let mut total = 0usize;
    let mut count = 0u64;
    for e in recorder.records.iter().filter(|e| e.mode.is_blob()) {
        total += repo.find_object(e.oid).unwrap().data.len();
        count += 1;
    }
    println!("read-back: {count} records, {:.1} MB in {:.1}s", total as f64 / 1e6, t.elapsed().as_secs_f64());
}
