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
        .commit(
            &changes(&[("objects/ab/W1.json", Some("{\"a\":2}")), ("kimcad.json", None), ("nodes/cd/N1.json", Some("[]"))]),
            "second",
            &sig(1_790_000_100),
        )
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

#[test]
fn rejects_signatures_that_would_corrupt_the_commit() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    for (name, email) in [("Evil <x>", "e@x.org"), ("Line\nbreak", "e@x.org"), ("Ok", "bad>mail"), ("", "e@x.org")] {
        let s = Signature { name: name.into(), email: email.into(), time: 1 };
        let r = repo.commit(&changes(&[("a.json", Some("1"))]), "x", &s);
        assert!(matches!(r, Err(Error::InvalidSignature(_))), "accepted {name:?} <{email}>");
    }
    assert_eq!(repo.head().unwrap(), None);
}

#[test]
fn milestones_are_annotated_tags() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    let c1 = repo.commit(&changes(&[("a.json", Some("1"))]), "first", &sig(1_790_000_000)).unwrap();
    repo.create_tag("Concept", "HEAD", "Concept design\nfor the client", &sig(1_790_000_050)).unwrap();
    let c2 = repo.commit(&changes(&[("a.json", Some("2"))]), "second", &sig(1_790_000_100)).unwrap();
    repo.create_tag("Schematic%20design", &c2, "SD", &sig(1_790_000_200)).unwrap();
    let tags = repo.tags().unwrap();
    assert_eq!(tags.iter().map(|t| t.name.as_str()).collect::<Vec<_>>(), vec!["Concept", "Schematic%20design"]);
    assert_eq!(tags[0].target, c1);
    assert_eq!(tags[0].message.trim(), "Concept design\nfor the client");
    assert_eq!(tags[0].time, 1_790_000_050);
    assert_eq!(tags[1].target, c2);
    assert_eq!(repo.resolve("Concept").unwrap(), c1);
    assert!(repo.create_tag("Concept", "HEAD", "again", &sig(1)).is_err()); // names are unique
    assert!(repo.create_tag("-x", "HEAD", "bad", &sig(1)).is_err());
    repo.delete_tag("Concept").unwrap();
    assert_eq!(repo.tags().unwrap().len(), 1);
    assert!(repo.delete_tag("Concept").is_err());
}

#[test]
fn delete_branch_but_not_the_current_one() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    repo.commit(&changes(&[("a.json", Some("1"))]), "base", &sig(1)).unwrap();
    repo.create_branch("option-b", "HEAD").unwrap();
    assert!(repo.delete_branch("main").is_err()); // current
    repo.delete_branch("option-b").unwrap();
    assert_eq!(repo.branches().unwrap(), vec!["main"]);
    assert!(matches!(repo.delete_branch("option-b"), Err(Error::UnknownBranch(_))));
}

#[test]
fn merge_commits_merge_base_and_fast_forward() {
    let dir = tempfile::tempdir().unwrap();
    let repo = Repo::init(dir.path()).unwrap();
    let base = repo.commit(&changes(&[("a.json", Some("1"))]), "base", &sig(1)).unwrap();
    repo.create_branch("b", "HEAD").unwrap();
    let ours = repo.commit(&changes(&[("a.json", Some("2"))]), "ours", &sig(2)).unwrap();
    repo.switch("b").unwrap();
    let theirs = repo.commit(&changes(&[("c.json", Some("3"))]), "theirs", &sig(3)).unwrap();
    repo.switch("main").unwrap();
    assert_eq!(repo.merge_base("main", "b").unwrap().as_deref(), Some(base.as_str()));
    let m = repo.commit_merge(&changes(&[("c.json", Some("3"))]), "combine b", &sig(4), &["b".to_string()]).unwrap();
    let log = repo.log("HEAD", 1).unwrap();
    assert_eq!(log[0].id, m);
    assert_eq!(log[0].parents, vec![ours.clone(), theirs.clone()]);
    assert_eq!(repo.tree_entries("HEAD").unwrap().keys().cloned().collect::<Vec<_>>(), vec!["a.json", "c.json"]);
    // b is behind main now: main contains it, b can fast-forward to main.
    assert_eq!(repo.merge_base("main", "b").unwrap().as_deref(), Some(theirs.as_str()));
    repo.switch("b").unwrap();
    assert_eq!(repo.fast_forward("main").unwrap(), m);
    assert_eq!(repo.head().unwrap().as_deref(), Some(m.as_str()));
    repo.switch("main").unwrap();
    let other = repo.commit(&changes(&[("a.json", Some("5"))]), "more", &sig(5)).unwrap();
    repo.switch("b").unwrap();
    repo.commit(&changes(&[("d.json", Some("6"))]), "diverged", &sig(6)).unwrap();
    assert!(repo.fast_forward(&other).is_err()); // not a fast-forward any more
}
