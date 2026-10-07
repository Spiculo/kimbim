<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 13 — Owner feedback round 1: what changed and how to try it

The owner's ten notes from the first hands-on session, and where each one landed
([plan](superpowers/plans/2026-10-06-architect-feedback.md)).

| # | Note | What KIMCAD does now | Try it |
|---|------|----------------------|--------|
| 1 | Placing walls/objects is slow | The 3D view no longer waits for the display's refresh (vsync) on every redraw; a wall now lands in ~50 ms and the mouse preview in ~2 ms (measured with `--bench-tools`). `KIMCAD_VSYNC=1` brings vsync back | Draw walls (W) quickly |
| 2 | Plan cut as a slider on the right | A vertical slider beside the 3D view sets the cut height for the active level | Drag the slider |
| 3 | Editing length in the panel does nothing | Properties shows a **Dimensions** group (length, height, width, thickness, depth...) that really changes the shape | Select a wall, edit Length |
| 4 | Layers as boundaries, views as collections of layers | **Layers** tab (next to Model): new, rename, delete, shown, locked, active layer, "Move selection here". **Views**: save the layer states + level + plan/3D + cut as a named view and switch between them. Stored in the IFC ([D57](decisions.md)) | Layers tab |
| 5 | "Models" for repeated apartments | **New model...** next to the levels; draw the apartment in it; **Place model (U)** on any level (Shift: turned 90°); a click selects the whole instance; **Model › Update model instances** applies the model's changes everywhere; **Explode** unlinks one ([D58](decisions.md)) | New model... |
| 6 | Labels, dimensions, marks on the plan | **Text label (A)**, **Dimension (Q)**: click two points then where the line goes, measures itself; **Mark (X)**: circle with a tag. They're IFC annotations: select, move (M), delete, undo, layers; edit the text in Properties ([D59](decisions.md)) | Plan view, A / Q / X |
| 7 | Cut walls have no borders | The plan cut draws sections: dark fill and bold outline (poché) where elements are cut | Plan view with the cut on |
| 8 | Drag to move | Press on a selected element and drag; snaps; joined walls follow (Ctrl: detach) | Select, drag |
| 9 | Selection flashes the background | Redraws now repaint the whole view in one pass; please confirm on your screen | Click around |
| 10 | Icons and hints | Element icons in the model tree; hovering an element in the 3D view shows its name, type and level | Hover |

## Shortcuts added

Place model **U** · Text label **A** · Dimension **Q** · Mark **X** (with the earlier W, S, D, N, K, J, G, M, R, E, T, O).

## Still open for the next session

- Confirm 9 (flash) and the feel of 1 and 8 on your screen; tests can't see either.
- Annotations: revision clouds, leaders/arrows, text size in paper units (they're screen-sized now), dimension chains and snapping to wall faces.
- Models: editing an instance in place (today: edit the model, then Update), nested models, a model library across projects.
- Views: per-view graphic overrides (colours/line weights per layer), sheets.
