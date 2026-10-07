# Slice 17 (M4, "cloning") — Everyday editing

**Goal:** model a repeated façade bay or mirror a whole apartment without redrawing it (Archicad's Edit menu).

## Decisions (D64)

| Command | Archicad behaviour followed | KIMCAD |
|---|---|---|
| Copy / Paste | Ctrl+C, Ctrl+V; paste keeps the original position | Pastes onto the **active level** at the same plan position (copy to another level when another level is active); the copies are selected so you drag them into place |
| Duplicate | Ctrl+D, an offset copy | Copy offset (1 m, 1 m) |
| Drag copy | Ctrl while dragging copies | Ctrl+drag copies; Alt+drag detaches joined walls (was Ctrl, D54) |
| Mirror | Ctrl+M, mirror line by two clicks; Ctrl mirrors a copy | Same. Walls are reversed so their layers land on the mirrored side; doors/windows move to the mirrored spot and swing the other way (LEFT ↔ RIGHT); slab outlines are reflected; other elements get a reflected position and heading. Joins to walls that were not mirrored are dropped |
| Multiply | Ctrl+U: Matrix / Rotate | Linear (dx, dy, count) and polar (centre, angle per copy, count) |
| Offset | Offset edges / parallel copies | Walls: a parallel copy at a distance (left of the axis, negative right); slabs: outline grown or shrunk in place (mitred corners) |

Copies get **new GlobalIds**, keep their **layers**, walls bring their **doors/windows**, and **joins between copied walls are copied** (the existing `_copy_elements`, also used by *Copy to level* and models). Every command is one undo step.

## Done

- [x] `kimcad/editing.py`: `copy_elements`, `duplicate_elements`, `array_elements`, `mirror_elements`, `offset_elements`, `slab_outline`.
- [x] App: Edit › Copy, Paste, Duplicate, Mirror (tool), Multiply… (dialog), Offset… (dialog); Ctrl+drag copies.
- [x] Tests: Python `test_editing.py` (6: copy keeps layers and joins and undoes; paste onto another level; duplicate; mirror in place keeps GlobalIds, reverses the wall, mirrors the door's position and hand; mirror a copy reflects a slab outline; linear and polar arrays; offset of walls and slabs; IFC validation), app `everydayEditing` and shortcuts.

## Not done (later)

- Reflecting asymmetric shapes themselves (an L-shaped column profile, a stair's direction); trim/extend; Offset of polylines and fills (no 2D drafting yet).
