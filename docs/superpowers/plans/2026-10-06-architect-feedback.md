# Architect-readiness track (owner feedback 2026-10-06) — Slices 9–13

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal (owner):** "A BIM software I can start iterating with an actual architect." Owner feedback after using the app, each item mapped to a slice below:

| # | Feedback | Slice |
|---|----------|-------|
| 1 | Placing walls or objects is too slow | 9 |
| 2 | The plan cut should be a slider on the right of the screen | 9 |
| 3 | Changing properties (e.g. length) in the right panel does nothing | 10 |
| 4 | Layers as boundaries, views as collections of layers | 11 |
| 5 | "Models": an apartment defined once (e.g. on level −5) and placed on many levels, all pointing to it; a dedicated "model" section next to the levels | 12 |
| 6 | Plan annotations: labels and marks on the plan | 13 |
| 7 | Cut walls show no borders, so the lines-only display is confusing | 9 |
| 8 | A drag-to-move tool | 10 |
| 9 | Selecting makes the background re-render / flash | 9 |
| 10 | Objects should have an icon and a hint on hover | 9 |

M5's remaining slices (milestones, object history, combine options) follow this track. The owner asked for readiness for an architect first.

## Global Constraints

- IFC4 standard concepts first: layers = `IfcPresentationLayerAssignment` (+ `IfcPresentationLayerWithStyle` for on/off/frozen); annotations = `IfcAnnotation`; reused "models" stay standard IFC for other tools (each placed instance is real geometry), with KimBim's link kept in a pset.
- Every edit is one undo step with a geometry delta; GlobalIds are kept by edits.
- EN/ES UI, SPDX, DCO; CI on GitHub (the owner allows pushing branches to run it).

---

## Slice 9 — Responsiveness and plan display
1. **Speed:** a tool benchmark (`--bench-tools`: preview update and wall placement times) plus per-step timings in the window. Finding: every paint swapped buffers twice (a forced immediate redraw), so each frame waited two vsyncs and previews lagged. Previews skip border lines and draw on the top layer.
2. **Plan-cut slider:** a vertical slider on the right edge of the 3D view (height above the active level, 0–level height), synced with the toolbar field.
3. **Cut outlines:** where the plan cut (or section box) cuts an element, its section outline is drawn as bold lines, and the cut faces are capped with a dark fill, as in architectural plans, in both shaded and lines-only display.
4. **Icons and hints:** the model tree shows an icon per kind of element; hovering an element in the 3D view shows a tooltip (name, type, level).
5. **Selection flash:** fixed by (1) if it was the double swap; verified by the owner.

## Slice 10 — Editing from the panel and dragging
- Properties panel "Dimensions" group, computed from the model: wall Length/Height/Thickness, door/window Width/Height/Sill, column Height, slab Thickness; editing them changes the geometry (walls through set_wall_axis/set_wall_height, openings through edit_opening, columns through a new set_column_height). Quantity sets stay read-only and are recomputed (`Qto_*BaseQuantities`) after geometry edits.
- Drag to move: press on a selected element and drag, with a live preview and snapping; release moves it (same command as Move, joined walls follow; Ctrl detaches). A drag that starts on empty space still draws a selection box.

## Slice 11 — Layers and views
- Layers (`IfcPresentationLayerAssignment`): a Layers panel (create, rename, delete, show/hide, lock); the active layer receives new elements; "Move selection to layer"; locked layers can't be selected or edited.
- Views = named collections of visible layers (+ the level, plan/3D and cut height): create from the current state, switch, update, delete. Stored in the project as a KimBim pset on IfcProject (JSON), so they travel with the file and the versions.

## Slice 12 — Models (reused units)
- A "Models" section next to the levels: a model is a storey-like container (an `IfcBuildingStorey` marked as a KimBim model, below the building's levels, e.g. "Apartment A" at −5) where a unit is drawn once.
- "Place model…" on a level at an offset/rotation creates an instance: real elements (other IFC tools see the full building), each with a pset linking it to its model element and instance. "Update instances" re-applies the model's current content to every instance, keeping the instance elements' GlobalIds (identity for versioning). Instances can't be edited directly (edit the model instead); "Explode instance" unlinks.

## Slice 13 — Plan annotations
- Text labels, linear dimensions and marks (a revision cloud or a circle with a tag) placed on the active level's plan as `IfcAnnotation` with 2D representations in a Plan/Annotation context; shown in plan views; selectable, movable, deletable, and part of layers (Slice 11).
