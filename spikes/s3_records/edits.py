"""Spike S3 (edit locality): how many records change for typical authoring edits?

Edits go through ifcopenshell.api like a real authoring tool. A good record design changes only
a handful of records per edit (structural sharing), regardless of model size.
Usage: python edits.py <file.ifc>
"""
import sys

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.pset
import ifcopenshell.util.element
import ifcopenshell.util.placement
import numpy as np

from records import decompose


def changed(before, after):
    keys = set(before) | set(after)
    diff = sorted(k for k in keys if before.get(k) != after.get(k))
    kinds = {}
    for k in diff:
        kinds[k[0]] = kinds.get(k[0], 0) + 1
    return len(diff), kinds


def main(path):
    f = ifcopenshell.open(path)
    base, d = decompose(f)
    print(f"{path.split('/')[-1]}: {len(base)} records")

    walls = f.by_type("IfcWall")
    wall = walls[len(walls) // 2]

    # 1. change one property value
    pset = ifcopenshell.util.element.get_pset(wall, "Pset_WallCommon")
    if pset:
        ifcopenshell.api.pset.edit_pset(f, pset=f.by_id(pset["id"]), properties={"FireRating": "EI60-KIMCAD"})
    else:
        p = ifcopenshell.api.pset.add_pset(f, product=wall, name="Pset_WallCommon")
        ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"FireRating": "EI60-KIMCAD"})
    r1, d = decompose(f, d)
    print("  set one property on one wall      ->", *changed(base, r1))

    # 2. move one wall 300 mm in X (children placements kept relative)
    m = ifcopenshell.util.placement.get_local_placement(wall.ObjectPlacement)
    m = np.array(m)
    m[0][3] += 0.3 / ifcopenshell.util.unit.calculate_unit_scale(f)
    ifcopenshell.api.geometry.edit_object_placement(f, product=wall, matrix=m)
    r2, d = decompose(f, d)
    print("  move one wall                     ->", *changed(r1, r2))

    # 3. raise one storey 100 mm (everything on it moves with it, via relative placement)
    storey = f.by_type("IfcBuildingStorey")[0]
    m = np.array(ifcopenshell.util.placement.get_local_placement(storey.ObjectPlacement))
    m[2][3] += 0.1 / ifcopenshell.util.unit.calculate_unit_scale(f)
    ifcopenshell.api.geometry.edit_object_placement(f, product=storey, matrix=m, should_transform_children=True)
    r3, d = decompose(f, d)
    contained = len(ifcopenshell.util.element.get_decomposition(storey))
    print(f"  raise one storey ({contained} elements on it) ->", *changed(r2, r3))


if __name__ == "__main__":
    import ifcopenshell.util.unit  # noqa: F401  (used above)

    main(sys.argv[1])
