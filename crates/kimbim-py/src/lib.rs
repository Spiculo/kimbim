// SPDX-License-Identifier: GPL-3.0-or-later
//! PyO3 bindings: `kimbim._core` (first of the two engine boundaries; the C++ `cxx` bridge comes with the GUI).
use std::collections::BTreeMap;
use std::path::PathBuf;

use pyo3::create_exception;
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBool, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple};

mod decompose;

create_exception!(_core, RepoError, pyo3::exceptions::PyException);

fn err(e: kimbim_repo::Error) -> PyErr {
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

#[pyclass(get_all, frozen)]
struct Tag {
    name: String,
    target: String,
    message: String,
    tagger_name: String,
    time: i64,
}

#[pyclass(frozen)]
struct Repo {
    inner: kimbim_repo::Repo,
}

#[pymethods]
impl Repo {
    #[staticmethod]
    fn init(path: PathBuf) -> PyResult<Self> {
        Ok(Repo { inner: kimbim_repo::Repo::init(&path).map_err(err)? })
    }

    #[staticmethod]
    fn open(path: PathBuf) -> PyResult<Self> {
        Ok(Repo { inner: kimbim_repo::Repo::open(&path).map_err(err)? })
    }

    /// A second working copy (D111): the object store of `project`, its branch in `<worktree>/.kimbim/HEAD`.
    #[staticmethod]
    fn open_worktree(project: PathBuf, worktree: PathBuf) -> PyResult<Self> {
        Ok(Repo { inner: kimbim_repo::Repo::open_worktree(&project, &worktree).map_err(err)? })
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

    fn diff_entries(&self, a_rev: &str, b_rev: &str) -> PyResult<Vec<(String, Option<String>, Option<String>)>> {
        self.inner.diff_entries(a_rev, b_rev).map_err(err)
    }

    fn read_blob_at<'py>(&self, py: Python<'py>, rev: &str, path: &str) -> PyResult<Option<Bound<'py, PyBytes>>> {
        let data = self.inner.read_blob_at(rev, path).map_err(err)?;
        Ok(data.map(|b| PyBytes::new(py, &b)))
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
        let sig = kimbim_repo::Signature { name: author_name, email: author_email, time };
        py.detach(|| self.inner.commit(&changes, message, &sig)).map_err(err)
    }

    #[pyo3(signature = (changes, message, author_name, author_email, time, merged))]
    #[allow(clippy::too_many_arguments)]
    fn commit_merge(
        &self,
        py: Python<'_>,
        changes: BTreeMap<String, Option<Vec<u8>>>,
        message: &str,
        author_name: String,
        author_email: String,
        time: i64,
        merged: Vec<String>,
    ) -> PyResult<String> {
        let sig = kimbim_repo::Signature { name: author_name, email: author_email, time };
        py.detach(|| self.inner.commit_merge(&changes, message, &sig, &merged)).map_err(err)
    }

    fn merge_base(&self, a: &str, b: &str) -> PyResult<Option<String>> {
        self.inner.merge_base(a, b).map_err(err)
    }

    fn fast_forward(&self, rev: &str) -> PyResult<String> {
        self.inner.fast_forward(rev).map_err(err)
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

    fn delete_branch(&self, name: &str) -> PyResult<()> {
        self.inner.delete_branch(name).map_err(err)
    }

    fn create_tag(&self, name: &str, rev: &str, message: &str, tagger_name: String, tagger_email: String, time: i64) -> PyResult<()> {
        let sig = kimbim_repo::Signature { name: tagger_name, email: tagger_email, time };
        self.inner.create_tag(name, rev, message, &sig).map_err(err)
    }

    fn tags(&self) -> PyResult<Vec<Tag>> {
        Ok(self
            .inner
            .tags()
            .map_err(err)?
            .into_iter()
            .map(|t| Tag { name: t.name, target: t.target, message: t.message, tagger_name: t.tagger_name, time: t.time })
            .collect())
    }

    fn delete_tag(&self, name: &str) -> PyResult<()> {
        self.inner.delete_tag(name).map_err(err)
    }

    fn repack_no_delta(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| self.inner.repack_no_delta()).map_err(err)
    }
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Repo>()?;
    m.add_class::<Commit>()?;
    m.add_class::<Tag>()?;
    m.add("RepoError", m.py().get_type::<RepoError>())?;
    m.add_function(wrap_pyfunction!(canon, m)?)?;
    m.add_function(wrap_pyfunction!(decompose_dump, m)?)?;
    Ok(())
}

