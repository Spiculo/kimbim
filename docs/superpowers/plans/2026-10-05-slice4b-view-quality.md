# Slice 4b — View quality: edges, lines-only plans, visible-only box selection, mouse release fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner feedback after trying Slice 4. Pan and orbit stop when the mouse button is released. Elements get edge lines so they can be told apart. Plans can be shown as a pure line drawing. Box selection takes only what you can see, unless you hold a modifier to select through. Missing navigation features are documented for later.

**Architecture:** All in the C++ viewport (`ElementBatch`, `Viewport`, `MainWindow`).
- **Edges:** each batch computes feature edges once from its triangles: boundary edges, plus edges where the adjacent faces bend by more than 30°. Vertices are matched by quantised position because meshes are not welded. The edges are drawn as a segment array over polygon-offset faces.
- **Display modes:** 0 = shaded faces + edges; 1 = element-id colours for visibility queries; 2 = lines only (faces unlit in the background colour + black edges, i.e. hidden-line).
- **Visible-only box selection:**
  1. Render the view once in mode 1 (unlit, an id encoded in the colour, black background, selection highlight off).
  2. Read the pixels of the rubber band (`V3d_View::ToPixMap`) and decode the set of ids seen.
  3. Intersect with OCCT's "fully inside" rectangle candidates, picked without changing the selection.
  4. Apply the click scheme (replace/add/toggle) manually.
  - Alt (or a View-menu toggle, since Linux window managers often take Alt+drag) selects through, as before.

**Tech Stack:** OCCT 8 (Graphic3d arrays, ToPixMap, SelectMgr), Qt 6, Qt Test.

**Spec:** Owner feedback 2026-10-05 (after running Slice 4): "put border lines", "the planar view should have an only lines toggle", "the selection goes through stuff, that should have a control just as the shift or ctrl keys have", "move and rotate do not stop until I let go of the shift instead of the mouse key"; "we need those extra things [view cube, preset views, touchpad], just document them for now".

## Global Constraints

- No regression in the Slice 2 performance target (100k elements interactive): edges are computed once per batch; the id render runs only on box-select release.
- Headless CI: pure functions (edge extraction, id encode/decode) are unit-tested; rendering paths go through the GUI self-tests.
- EN/ES strings, SPDX, DCO.

## Review Focus

1. Unwelded meshes (OCCT output duplicates vertices per face): edges must still pair up, so a box gives 12 edges, not 36.
2. Sub-pixel or float noise in colour readback (sRGB conversion, rounding): decoding must tolerate ±1 per channel.
3. Add/XOR schemes with visible-only selection must keep the previous selection outside the box.
4. Clip planes (plan cut, section box) must still apply in id mode: cut-away parts don't count as visible.
5. Lines-only + selection highlight: selected elements must still show as selected.

---

### Task 1: Mouse release ends pan/orbit (bug)
- Test (`test_navigation`): press and release the middle button with Shift held through `QTest` → the controller reports no pressed buttons; the same for the left button.
- Fix: `PressMouseButton`/`ReleaseMouseButton` get the button that changed (`e->button()`), not the buttons still held.

### Task 2: Edge lines + lines-only mode
- `ElementBatch::featureEdges(const MeshChunk&, int element, double angleDeg = 30) -> std::vector<std::pair<gp_Pnt,gp_Pnt>>` (pure, tested: unwelded cube → 12; flat quad of 2 triangles → 4; two coplanar quads sharing an edge → 6).
- Mode 0 draws faces with polygon offset + dark edges; mode 2 draws unlit background-colour faces + black edges. `Viewport::setLinesOnly(bool)`, `linesOnly()`; View › Lines only (`actionLinesOnly`, key **L**, checkable). Tests: viewport switches every batch's display mode; action exists with shortcut.

### Task 3: Visible-only box selection, Alt to select through
- Pure `idColor(int id) -> Quantity_Color` / `idFromPixel(r, g, b) -> int` (6 bits per channel, channel value = v·4+2, tolerant to ±1; 0 = background). Tests: round trip for 0..262143 samples with ±1 noise.
- `Viewport::visibleIn(rect) -> QSet<QString>` (id render, as in Architecture); `Viewport::selectInRectangle(x0, y0, x1, y1, scheme, bool through = false)` uses it when `!through`; the rubber-band gesture uses it via `handleSelectionPoly` override; Alt binds the through variant. View › "Select hidden elements too" (`actionSelectThrough`) makes through the default.
- GUI self-tests: `_write_occlusion_model` (a long 3 m wall in front of a 1 m wall that is fully hidden in the default view); `--box-select` → 1, `--box-select --select-through` → 2; the existing 2-wall fixture still gives 2.

### Task 4: Docs, verification
- Doc 04 §2: navigation backlog (view cube, front/back/side/top preset views, touchpad navigation: two-finger pan, pinch zoom, a modifier for orbit without a middle button); selection keys incl. Alt; edges and lines only. README keys. Decision D52 (visible-only box selection by id render; lines-only = hidden-line).
- Full suites Windows + WSL; screenshots (edges on the wall loop and Duplex, lines-only plan); self-review; finish the branch.
