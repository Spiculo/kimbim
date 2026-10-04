"""Spike S4: compare per-file state hashes and export hashes produced on two platforms.

Usage: python compare_manifests.py manifest-windows.json manifest-linux.json
"""
import json
import sys

a = json.load(open(sys.argv[1]))
b = json.load(open(sys.argv[2]))
common = sorted(set(a) & set(b))
state_eq = export_eq = 0
for k in common:
    sa, ea = a[k]
    sb, eb = b[k]
    if sa is None or sb is None:
        print(f"skip (no result)  {k}")
        continue
    state_eq += sa == sb
    export_eq += ea == eb
    if sa != sb or ea != eb:
        print(f"DIFF state={'=' if sa == sb else 'X'} export={'=' if ea == eb else 'X'}  {k}")
n = sum(1 for k in common if a[k][0] and b[k][0])
print(f"\n{n} files compared: state hash equal {state_eq}/{n}, IFC export equal {export_eq}/{n}")
print(f"only in {sys.argv[1]}: {len(set(a) - set(b))}, only in {sys.argv[2]}: {len(set(b) - set(a))}")
