#!/usr/bin/env bash
# Re-run S3 on Linux for files matching a filter and merge into out-linux/ results.
set -euo pipefail
SRC=/mnt/c/Users/lecot/OneDrive/Projects/kimcad/spikes
DST=~/kimcad-spikes
cp "$SRC"/s3_records/*.py "$DST/s3_records/"
cd "$DST/s3_records"
cp out-linux/results-linux.json out-linux/results-linux.full.json
KIMCAD_SPIKE_OUT=out-linux-one PYTHONPATH=~/kimcad-spike-pkgs python3 run.py "$1" 2>&1 | grep -v "^No stream"
python3 - <<'EOF'
import json
full = json.load(open("out-linux/results-linux.full.json"))
new = {r["file"]: r for r in json.load(open("out-linux-one/results-linux.json"))}
full = [new.get(r["file"], r) for r in full]
json.dump(full, open("out-linux/results-linux.json", "w"), indent=1)
json.dump({r["file"]: [r.get("state_hash"), r.get("export_hash")] for r in full},
          open("out-linux/manifest-linux.json", "w"), indent=1, sort_keys=True)
EOF
cp out-linux/results-linux.json out-linux/manifest-linux.json "$SRC/s3_records/out-linux/"
