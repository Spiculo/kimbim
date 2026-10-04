#!/usr/bin/env bash
# Spike S1: build host.cpp against conda-forge IfcOpenShell + Python and run it on a sample file.
# Env created with:
#   micromamba create -p ~/kimcad-s1/env -c conda-forge python=3.12 ifcopenshell=0.9.0 cxx-compiler cmake make
set -euo pipefail
ENV=~/kimcad-s1/env
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT=~/kimcad-s1/build && mkdir -p "$OUT"
"$ENV/bin/x86_64-conda-linux-gnu-c++" -std=c++17 -O1 "$HERE/host.cpp" -o "$OUT/host" \
  -I"$ENV/include" -I"$ENV/include/python3.12" \
  -L"$ENV/lib" -Wl,-rpath,"$ENV/lib" -lifcopenshell.parse -lpython3.12
SAMPLE="${1:-$HERE/../corpus/files/bsi/IFC 4.0.2.1 (IFC 4 ADD2 TC1)/Simple-Scene/Building-Architecture.ifc}"
PYTHONHOME="$ENV" "$OUT/host" "$SAMPLE"