// ---------------------------------------------------------------- canonical JSON (records.canon)
//
// The cold decomposer will build its record dicts in Rust. This encoder is the exact-byte reference:
// sorted keys, `(",", ":")` separators, UTF-8 (ensure_ascii=False), Python float repr, -0.0 preserved.
// It is already useful for tests and lets the Python records module compare against it.

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
                use std::fmt::Write as _;
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_canonical(value: &Bound<'_, PyAny>, out: &mut String) -> PyResult<()> {
    if value.is_none() {
        out.push_str("null");
        return Ok(());
    }
    if value.cast::<PyBool>().is_ok() {
        out.push_str(if value.extract::<bool>()? { "true" } else { "false" });
        return Ok(());
    }
    if value.cast::<PyInt>().is_ok() {
        out.push_str(&value.extract::<i64>()?.to_string());
        return Ok(());
    }
    if value.cast::<PyFloat>().is_ok() {
        // Python's json module uses float.__repr__; keep the same text (1.0, 1e-05, -0.0...).
        let text = value.repr()?.to_str()?.to_owned();
        if text == "inf" || text == "-inf" || text == "nan" {
            return Err(pyo3::exceptions::PyValueError::new_err("NaN/Inf not allowed in canonical JSON"));
        }
        out.push_str(&text);
        return Ok(());
    }
    if value.cast::<PyString>().is_ok() {
        json_escape(value.extract::<&str>()?, out);
        return Ok(());
    }
    if let Ok(list) = value.cast::<PyList>() {
        out.push('[');
        for (i, item) in list.iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            write_canonical(&item, out)?;
        }
        out.push(']');
        return Ok(());
    }
    if let Ok(tuple) = value.cast::<PyTuple>() {
        out.push('[');
        for (i, item) in tuple.iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            write_canonical(&item, out)?;
        }
        out.push(']');
        return Ok(());
    }
    if let Ok(dict) = value.cast::<PyDict>() {
        let mut entries: Vec<(String, Bound<'_, PyAny>)> = Vec::with_capacity(dict.len());
        for (key, item) in dict.iter() {
            let key = key.extract::<String>().map_err(|_| {
                pyo3::exceptions::PyTypeError::new_err("canonical JSON keys must be strings")
            })?;
            entries.push((key, item));
        }
        entries.sort_by(|a, b| a.0.cmp(&b.0));
        out.push('{');
        for (i, (key, item)) in entries.into_iter().enumerate() {
            if i > 0 {
                out.push(',');
            }
            json_escape(&key, out);
            out.push(':');
            write_canonical(&item, out)?;
        }
        out.push('}');
        return Ok(());
    }
    Err(pyo3::exceptions::PyTypeError::new_err(format!(
        "cannot canonicalise {} in a record",
        value.get_type().name()?
    )))
}

#[pyfunction]
fn canon<'py>(py: Python<'py>, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyBytes>> {
    let mut out = String::new();
    write_canonical(value, &mut out)?;
    Ok(PyBytes::new(py, out.as_bytes()))
}

/// Stage 3 of docs/19: decompose an `ifcdump` payload entirely in Rust. `records.py` remains the
/// reference until the golden/versioning comparisons are byte-identical.
#[pyfunction]
#[pyo3(signature = (dump, format_tag, resolver=None))]
fn decompose_dump<'py>(
    py: Python<'py>,
    dump: &str,
    format_tag: &str,
    resolver: Option<Py<PyAny>>,
) -> PyResult<Bound<'py, PyDict>> {
    let mut decomposer =
        decompose::Decomp::parse(dump).map_err(pyo3::exceptions::PyValueError::new_err)?;
    if let Some(resolver) = resolver {
        decomposer.set_resolver(resolver);
    }
    decomposer
        .run(format_tag)
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
    let out = PyDict::new(py);
    for (key, bytes) in decomposer.records {
        out.set_item(key, PyBytes::new(py, &bytes))?;
    }
    Ok(out)
}
