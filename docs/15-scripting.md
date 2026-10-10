<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 15 — Scripting: the Python console

KIMCAD embeds CPython (D22) with IfcOpenShell, so the model you are editing is a live `ifcopenshell.file` you can
script. The **Console** panel works like pyRevit's and Bonsai's consoles and Archicad's Python palette, but it runs
in the same interpreter as the app, on the same model, with no JSON command layer in between (decision D82).

## Opening it

- **View › Panels › Python console** (Ctrl+Alt+P). It docks with the other panels and can float.
- **File › Run Python script...**, or **Run script...** in the panel, runs a `.py` file in the console.

Enter runs the input. Shift+Enter adds a line (indented after a `:`). Up and Down on the first or last line bring
back earlier input. When the last line is an expression, its value is printed, like the Python prompt. Output and
`print` appear above the input, and tracebacks appear in red. The names you define stay for the whole session.

## Names in the console

| Name | What it is |
|------|------------|
| `ifc` | The open model, an `ifcopenshell.file`. It is set again before every run, so it always follows the open file |
| `ifcopenshell` | IfcOpenShell (`ifcopenshell.api`, `ifcopenshell.util.element` are already imported) |
| `kimcad`, `bridge` | KIMCAD's modules. `bridge` is `kimcad.app_bridge`, the app's own commands (strings in, JSON out) |
| `selection()` | The selected elements, as entities |
| `select(items)` | Selects elements: GlobalIds, entities, or a list of either. `select([])` clears the selection |
| `edit()` | `with edit(): ...` makes the changes in the block **one undo step** (Ctrl+Z), and the views update |
| `refresh()` | Redraws every element and refreshes the panels when the run ends |
| `help_kimcad()` | Prints this list |

```python
len(ifc.by_type("IfcWall"))                 # 8 in the sample house

with edit():                                # one undo step
    for wall in selection():
        wall.Name = wall.Name.upper()

import json
with edit():                                # KIMCAD's own commands join the same step
    bridge.set_name(json.dumps([w.GlobalId for w in selection()]), "Exterior")

select([w for w in ifc.by_type("IfcWall") if "Exterior" in (w.Name or "")])
```

## How it behaves

- **Undo.** Changes made inside `with edit():` are recorded like the app's own edits: one step in Edit › Undo, and
  the unsaved-changes mark appears. If the block raises an error, its changes are rolled back. KIMCAD commands called
  inside the block (`bridge.create_wall(...)`, `bridge.delete_elements(...)`) join the step instead of making their
  own. **Changes made outside `edit()` cannot be undone**, and they can confuse undo for earlier steps, so always
  use `edit()` to change the model.
- **Views.** After a run, KIMCAD redraws the elements whose shapes the run's edit steps touched: the entities the
  step created, changed or deleted, traced up to their elements. A changed placement also redraws the elements
  placed relative to it, and a changed opening redraws its wall. Call `refresh()` when something else changed.
- **Selection.** `selection()` is the selection when the run started, or the one set by `select()`. `select()`
  takes effect when the run ends. Elements that are hidden or on hidden or locked layers are not selected, as with
  Find & Select.
- **Long scripts.** The script runs on a worker thread. After 0.4 s a window says *Running the script...* with a
  **Stop** button (or Ctrl+C), and the rest of the app waits. Stop raises `KeyboardInterrupt` at the script's next
  line of your code (the console's input or the script file). A long call inside a library, for example a
  `time.sleep` or a geometry operation in C++, finishes first. KIMCAD's own bookkeeping is never interrupted
  part-way, so an undo step is never left half-recorded.
- **Running a file.** The file runs in the console's namespace, so its names stay afterwards. Inside it,
  `__file__` is its path.

## Not yet

Code completion, plugins that add commands and panels (doc 04 §11, P2), and running scripts from the command line
without the window. `kimcad` on the command line covers versioning (`kimcad --help`).
