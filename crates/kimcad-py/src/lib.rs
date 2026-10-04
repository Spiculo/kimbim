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
