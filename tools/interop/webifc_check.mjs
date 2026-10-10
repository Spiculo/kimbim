// SPDX-License-Identifier: GPL-3.0-or-later
// Opens an IFC file with web-ifc (the That Open / IFC.js engine: an IFC reader and geometry kernel
// independent of IfcOpenShell) and checks that every building element produces geometry.
// Usage: node webifc_check.mjs FILE.ifc  -> prints a JSON report; exit code 1 on failure.
import fs from "node:fs";
import * as WebIFC from "web-ifc";

const path = process.argv[2];
if (!path) {
  console.error("usage: node webifc_check.mjs FILE.ifc");
  process.exit(2);
}

const CLASSES = ["IFCWALL", "IFCSLAB", "IFCDOOR", "IFCWINDOW", "IFCSTAIR", "IFCCOLUMN", "IFCBEAM", "IFCFURNITURE",
  "IFCSANITARYTERMINAL", "IFCELECTRICAPPLIANCE", "IFCGEOGRAPHICELEMENT", "IFCBUILDINGELEMENTPROXY", "IFCBUILDINGSTOREY"];
const api = new WebIFC.IfcAPI();
await api.Init();
const model = api.OpenModel(new Uint8Array(fs.readFileSync(path)));

const report = { file: path, schema: api.GetModelSchema(model), counts: {}, elements: 0, meshed: 0, missing: [] };
const elements = new Map(); // expressID -> class
for (const name of CLASSES) {
  const ids = api.GetLineIDsWithType(model, WebIFC[name]);
  report.counts[name] = ids.size();
  if (name === "IFCBUILDINGSTOREY") continue;
  for (let i = 0; i < ids.size(); i++) elements.set(ids.get(i), name);
}
report.elements = elements.size;

const meshed = new Set();
api.StreamAllMeshes(model, (mesh) => {
  let triangles = 0;
  for (let i = 0; i < mesh.geometries.size(); i++) {
    const placed = mesh.geometries.get(i);
    const geometry = api.GetGeometry(model, placed.geometryExpressID);
    triangles += geometry.GetIndexDataSize() / 3;
    geometry.delete();
  }
  if (triangles > 0) meshed.add(mesh.expressID);
});
for (const [id, name] of elements) if (!meshed.has(id)) report.missing.push({ id, class: name });
report.meshed = elements.size - report.missing.length;
api.CloseModel(model);

report.ok = report.elements > 0 && report.missing.length === 0;
console.log(JSON.stringify(report));
process.exit(report.ok ? 0 : 1);
