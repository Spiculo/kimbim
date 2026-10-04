# Spikes

Throwaway experiments that answer the open technical questions in [docs/07-roadmap.md](../docs/07-roadmap.md#spikes-do-first-each-is-small-throwaway-and-documented).
**Results and decisions:** [docs/11-spike-results.md](../docs/11-spike-results.md).

This code is not production code. It exists to measure and to fail fast.

| Spike | Folder | Question |
|-------|--------|----------|
| S1 | `s1_shared_model/` | Can a C++ host and embedded `ifcopenshell` Python share one in-memory model? |
| S2 | `s2_geometry/`, `s2_viewer/` | How fast can IfcOpenShell tessellate large models, and can the OCCT viewer render and pick them? |
| S3 | `s3_records/` | Does IFC → canonical records → IFC round-trip losslessly and deterministically? Do edits stay local? |
| S4 | `s3_records/` (run on 2 OSs) | Do Windows and Linux produce identical record hashes? |
| S5 | `s5_git_store/` | Can a Git object database (gitoxide) hold a 1M-record model? |

## Setup

```bash
python -m venv spikes/.venv
spikes/.venv/Scripts/python -m pip install ifcopenshell==0.9.0 blake3 psutil   # Windows
python spikes/corpus/fetch.py        # downloads ~95 MB of buildingSMART sample files (not committed)
```

## Running

```bash
# S3 + S4 manifest (writes s3_records/out/results-<os>.json and manifest-<os>.json)
cd spikes/s3_records && ../.venv/Scripts/python run.py [filter]
../.venv/Scripts/python edits.py <file.ifc>          # edit locality

# S4 on Linux (WSL), isolated packages, separate output dir
python3 -m pip install --target ~/kimcad-spike-pkgs ifcopenshell==0.9.0 blake3
KIMCAD_SPIKE_OUT=out-linux PYTHONPATH=~/kimcad-spike-pkgs python3 run.py
python compare_manifests.py out/manifest-windows.json out-linux/manifest-linux.json

# S2
cd spikes/s2_geometry && ../.venv/Scripts/python geom_bench.py synth 100000
KIMCAD_KERNEL=opencascade ../.venv/Scripts/python geom_bench.py <file.ifc>

# S5 (put the repo outside OneDrive / synced folders)
cd spikes/s5_git_store && cargo build --release
target/release/s5_git_store <repo-dir> 1000000            # import via git fast-import
git -C <repo-dir> repack -adf --window=0                   # no-delta pack for fast reads
target/release/s5_git_store <repo-dir> 0 0 read            # read-back benchmark

# S2 viewer (pixi environment "s2" adds pythonocc-core + PySide6 on the same OCCT)
pixi run python spikes/s2_viewer/prepare_meshes.py <model.ifc> spikes/s2_viewer/out/model.npz
pixi run -e s2 python spikes/s2_viewer/view_bench.py spikes/s2_viewer/out/model.npz batched 1000000000 1000 offscreen

# S1 (Linux/WSL; needs conda-forge ifcopenshell, NOT the pip wheel)
micromamba create -p ~/kimcad-s1/env -c conda-forge python=3.12 ifcopenshell=0.9.0 cxx-compiler cmake make
bash spikes/s1_shared_model/build_and_run.sh
```
