# Track C — 3D cut planes in any direction (2026-10-20)

Design recorded as **D95** in `docs/decisions.md`; this note lists what was built, what was left and
anything a reviewer should know.

## Built

### Model and maths (`app/src/Cuts.*`, `app/src/CutPlanes.*`)
- `CutState` now holds `std::vector<CutPlane>` beside the plan cut and section box. A `CutPlane` has a
  name, on/off, kind (horizontal / vertical / oblique), a point, a unit kept-side normal, a line
  direction and an angle.
- Helpers: flip, translate along the normal, `offset()` / `setOffset()` (the plane equation
  `n·x = offset`), `setAngle()` (tilt about the line for oblique planes), JSON round trip.
- Creation helpers: vertical from two plan points + kept side, horizontal at a height, oblique (the
  vertical line tilted by degrees) and from a face (face plane, kept side away from the camera).
- `makePlanes()` accepts a driver limit and truncates; `planeCount()` and `maxUserPlanes()` expose the
  budget. The plan cut and the six box sides come first, then enabled user planes.
- Cuts remain view state: `MainWindow::CutSettings` holds them per view; the 3D view owns them, plan
  tabs keep none. Saved views store them (`planes` in the view data, Python stores the JSON as-is).

### Poché (`Viewport`)
- The plan-cut section pass is now `setSectionPlanes(keepRegion, sectionPlanes)`: closed loops on any
  plane (`ElementBatch::sectionLoopsPlane`, which already existed for section drawings), clipped against
  every other kept half-space (Sutherland–Hodgman), one styled part per purpose style, drawn a hair
  inside the kept side. `setSectionHeight(z)` is kept as the horizontal-plan-cut wrapper, so existing
  callers/tests are unchanged and the plan cut's output is the same.
- `sectionPlaneCount()` was added for tests; `sectionElementCount()` still counts distinct cut elements.

### UI (`MainWindow`, `CutPlanesPanel`, `CutPlaneOverlay`)
- **View › Cut planes**: Vertical cut, Horizontal cut…, Oblique cut…, From a face, and Cut planes panel.
  The Plan cut button in the title bar has the same menu as a flyout (MenuButtonPopup).
- Vertical/oblique: two clicks on the working plane (in 3D or a plan tab) define the line, a third
  click the kept side; the tool stays active for the next cut and Esc/right click leaves it. Oblique
  asks for the tilt (30° default; quiet tests use 30).
- Horizontal asks for the height above project zero, independent of the plan cut.
- From a face: the view picks the front-most element surface and finds the triangle under the cursor;
  the kept side is away from the camera. Esc/right click leaves the mode.
- **Cut planes panel** (a dock tab, also under View › Panels): rows for on/off, name, kind, offset and
  angle, with Vertical/Horizontal…/Oblique…/From a face buttons, Flip side and Delete. Offset and angle
  are typed and applied live. Selecting a row shows the plane.
- The selected plane draws a translucent rectangle centred on the model in that plane, plus a 3D handle
  along its normal. Dragging the handle moves the plane live (the poché and clip plane update on each
  mouse move, like the plan cut slider).
- Plan tabs are unaffected: they show only their own plan cut; user planes are never copied into them.
- All new UI strings are translated to Spanish (`app/translations/kimbim_es.ts`,
  `tools/fill_translations_es.py`); `tools/check_translations.py` passes.

## Clip-plane budget (read this)

The number of clip planes is asked from OCCT (`Viewport::clipPlaneLimit()`,
`Graphic3d_GraphicDriver::InquirePlaneLimit()`). When the driver cannot answer (headless/offscreen) the
code assumes 32, enough for the documented minimum of **4 user planes + plan cut + box = 11**. A real
driver that reports 8 will refuse the plane that does not fit: the status bar says there is no clip
plane left, and the plane is not added (or an existing one cannot be switched back on). On such a
driver the box's six planes inevitably take most of the budget; that is an OCCT/GL limit, not a choice
in this code. `maxUserPlanes()` is the single place to change the policy.

## Left out / approximations

- **Selection and snapping** were not extended. They keep exactly the behaviour they have with the plan
  cut today (selection is OCCT's, snapping comes from the model data); clipped-away geometry is not
  additionally filtered. This matches the task's "as they do for the plan cut today" but is worth
  revisiting if OCCT's selector ignores view clip planes.
- **From a face** uses the triangle nearest the picked point in the front-most picked element rather
  than OCCT's exact face entity. It is exact for flat meshes (the only kind KimBim stores) but a very
  thin/overlapping triangle at the same depth could be chosen.
- **Oblique "typed angle"** is typed in a modal dialog after the third click, not in the options strip;
  the panel's Angle column edits it afterwards. The tool has no live tilted-plane preview while the
  third point is being chosen.
- **Live drag cost**: every mouse move rebuilds the poché pass for every cut plane (one pass over all
  elements per plane). That is fast on small models and the same order as the plan-cut slider, but a
  large model with four planes will feel it. A cached/partial section rebuild is the next optimisation.
- No keyboard shortcuts were assigned to the cut actions; they are under View and the panel.

## Tests

- `app/tests/test_cuts.cpp`: plane construction, normals, flip/offset/angle, face orientation, limit
  helpers, JSON round trip; poché on vertical and oblique planes (cube), clipping between planes, the
  plan-cut wrapper still works.
- `app/tests/test_element_batch.cpp`: `sectionLoopsPlane` on vertical and oblique planes.
- `app/tests/test_cut_planes.cpp` (new): the view menu tools create vertical/oblique/horizontal/face
  planes through the real signals, four user planes fit with the plan cut and box, poché appears on a
  wall, flip/offset/angle/enable/delete, plan tabs keep their own plan cut, saved-view round trip,
  panel rows and the plan-cut button's flyout.
- `tests/python/test_layers.py`: a saved view keeps its cut-plane JSON across save/open.
- Full suites at the end of the track:
  - `pixi run test` — SPDX OK, Rust 10/10, Python **573 passed**, 82 deselected.
  - `pixi run app-test` — **57/57 passed**, including the 19 GUI self-tests.

No failing tests.
