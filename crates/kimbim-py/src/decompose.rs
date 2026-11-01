// SPDX-License-Identifier: GPL-3.0-or-later
//! Rust decomposer (docs/19, stage 3).
//!
//! Consumes the tab-separated dump produced by `tools/ifcdump` and reproduces `records.py`:
//! hash-consing, content classes, INLINE/ANCHORED/NODE, anchor paths, loose records, duplicate
//! GlobalIds and canonical JSON bytes. The Python decomposer stays authoritative until the
//! golden/versioning tests compare both record dicts and `state_hash`.
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt::Write as _;

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum AggKind {
    Array,
    Bag,
    List,
    Set,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum Tree {
    Unknown,
    Named(String),
    Agg(AggKind, Box<Tree>),
    Simple(String),
}

fn parse_tree(text: &str) -> Tree {
    if let Some(open) = text.find('<') {
        if text.ends_with('>') {
            let kind = match &text[..open] {
                "ARRAY" => Some(AggKind::Array),
                "BAG" => Some(AggKind::Bag),
                "LIST" => Some(AggKind::List),
                "SET" => Some(AggKind::Set),
                _ => None,
            };
            if let Some(kind) = kind {
                return Tree::Agg(kind, Box::new(parse_tree(&text[open + 1..text.len() - 1])));
            }
        }
    }
    match text {
        "?" | "" => Tree::Unknown,
        "BINARY" | "BOOLEAN" | "INTEGER" | "LOGICAL" | "NUMBER" | "REAL" | "STRING" => {
            Tree::Simple(text.to_string())
        }
        other => Tree::Named(other.to_string()),
    }
}

fn agg_kind(tree: Option<&Tree>) -> Option<AggKind> {
    match tree {
        Some(Tree::Agg(kind, _)) => Some(*kind),
        _ => None,
    }
}

fn elem_tree(tree: Option<&Tree>) -> Option<&Tree> {
    match tree {
        Some(Tree::Agg(_, elem)) => Some(elem),
        _ => None,
    }
}

#[derive(Clone, Debug)]
enum Val {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    List(Vec<Val>),
    Ref(u32),
    Typed(String, Box<Val>),
}

fn parse_val(value: serde_json::Value) -> Result<Val, String> {
    Ok(match value {
        serde_json::Value::Null => Val::Null,
        serde_json::Value::Bool(v) => Val::Bool(v),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Val::Int(i)
            } else if let Some(f) = n.as_f64() {
                Val::Float(f)
            } else {
                return Err(format!("unsupported number {n}"));
            }
        }
        serde_json::Value::String(s) => Val::Str(s),
        serde_json::Value::Array(items) => {
            Val::List(items.into_iter().map(parse_val).collect::<Result<_, _>>()?)
        }
        serde_json::Value::Object(map) => {
            if let Some(serde_json::Value::Number(n)) = map.get("ref") {
                let id = n.as_u64().ok_or("bad ref")? as u32;
                Val::Ref(id)
            } else if let Some(serde_json::Value::String(t)) = map.get("@t") {
                let inner = parse_val(map.get("v").cloned().unwrap_or(serde_json::Value::Null))?;
                Val::Typed(t.clone(), Box::new(inner))
            } else {
                return Err(format!("unexpected object {map:?}"));
            }
        }
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Kind {
    Inline,
    Anchored,
    Node,
}

struct Attr {
    name: String,
    tree: Tree,
    val: Val,
}

struct Entity {
    id: u32,
    ty: String,
    attrs: Vec<Attr>,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
struct Edge {
    parent: String,
    attr: String,
    path: Vec<usize>,
}

// ---------------------------------------------------------------- canonical JSON

fn json_escape(text: &str, out: &mut String) {
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

/// Python `repr(float)`: shortest round-trip digits, but exponents keep a sign and two digits.
pub fn python_float_repr(f: f64) -> String {
    let text = format!("{f:?}");
    match text.find('e') {
        Some(pos) => {
            let (mantissa, exp) = text.split_at(pos);
            let exp = &exp[1..];
            let (sign, digits) = if let Some(d) = exp.strip_prefix('-') {
                ("-", d)
            } else if let Some(d) = exp.strip_prefix('+') {
                ("+", d)
            } else {
                ("+", exp)
            };
            if digits.len() < 2 {
                format!("{mantissa}e{sign}0{digits}")
            } else {
                format!("{mantissa}e{sign}{digits}")
            }
        }
        None => text,
    }
}

#[derive(Clone, Debug)]
enum J {
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Arr(Vec<J>),
    Obj(BTreeMap<String, J>),
}

fn write_json(value: &J, out: &mut String) {
    match value {
        J::Null => out.push_str("null"),
        J::Bool(true) => out.push_str("true"),
        J::Bool(false) => out.push_str("false"),
        J::Int(v) => {
            let _ = write!(out, "{v}");
        }
        J::Float(v) => out.push_str(&python_float_repr(*v)),
        J::Str(v) => json_escape(v, out),
        J::Arr(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_json(item, out);
            }
            out.push(']');
        }
        J::Obj(map) => {
            out.push('{');
            for (i, (key, item)) in map.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                json_escape(key, out);
                out.push(':');
                write_json(item, out);
            }
            out.push('}');
        }
    }
}

fn canon(value: &J) -> Vec<u8> {
    let mut out = String::new();
    write_json(value, &mut out);
    out.into_bytes()
}

fn hash(bytes: &[u8]) -> String {
    blake3::hash(bytes).to_hex()[..32].to_string()
}

fn norm_float(v: f64) -> Result<f64, String> {
    if !v.is_finite() {
        return Err("NaN/Inf not allowed in IFC".to_string());
    }
    Ok(if v == 0.0 { 0.0 } else { v })
}

// ---------------------------------------------------------------- content keys

/// Content-key encoding. It need not match `records._kv` byte for byte: only the equality classes
/// matter, and this encoding is injective. SET members are sorted, exactly like the Python key.
fn key_of(
    value: &Val,
    tree: Option<&Tree>,
    d: &Decomp,
    memo: &mut HashMap<u32, String>,
) -> Result<String, String> {
    Ok(match value {
        Val::Null => "n;".to_string(),
        Val::Bool(v) => format!("b{};", i32::from(*v)),
        Val::Int(v) => format!("i{v};"),
        Val::Float(v) => format!("f{:016x};", norm_float(*v)?.to_bits()),
        Val::Str(v) => format!("s{}:{};", v.len(), v),
        Val::Ref(id) => {
            if d.gid.contains_key(id) {
                format!("R{};", d.gid[id])
            } else {
                format!("E{};", entity_key(*id, d, memo)?)
            }
        }
        Val::Typed(name, inner) => {
            // records._kv passes t=None inside typed values, so SETs there are NOT sorted.
            format!("T{}:{};", name.len(), name) + &key_of(inner, None, d, memo)?
        }
        Val::List(items) => {
            let mut parts = Vec::with_capacity(items.len());
            let sub = elem_tree(tree);
            for item in items {
                parts.push(key_of(item, sub, d, memo)?);
            }
            if agg_kind(tree) == Some(AggKind::Set) {
                parts.sort();
            }
            let mut out = String::from("[");
            for part in parts {
                let _ = write!(out, "{}:{},", part.len(), part);
            }
            out.push(']');
            out
        }
    })
}

fn entity_key(id: u32, d: &Decomp, memo: &mut HashMap<u32, String>) -> Result<String, String> {
    if let Some(key) = memo.get(&id) {
        return Ok(key.clone());
    }
    let entity = d.entity(id)?;
    let mut parts = Vec::with_capacity(entity.attrs.len() + 1);
    parts.push(entity.ty.clone());
    for attr in &entity.attrs {
        parts.push(key_of(&attr.val, Some(&attr.tree), d, memo)?);
    }
    let joined = parts.join("(");
    let key = hash(joined.as_bytes());
    memo.insert(id, key.clone());
    Ok(key)
}

// ---------------------------------------------------------------- decomposer

pub struct Decomp {
    schema: String,
    types: HashMap<String, Tree>,
    entities: Vec<Entity>,
    index: HashMap<u32, usize>,
    is_root_type: HashMap<String, bool>,
    pub gid: HashMap<u32, String>,
    pub issues: Vec<String>,
    ckey: HashMap<u32, String>,
    kind: HashMap<u32, Kind>,
    anchor_of: HashMap<u32, String>,
    node_key: HashMap<String, String>,
    pub inst_node_key: HashMap<u32, String>,
    pub fresh_ids: HashMap<String, String>,
    pub records: BTreeMap<String, Vec<u8>>,
    visiting: HashSet<u32>,
    resolver: Option<Py<PyAny>>,
}

impl Decomp {
    pub fn parse(dump: &str) -> Result<Self, String> {
        let mut schema = String::new();
        let mut types = HashMap::new();
        let mut parents: HashMap<String, String> = HashMap::new();
        let mut entities: Vec<Entity> = Vec::new();
        let mut index = HashMap::new();
        let mut current: Option<Entity> = None;
        for line in dump.lines() {
            if line.is_empty() {
                continue;
            }
            let parts: Vec<&str> = line.split('\t').collect();
            match parts.as_slice() {
                ["schema", name] => {
                    schema = (*name).to_string();
                }
                ["type", name, tree] => {
                    types.insert((*name).to_string(), parse_tree(tree));
                }
                ["entity", name, parent] => {
                    parents.insert((*name).to_string(), (*parent).to_string());
                }
                [eid, ty, attr, _agg, tree, raw] => {
                    let id: u32 = eid.parse().map_err(|_| format!("bad id {eid}"))?;
                    let value: serde_json::Value =
                        serde_json::from_str(raw).map_err(|e| format!("bad JSON on #{id}.{attr}: {e}"))?;
                    let value = parse_val(value)?;
                    if current.as_ref().map(|e| e.id) != Some(id) {
                        if let Some(entity) = current.take() {
                            index.insert(entity.id, entities.len());
                            entities.push(entity);
                        }
                        current = Some(Entity { id, ty: (*ty).to_string(), attrs: Vec::new() });
                    }
                    current.as_mut().unwrap().attrs.push(Attr {
                        name: (*attr).to_string(),
                        tree: parse_tree(tree),
                        val: value,
                    });
                }
                _ => return Err(format!("unexpected dump line {line:?}")),
            }
        }
        if let Some(entity) = current.take() {
            index.insert(entity.id, entities.len());
            entities.push(entity);
        }
        let mut is_root_type = HashMap::new();
        for name in parents.keys() {
            let mut cur = name.as_str();
            let mut root = false;
            let mut hops = 0;
            loop {
                if cur == "IfcRoot" {
                    root = true;
                    break;
                }
                match parents.get(cur) {
                    Some(parent) if !parent.is_empty() && hops < 64 => {
                        cur = parent;
                        hops += 1;
                    }
                    _ => break,
                }
            }
            is_root_type.insert(name.clone(), root);
        }
        Ok(Self {
            schema,
            types,
            entities,
            index,
            is_root_type,
            gid: HashMap::new(),
            issues: Vec::new(),
            ckey: HashMap::new(),
            kind: HashMap::new(),
            anchor_of: HashMap::new(),
            node_key: HashMap::new(),
            inst_node_key: HashMap::new(),
            fresh_ids: HashMap::new(),
            records: BTreeMap::new(),
            visiting: HashSet::new(),
            resolver: None,
        })
    }

    fn entity(&self, id: u32) -> Result<&Entity, String> {
        self.index
            .get(&id)
            .and_then(|i| self.entities.get(*i))
            .ok_or_else(|| format!("entity #{id} missing from the dump"))
    }

    fn global_id<'a>(&self, entity: &'a Entity) -> Option<&'a str> {
        entity.attrs.iter().find_map(|a| {
            if a.name == "GlobalId" {
                if let Val::Str(s) = &a.val {
                    return Some(s.as_str());
                }
            }
            None
        })
    }

    /// Map every entity id to the list of places that reference it: (referrer id, attr name, path).
    fn build_refs(&self) -> HashMap<u32, Vec<(u32, String, Vec<usize>)>> {
        fn walk(
            value: &Val,
            owner: u32,
            attr: &str,
            path: &mut Vec<usize>,
            out: &mut HashMap<u32, Vec<(u32, String, Vec<usize>)>>,
        ) {
            match value {
                Val::Ref(target) => {
                    out.entry(*target).or_default().push((owner, attr.to_string(), path.clone()));
                }
                Val::List(items) => {
                    for (i, item) in items.iter().enumerate() {
                        path.push(i);
                        walk(item, owner, attr, path, out);
                        path.pop();
                    }
                }
                Val::Typed(_, _) => {} // records._positions does not look inside typed values
                _ => {}
            }
        }
        let mut out: HashMap<u32, Vec<(u32, String, Vec<usize>)>> = HashMap::new();
        for entity in &self.entities {
            for attr in &entity.attrs {
                walk(&attr.val, entity.id, &attr.name, &mut Vec::new(), &mut out);
            }
        }
        out
    }

    pub fn classify(&mut self) -> Result<(), String> {
        // Duplicate GlobalIds: first in file order keeps the id, later ones get "~1", "~2"...
        let mut count: HashMap<String, usize> = HashMap::new();
        let roots: Vec<u32> = self
            .entities
            .iter()
            .filter(|e| self.is_root_type.get(&e.ty).copied().unwrap_or(false))
            .map(|e| e.id)
            .collect();
        for id in roots {
            let entity = self.entity(id)?;
            let global = self
                .global_id(entity)
                .map(str::to_string)
                .ok_or_else(|| format!("IfcRoot #{id} {} has no GlobalId", entity.ty))?;
            let n = count.get(&global).copied().unwrap_or(0);
            count.insert(global.clone(), n + 1);
            if n > 0 {
                self.issues.push(format!("duplicate GlobalId {global} (occurrence {}, #{id})", n + 1));
                self.gid.insert(id, format!("{global}~{n}"));
            } else {
                self.gid.insert(id, global);
            }
        }
        // Hash-cons every non-rooted entity.
        let mut memo = HashMap::new();
        let non_rooted: Vec<u32> = self
            .entities
            .iter()
            .filter(|e| !self.gid.contains_key(&e.id))
            .map(|e| e.id)
            .collect();
        for id in non_rooted {
            let key = entity_key(id, self, &mut memo)?;
            self.ckey.insert(id, key);
        }
        // Reference edges between content classes, collapsed per class.
        let refs = self.build_refs();
        let mut edges: HashMap<String, HashSet<Edge>> = HashMap::new();
        for entity in &self.entities {
            if self.gid.contains_key(&entity.id) {
                continue;
            }
            let class = self.ckey[&entity.id].clone();
            let set = edges.entry(class).or_default();
            if let Some(referrers) = refs.get(&entity.id) {
                for (parent_id, attr, path) in referrers {
                    let parent = if let Some(global) = self.gid.get(parent_id) {
                        format!("R{global}")
                    } else {
                        self.ckey
                            .get(parent_id)
                            .cloned()
                            .ok_or_else(|| format!("referrer #{parent_id} has no content class"))?
                    };
                    set.insert(Edge { parent, attr: attr.clone(), path: path.clone() });
                }
            }
        }
        // Kind per content class.
        let mut ckind: HashMap<String, (Kind, Option<String>)> = HashMap::new();
        for (class, set) in &edges {
            if set.len() <= 1 {
                ckind.insert(class.clone(), (Kind::Inline, None));
                continue;
            }
            let root_edges: Vec<&Edge> = set.iter().filter(|e| e.parent.starts_with('R')).collect();
            if root_edges.len() == 1 && root_edges[0].path.is_empty() {
                let path = format!("{}/{}", &root_edges[0].parent[1..], root_edges[0].attr);
                ckind.insert(class.clone(), (Kind::Anchored, Some(path)));
            } else {
                ckind.insert(class.clone(), (Kind::Node, None));
            }
        }
        for (id, class) in &self.ckey {
            let (kind, path) = ckind
                .get(class)
                .cloned()
                .ok_or_else(|| format!("no classification for content class {class}"))?;
            self.kind.insert(*id, kind);
            if let Some(path) = path {
                self.anchor_of.insert(*id, path);
            }
        }
        Ok(())
    }

    fn value(
        &mut self,
        value: &Val,
        tree: Option<&Tree>,
        owner: Option<u32>,
        attr: Option<&str>,
    ) -> Result<Option<J>, String> {
        Ok(match value {
            Val::Null => None,
            Val::Bool(v) => Some(J::Bool(*v)),
            Val::Int(v) => Some(J::Int(*v)),
            Val::Float(v) => Some(J::Float(norm_float(*v)?)),
            Val::Str(v) => Some(J::Str(v.clone())),
            Val::Ref(id) => Some(self.reference(*id, owner, attr)?),
            Val::Typed(name, inner) => {
                let inner_tree = self.types.get(name).cloned();
                let encoded = self.value(inner, inner_tree.as_ref(), owner, attr)?;
                let mut map = BTreeMap::new();
                map.insert("@t".to_string(), J::Str(name.clone()));
                map.insert("v".to_string(), encoded.unwrap_or(J::Null));
                Some(J::Obj(map))
            }
            Val::List(items) => {
                let sub = elem_tree(tree);
                let mut encoded = Vec::with_capacity(items.len());
                for item in items {
                    encoded.push(self.value(item, sub, owner, attr)?.unwrap_or(J::Null));
                }
                if agg_kind(tree) == Some(AggKind::Set) {
                    encoded.sort_by(|a, b| canon(a).cmp(&canon(b)));
                }
                Some(J::Arr(encoded))
            }
        })
    }

    fn reference(&mut self, id: u32, owner: Option<u32>, attr: Option<&str>) -> Result<J, String> {
        if let Some(global) = self.gid.get(&id) {
            let mut map = BTreeMap::new();
            map.insert("@o".to_string(), J::Str(global.clone()));
            return Ok(J::Obj(map));
        }
        match self.kind.get(&id) {
            Some(Kind::Inline) => Ok(self.entity_value(id)?),
            Some(Kind::Anchored) => {
                let path = self
                    .anchor_of
                    .get(&id)
                    .cloned()
                    .ok_or_else(|| format!("anchored #{id} has no owner path"))?;
                let here = match (owner, attr) {
                    (Some(owner), Some(attr)) => self
                        .gid
                        .get(&owner)
                        .map(|global| format!("{global}/{attr}")),
                    _ => None,
                };
                if here.as_deref() == Some(path.as_str()) {
                    Ok(self.entity_value(id)?)
                } else {
                    let mut map = BTreeMap::new();
                    map.insert("@a".to_string(), J::Str(path));
                    Ok(J::Obj(map))
                }
            }
            Some(Kind::Node) => {
                let key = self.node(id)?;
                let mut map = BTreeMap::new();
                map.insert("@n".to_string(), J::Str(key));
                Ok(J::Obj(map))
            }
            None => Err(format!("no kind for #{id}")),
        }
    }

    fn entity_value(&mut self, id: u32) -> Result<J, String> {
        if !self.visiting.insert(id) {
            return Err(format!("cycle through #{id}"));
        }
        let position = *self
            .index
            .get(&id)
            .ok_or_else(|| format!("entity #{id} missing from the dump"))?;
        let ty = self.entities[position].ty.clone();
        // Move the attributes out so recursive encoding can borrow the rest of the decomposer.
        // The entity cannot be re-entered: `visiting` rejects a cycle before this runs again.
        let attrs = std::mem::take(&mut self.entities[position].attrs);
        let mut map = BTreeMap::new();
        let mut failure = None;
        for attr in &attrs {
            match self.value(&attr.val, Some(&attr.tree), Some(id), Some(&attr.name)) {
                Ok(Some(encoded)) => {
                    map.insert(attr.name.clone(), encoded);
                }
                Ok(None) => {}
                Err(e) => {
                    failure = Some(e);
                    break;
                }
            }
        }
        self.entities[position].attrs = attrs;
        self.visiting.remove(&id);
        if let Some(e) = failure {
            return Err(e);
        }
        let mut root = BTreeMap::new();
        root.insert("a".to_string(), J::Obj(map));
        root.insert("t".to_string(), J::Str(ty));
        Ok(J::Obj(root))
    }

    fn node(&mut self, id: u32) -> Result<String, String> {
        let class = self
            .ckey
            .get(&id)
            .cloned()
            .ok_or_else(|| format!("no content class for #{id}"))?;
        let key = if let Some(key) = self.node_key.get(&class) {
            key.clone()
        } else {
            let bytes = canon(&self.entity_value(id)?);
            let fresh = hash(&bytes);
            let key = self.resolve_node_id(id, &bytes)?.unwrap_or_else(|| fresh.clone());
            if key == fresh {
                self.fresh_ids.insert(key.clone(), fresh);
            }
            self.node_key.insert(class, key.clone());
            self.records.insert(format!("n/{key}"), bytes);
            key
        };
        self.inst_node_key.insert(id, key.clone());
        Ok(key)
    }

    fn loose_value(&mut self, id: u32) -> Result<J, String> {
        self.entity_value(id)
    }

    pub fn run(&mut self, format_tag: &str) -> Result<(), String> {
        self.classify()?;
        let roots: Vec<u32> = self
            .entities
            .iter()
            .filter(|e| self.gid.contains_key(&e.id))
            .map(|e| e.id)
            .collect();
        for id in roots {
            let bytes = canon(&self.entity_value(id)?);
            let global = self.gid[&id].clone();
            self.records.insert(format!("o/{global}"), bytes);
        }
        let mut loose: BTreeMap<String, (J, usize)> = BTreeMap::new();
        let inverses: HashMap<u32, usize> = {
            let refs = self.build_refs();
            refs.into_iter().map(|(id, list)| (id, list.len())).collect()
        };
        let ids: Vec<u32> = self.entities.iter().map(|e| e.id).collect();
        for id in ids {
            if self.gid.contains_key(&id) {
                continue;
            }
            if inverses.get(&id).copied().unwrap_or(0) == 0 {
                let value = self.loose_value(id)?;
                let hx = hash(&canon(&value));
                loose
                    .entry(hx)
                    .and_modify(|(_, n)| *n += 1)
                    .or_insert((value, 1));
            } else if self.kind.get(&id) == Some(&Kind::Node) {
                self.node(id)?;
            }
        }
        for (hx, (value, n)) in loose {
            let mut map = BTreeMap::new();
            map.insert("e".to_string(), value);
            map.insert("n".to_string(), J::Int(n as i64));
            self.records.insert(format!("l/{hx}"), canon(&J::Obj(map)));
        }
        let mut meta = BTreeMap::new();
        meta.insert("k".to_string(), J::Str(format_tag.to_string()));
        meta.insert("schema".to_string(), J::Str(self.schema.clone()));
        self.records.insert("meta".to_string(), canon(&J::Obj(meta)));
        Ok(())
    }

    /// Stable node ids: the Python layer supplies a callback (content hash -> id), None means keep
    /// the fresh content hash. Python's `decompose_against_head` needs this to preserve ids.
    pub fn set_resolver(&mut self, resolver: Py<PyAny>) {
        self.resolver = Some(resolver);
    }

    fn resolve_node_id(&self, id: u32, bytes: &[u8]) -> Result<Option<String>, String> {
        let Some(resolver) = &self.resolver else {
            return Ok(None);
        };
        let ty = self.entity(id)?.ty.clone();
        Python::attach(|py| {
            let result = resolver
                .call1(py, (ty, PyBytes::new(py, bytes)))
                .map_err(|e| e.to_string())?;
            if result.is_none(py) {
                Ok(None)
            } else {
                result.extract::<String>(py).map(Some).map_err(|e| e.to_string())
            }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn float_repr_matches_python_examples() {
        assert_eq!(python_float_repr(1.0), "1.0");
        assert_eq!(python_float_repr(1e16), "1e+16");
        assert_eq!(python_float_repr(1e-5), "1e-05");
        assert_eq!(python_float_repr(-0.0), "-0.0");
        assert_eq!(python_float_repr(1.234e20), "1.234e+20");
        assert_eq!(python_float_repr(0.0001), "0.0001");
    }

    #[test]
    fn tree_parser_keeps_nesting() {
        assert_eq!(
            parse_tree("LIST<LIST<REAL>>"),
            Tree::Agg(AggKind::List, Box::new(Tree::Agg(AggKind::List, Box::new(Tree::Simple("REAL".into())))))
        );
        assert_eq!(parse_tree("IfcLabel"), Tree::Named("IfcLabel".into()));
    }
}
