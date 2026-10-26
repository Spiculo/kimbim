// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

namespace kimbim {

// D102: `kimbim-app --snapshot-server`, the agent worker's windowless render helper (spec §6). Reads
// one JSON request per stdin line and writes one JSON line per request to stdout; exits on EOF.
//   {"op":"load","model":ifc,"settings":settings.json|null}       -> {"ok":true,"elements":n}
//   {"op":"render3d","out":png,"size":[w,h],"camera":preset|{eye,target,up,fov},
//    "style":"shaded|white|lines|textured","purpose":name,"frame":[guids],"isolate":bool,
//    "highlight":[guids],"colours":{guid:"#rrggbb"},"cut":metres|null}
//        -> {"ok":true,"out","camera":{eye,target,up,fov},"framed":n,"highlight_colour"}
//   {"op":"svg2png","svg":path,"out":png,"size":[w,h]}             -> {"ok":true,"out","size"}
// Errors: {"ok":false,"error":{"code","message"}}. The model is shown by the app's own MainWindow and
// renderer, in a window that is never put on screen.
int snapshotServerCommand();

} // namespace kimbim
