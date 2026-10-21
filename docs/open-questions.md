# Open Questions

Resolve these, then record the answer in [decisions.md](decisions.md).

## Resolved (2026-10-03)

| Question | Answer | Decision |
|----------|--------|----------|
| License | GPL-3.0-or-later (AGPL for future server parts) | D08 |
| Git as storage layer | Yes | D18 |
| Canonical JSON instead of XML | Yes | D11 |
| Embedded Python runtime | Yes | D22 |
| UI vocabulary | Yes; may change from user feedback. UI in English + Spanish | D28, D29 |
| IFC schema | Compatible with IFC4 and IFC4X3; MVP ships IFC4 | D30 |
| Model resolution | 0.01 mm | D31 |

## Resolved (2026-10-20)

The owner answered the plan tab, renovation and view cube lists (D91) and set the rule for the rest: **make most
behaviour configurable, the agent decides what** (D92). Below, "setting" means the current behaviour stays the
default and becomes a setting at the scope in brackets. Built 2026-10-20 except the items marked backlog; what was left narrow is listed in the track notes ([plans and renovation](superpowers/notes/2026-10-20-plans-renovation.md), [settings sweep](superpowers/notes/2026-10-20-settings-sweep.md)).

**Plan tabs** (D91, owner): slice at 1.20 m [project, per level, per view] · which levels an element shows on:
ranges, rules, expressions [object, view] · view depth below [view, per object] · ceilings follow the same settings,
usually drawn transparent · plan symbols tracked; plan symbol vs 3D top view [object, project].

**Renovation** (D91, owner): add Temporary and Auxiliary · unmarked IFC elements default to Existing [setting] · filter
looks [setting per filter] · a door or window takes its host wall's status · legend lists every rule of the purpose when
it fits, else only the rules used [setting].

**View cube** (D91 owner, then D92): preset views always zoom to fit · shortcuts rebindable · home view: user can set
the current view as home (default SE iso) · north arrow on plans [view; on by default once true north is set] ·
field of view [preferences, 45°].

**Window chrome**: which controls the title bar holds [preferences] · Save version in Versions **and** File.

**Schedules**: inside and outside face lengths added as columns · minimum opening area to deduct [schedule, 0] ·
group-by fields [schedule, type and size] · units [schedule, m / m² / m³] · imported spaces listed (yes).

**Selection**: Select similar scope [preferences, same class and predefined type] · Ctrl+A with a tool active selects
that tool's elements (Archicad), with no tool everything · box mode: by direction (default) or Archicad's
partial/entire [preferences] · Find & Select "include hidden" [option, off].

**Measure and levels**: area unit [project, m²] · mesh vertex snaps [preferences, off] · elevation change moves
levels above [option, off] · insert level: push above (Archicad, default) or fit between (Revit) [option] · delete
level keeps both choices.

**Split, trim, join**: split pieces joined [preferences, joined; Ctrl inverts] · trim that drops an opening: refuse
(default), delete or keep inside [option] · merge: keep the first's properties (default) or refuse when they differ
[option] · imported walls: rebuild (default) or keep shape and cut [option] · shortcuts rebindable, Revit two-letter
codes available as a keymap preset.

**Checks**: building-material priorities decide wall/slab overlaps (Archicad); by default the slab cuts the walls
under it · tolerance and clearance [check settings, 2 / 50 mm] · ignore joined walls [option, on] · partial-overlap
duplicates [option, off] · warning exemptions [check rules] · IDS embedded (default) or linked from a shared folder.

**DXF export and underlays**: DXF now; DWG through a user-installed ODA File Converter [preferences, path] · layer
scheme: US NCS (default), ISO 13567, per pen [export setting] · poché on -PATT [option, on] · sheets as blocks
(default) or viewports, later [option] · colour mode: exact / ACI / lineweight [export setting] · DXF text in
underlays [option, on when built] · placement: centred (default) or survey coordinates [option] · opacity, grey,
tint defaults [preferences] · layer per underlay [option] · underlay edits become undo steps · explode and clip:
backlog.

**2D drafting**: keep rectangles rectangular [option, off] · fill outline pen, including none [fill] · pattern
scale: paper (default) or model [fill] · user-defined patterns; insulation zigzag (default) or loops · placeable
area label: backlog · shortcuts rebindable.

**Tags and annotation**: marker, tag and room stamp contents are templates (presets: "D1 / 0.90×2.10", "90/210",
ID in hexagon, sill height; wall tag by type or by a property; stamp fields incl. perimeter, height, finishes) ·
Tag all asks for categories · orphan tags: delete (default) or keep with "?" [option] · level dimension reference:
project zero (default), level, sea level · north arrow and scale bar symbols selectable · revision schedule: backlog ·
angle and radius decimals [project].

**Object library**: edit selection (default) or ask about the type [preferences] · origin per object (library keeps
left front) · plan symbols overridable per object · Shift+O and Tab rebindable · first-release objects to add:
lighting, office desks, parking spaces, potted plants.

**Stairs and railings**: stair rules [project: riser target, tread fixed or from 2R+G] · code presets (rule sets),
see below · flight split and well width editable · floor opening: whole outline (default) or headroom only [stair] ·
railing presets; wall handrail: backlog · plan arrow position and riser numbers [drawing setting] · winders and
spiral stairs: backlog.

**Tracker, guides, touchpad**: tracker always / when typing / off [preferences] · relative x/y default; user origin:
backlog · angle input: absolute (default), relative to previous segment, bearing [preferences] · typed length unit:
metres (default) or project unit [preferences] · dragged and permanent guides: backlog · Tab cycling reaches
annotations [option, on] · navigation presets (precision touchpad, Mac trackpad, mouse) [preferences].

**Tool palette (owner)**: look already a setting (keep icons and labels) · add Split / Trim / Join and Slab / Slab
opening flyouts; users can pin any panel as a permanent tab · panels shrink first on small screens [option, off] ·
vertical icon strip with titles [option, off].

**Python console (owner)**: every run is one undo step, dropped when it changed nothing (no empty steps) · Scripting
menu with pinned scripts: with P2 plugins · `kimbim run script.py model.ifc` for batch jobs: yes.

## Presets (resolved 2026-10-20, D93)

Permit looks, stair code values, layer naming, marker styles, patterns and scales ship as editable presets (default
region Uruguay); the agent picks the defaults. Nothing here is waiting on anyone.

## Needs a spike

These are listed in [07-roadmap.md](07-roadmap.md#spikes-do-first-each-is-small-throwaway-and-documented).

- S1: shared in-memory IFC between C++ and Python.
- S2: OCCT viewer performance at 100k objects.
- S3: lossless record decomposition on the corpus.
- S4: cross-platform hash equality.
- S5: gitoxide performance at 1M blobs.

## Design details to settle during implementation

- The exact canonical JSON schema: attribute naming, how SELECT types and typed values (`IfcLabel("x")`) are encoded, aggregates of aggregates.
- The size threshold that moves geometry into separate records.
- Ownership rules for non-rooted entities that are referenced by several roots without a clear owner.
- Representing IFC2X3 files: convert to IFC4 on import, or store natively by schema?
- Where saved views, drawing definitions and library references live (in-model IFC entities vs `kimbim.toml`).
- Undo across "Save version": can you undo past a commit, or does a commit reset the undo stack?
- Spanish terminology for UI and IFC display labels: pick one regional variant (neutral Latin American vs. Spain) or ship both?
- Community: where the project lives (Codeberg/GitHub), communication channel, and its relationship with the OSArch / IfcOpenShell communities. Upstreaming fixes to IfcOpenShell is strongly encouraged.
