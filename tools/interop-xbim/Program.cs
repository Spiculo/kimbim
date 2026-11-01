// SPDX-License-Identifier: GPL-3.0-or-later
// Independent IFC interop check: xBIM (the .NET engine behind Xplorer) opens the model with its own
// parser and counts the products the M3 house must have. It shares no code with IfcOpenShell.
using System.Text.Json;
using Xbim.Ifc;
using Xbim.Ifc4.Interfaces;

if (args.Length != 1)
{
    Console.Error.WriteLine("usage: interop-xbim <model.ifc>");
    return 2;
}

try
{
    using var model = IfcStore.Open(args[0]);
    var products = model.Instances.OfType<IIfcProduct>().Count();
    var walls = model.Instances.OfType<IIfcWall>().Count();
    var storeys = model.Instances.OfType<IIfcBuildingStorey>().Count();
    var doors = model.Instances.OfType<IIfcDoor>().Count();
    var windows = model.Instances.OfType<IIfcWindow>().Count();
    var report = new
    {
        ok = products > 0 && walls > 0 && storeys > 0,
        products,
        walls,
        storeys,
        doors,
        windows,
        schema = model.SchemaVersion.ToString(),
    };
    Console.WriteLine(JsonSerializer.Serialize(report));
    return report.ok ? 0 : 1;
}
catch (Exception ex)
{
    Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = ex.Message }));
    return 1;
}
