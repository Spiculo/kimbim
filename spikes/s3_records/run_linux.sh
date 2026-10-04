#!/usr/bin/env bash
# Spike S4: run S3 on Linux (WSL) from the native filesystem (/mnt/c is too slow),
# then copy the results back next to the Windows ones.
set -euo pipefail
SRC=/mnt/c/Users/lecot/OneDrive/Projects/kimcad/spikes
DST=~/kimcad-spikes
mkdir -p "$DST/s3_records" "$DST/corpus"
cp "$SRC"/s3_records/*.py "$DST/s3_records/"
rsync -a "$SRC/corpus/files" "$DST/corpus/" 2>/dev/null || cp -r "$SRC/corpus/files" "$DST/corpus/"
cd "$DST/s3_records"
KIMCAD_SPIKE_OUT=out-linux PYTHONPATH=~/kimcad-spike-pkgs python3 run.py > full-linux.log 2>&1 || true
mkdir -p "$SRC/s3_records/out-linux"
cp out-linux/results-linux.json out-linux/manifest-linux.json full-linux.log "$SRC/s3_records/out-linux/"
tail -1 full-linux.log
