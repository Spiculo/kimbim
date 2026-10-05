// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QString>

namespace kimcad {

struct SelfTestOptions {
    QString path;                 // IFC file, or ":fixture:" for the built-in 2-wall test model
    int frames = 60;              // orbit frames to measure
    bool quitDuringLoad = false;  // request quit after the first chunk (shutdown while loading)
    double planCut = -1;          // >= 0: apply a plan cut at this height before measuring
    int chunkSize = 1000;         // elements per mesh chunk / batch
    bool boxSelect = false;       // box-select the whole view and report how many got selected
    QString screenshot;           // non-empty: save a PNG of the whole window at the end
    QString drawWalls;            // "x,y;x,y;...": new project, draw this wall polyline with the wall tool
};

// Opens the model in a real window, loads it, measures, prints one JSON line to stdout.
// Returns the process exit code (0 = ok). Used by CI and by people reporting performance.
int runSelfTest(const SelfTestOptions& options);

} // namespace kimcad
