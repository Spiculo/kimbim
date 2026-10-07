// SPDX-License-Identifier: GPL-3.0-or-later
#include "Icons.h"

#include <QHash>

namespace kimcad {

QIcon iconFor(const QString& ifcClass)
{
    static const QHash<QString, QString> kinds{
        {"IfcWall", "wall"}, {"IfcWallStandardCase", "wall"}, {"IfcCurtainWall", "wall"},
        {"IfcSlab", "slab"}, {"IfcRoof", "slab"}, {"IfcCovering", "slab"}, {"IfcPlate", "slab"},
        {"IfcDoor", "door"}, {"IfcWindow", "window"},
        {"IfcColumn", "column"}, {"IfcPile", "column"},
        {"IfcBeam", "beam"}, {"IfcMember", "beam"}, {"IfcFooting", "beam"},
        {"IfcStair", "stair"}, {"IfcStairFlight", "stair"}, {"IfcRamp", "stair"}, {"IfcRampFlight", "stair"},
        {"IfcRailing", "stair"},
        {"IfcBuildingStorey", "storey"}, {"IfcBuilding", "building"}, {"IfcSite", "site"},
        {"IfcProject", "project"}, {"IfcSpace", "space"}, {"IfcGrid", "grid"},
    };
    static QHash<QString, QIcon> cache;
    const QString kind = kinds.value(ifcClass, QStringLiteral("element"));
    auto it = cache.find(kind);
    if (it == cache.end())
        it = cache.insert(kind, QIcon(QStringLiteral(":/icons/%1.svg").arg(kind)));
    return *it;
}

} // namespace kimcad
