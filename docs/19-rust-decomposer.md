# 19 — Rust decomposer (route 1): C++ IfcOpenShell bridge

Status: **stages 1–4 implemented**. `Project._decompose_file` uses the Rust decomposer when the C++
bridge is available and falls back to the Python reference (`kimbim.records`) otherwise.
`pixi run bench-100k` gates cold decomposition at **< 150 s** (measured 107.9 s on the 100k model,
down from 230.3 s with Python only).

- **Stage 1** is the C++ `tools/ifcdump` bridge: schema, entity ids, types, explicit attribute counts
  and argument types. `pixi run ifcdump-check` compares it with IfcOpenShell on the sample house
  (4,220 entities, IFC4, 0 differences).
- **Stage 2** now includes the C++ **value** dump: entity type, schema attribute name, aggregate
  kind, parameter type tree and JSON value for all 11,856 explicit attributes of the house. The dump
  also carries the schema's defined types and entity supertypes. The checker compares every value
  (including typed values, SET/LIST kinds, references and aggregates) with IfcOpenShell.
  `kimbim._core.canon` is the Rust canonical JSON encoder and matches `records.canon` byte-for-byte
  on values and on every record produced by `records.decompose` for a test model
  (`tests/python/test_rust_canon.py`, 2 passed).
- **Stage 3** is the Rust decomposer in `crates/kimbim-py/src/decompose.rs`. It consumes the dump,
  reproduces hash-consing, content classes, INLINE/ANCHORED/NODE, anchor paths, loose records,
  duplicate GlobalIds, typed values, SET ordering and stable node-id resolution, and writes
  canonical JSON with Python's float text. `tests/python/test_rust_decompose.py` compares the
  complete record dict and `state_hash` with Python on generated models (typed values, duplicate
  GlobalIds, loose duplicates, unchanged/edited shared nodes). It is also byte-identical on the
  4,220-entity house and the 188,018-entity `synth-10000` model.
- **Stage 4** switches `Project._decompose_file` to `kimbim.ifcdump` + the Rust decomposer. The
  Python reference remains the fallback when the bridge is missing or rejects the input (for
  example a malformed GlobalId), and is still what the schema/GlobalId diagnostic path uses.
- The C++ destructor still crashes after value access on Windows, so `ifcdump` flushes and calls
  `_Exit(0)` after the one-shot dump. That is acceptable for a dump subprocess, not for a library.

## Why this is not a small change

Profiling the 10k synthetic model (`cProfile`, 13.6 s) shows the cost is not JSON:

| Hot path | Time |
|---|---:|
| `ifcopenshell/file.py __getitem__` (564k calls) | 4.05 s |
| `builtins.isinstance` (3.7M) | 2.46 s |
| `builtins.len` (1.3M) | 1.99 s |
| `entity_instance.__setattr__` (1.45M) | 1.13 s |
| `canon` + `blake3` + `json` | ~1.0 s |

The first four are the Python/SWIG boundary of IfcOpenShell. Replacing `canon` alone would save only a
few percent and would still have to reproduce Python's exact JSON bytes for the golden hashes.

## Route 1: C++ attribute bridge, Rust decomposition

```text
IFC file
  │
  ▼
C++ bridge (IfcParse):  entities, explicit attributes (name + aggregate kind),
  │                     typed values, references, inverse edges
  ▼
compact binary/JSON dump
  │
  ▼
Rust decomposer (PyO3 in kimbim._core):
  hash-cons, content classes, INLINE/ANCHORED/NODE, anchors,
  canonical JSON (Python-compatible float text), BLAKE3 ids, records dict
  │
  ▼
Python kimbim.records.decompose() → C++/Rust path when the bridge is available
```

The C++ bridge is the **only** IfcOpenShell C++ dependency; Rust never links IfcOpenShell. The bridge
and the Rust crate are built by CMake/maturin respectively, and the bridge is invoked as a subprocess or
a C ABI shared library. A subprocess keeps the build boundary simple and can be tested independently.

## Stages and acceptance

1. **Bridge dump** — `tools/ifcdump` reads an IFC with `IfcParse`, writes every entity's type, attribute
   names/types, parameter type trees, typed values and references; a Python test checks the dump against
   `ifcopenshell` for the house and the corpus. **Done** (`pixi run ifcdump-check`: 4,220 entities,
   11,856 attributes, 0 problems).
2. **Rust canonical encoder** — encode the dump into canonical record bytes; compare byte-for-byte with
   `kimbim.records.canon` on the golden corpus, including `-0.0`, SET ordering, typed values and
   non-ASCII strings. **Done** (`tests/python/test_rust_canon.py`).
3. **Rust decomposer** — hash-consing, content classes, edges, anchors, loose entities and records.
   Compare the complete record dict and state hash with Python on every generated golden file; run
   the versioning, merge, reconciliation and cache tests. **Done** for the checked corpus
   (`tests/python/test_rust_decompose.py`; house and `synth-10000` byte-identical, same state hash).
   The Python implementation stays as the reference and as the fallback.
4. **Switch and gate** — `Project._decompose_file` uses Rust; `bench-100k` gates cold decomposition
   below 150 s. **Done**: cold 107.9 s, warm 3.33 s on the 100k model (previous Python-only cold
   230.3 s). The portable package ships `ifcdump/ifcdump.exe`; without it the Python path is used.

## Remaining risks

- Canonical JSON floats: Python's `repr` and exponent formatting must match exactly (`1e-05`, `-0.0`).
  Rust uses shortest round-trip text and normalises the exponent sign/width; the dump enables
  serde_json's `float_roundtrip` feature so 17-digit C++ doubles parse exactly.
- Hash-consing and anchor ownership depend on content classes, not instances. The Rust key encoding is
  intentionally not byte-identical to `records._kv`; it only has to be injective and sort SET members
  the same way, which the record/state-hash comparison verifies.
- IfcOpenShell's C++ plugin/schema DLLs must be shipped next to the bridge and the app; the package
  launcher puts `runtime/Library/bin` on `PATH` and the bridge in `ifcdump/`.
- The bridge dump doubles I/O for a large model (about 300 MB of text for 100k objects). Streaming or a
  memory-mapped dump is the next speed step if cold decomposition must go below ~100 s.
- The Rust crate must be built on Windows and Linux with the same schema/plugin versions as the app.

The Python decomposer remains the release fallback; both paths are byte-identical on the tests above.
