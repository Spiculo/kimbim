// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QSize>
#include <QString>

namespace kimcad {

struct SelfTestOptions {
    QString path;                 // IFC file, or ":fixture:" for the built-in 2-wall test model
    int frames = 60;              // orbit frames to measure
    bool quitDuringLoad = false;  // request quit after the first chunk (shutdown while loading)
    double planCut = -1;          // >= 0: apply a plan cut at this height before measuring
    int chunkSize = 1000;         // elements per mesh chunk / batch
    bool boxSelect = false;       // box-select the whole view and report how many got selected
    bool selectThrough = false;   // box selection includes hidden elements
    QString screenshot;           // non-empty: save a PNG of the whole window at the end
    QSize windowSize;             // valid: the window's size (--window-size 1000x800)
    bool maximized = false;       // show the window maximized
    bool planView = false;        // switch to the plan view of the lowest level before the screenshot
    QString underlay;             // D85: "file[;opacity[;x;y]]" placed on the active level after loading
    bool linesOnly = false;       // lines-only display before measuring/screenshot
    bool benchTools = false;      // time tool previews and wall creation (ms), report them
    bool house = false;           // new project: walls, slab from walls, a door and a window
    QString drawWalls;            // "x,y;x,y;...": new project, draw this wall polyline with the wall tool
    bool createDrawings = false; // View > Create floor plans and elevations after loading (an opened IFC has none)
    QString openDrawing;          // a drawing's name: open it in its tab, wait for it, report its paper size
    bool popOut = false;          // move the 3D view to its own window and back (a tab dragged out, D71)
    bool benchEdit = false;       // time moving a wall back and forth (ms per edit, and per refresh step)
    bool benchModify = false;     // D80: time a split and a trim of a wall, then undo them
    bool planTab = false;        // with benchEdit: a plan tab of the active level open and active
    bool perspective = false;     // D76: View > Perspective before measuring (pick, box select, fps)
    QString view;                 // D76: a preset view (Top, Front, SE, ..., Home) before measuring, animated
    bool cubeClick = false;       // D76: click the view cube's top face and the home button; selection must stay
    QString schedule;             // D77: open this schedule (doors, walls, ...), select its first row; with screenshot, a PNG of it
    QString measure;              // D79: "x,y x,y ...": measure through these work-plane points, report the readout
    bool levelsDialog = false;    // D79: open Model > Levels...; with screenshot, a PNG of it
    QString console;              // D82: run this Python in the console panel, report its output
    QString findSelect;           // D78: an IFC class: Find & Select it from the panel, report how many
    QString library;              // D86: open the Library panel on this object and place it at (1, 1); with screenshot, a PNG of the panel
    bool tracker = false;         // D89: draw a wall in the plan with a temporary guide and the tracker shown; PNGs of the view
    QString checks;               // D81: checks to run from the Checks panel ("schema,model,clash"); clicks the first issue
};

// Opens the model in a real window, loads it, measures, prints one JSON line to stdout.
// Returns the process exit code (0 = ok). Used by CI and by people reporting performance.
int runSelfTest(const SelfTestOptions& options);

} // namespace kimcad
