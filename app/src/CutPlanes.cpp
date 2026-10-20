// SPDX-License-Identifier: GPL-3.0-or-later
#include "CutPlanes.h"

#include <gp.hxx>
#include <gp_Vec.hxx>

#include <QJsonArray>

#include <algorithm>
#include <cmath>

namespace kimbim {

namespace {

gp_Dir perpendicular(const QPointF& a, const QPointF& b, const QPointF& keep)
{
    gp_Dir n(b.y() - a.y(), -(b.x() - a.x()), 0);
    if (n.XYZ().Dot(gp_XYZ(keep.x() - a.x(), keep.y() - a.y(), 0)) < 0)
        n.Reverse();
    return n;
}

} // namespace

CutPlane verticalCutPlane(const QString& name, const QPointF& a, const QPointF& b, const QPointF& keep,
    double baseZ)
{
    CutPlane p;
    p.name = name.toStdString();
    p.kind = CutPlane::Kind::Vertical;
    p.point = gp_Pnt(a.x(), a.y(), baseZ);
    p.direction = gp_Dir(b.x() - a.x(), b.y() - a.y(), 0);
    p.normal = perpendicular(a, b, keep);
    p.angle = 0;
    return p;
}

CutPlane horizontalCutPlane(const QString& name, double z)
{
    CutPlane p;
    p.name = name.toStdString();
    p.kind = CutPlane::Kind::Horizontal;
    p.point = gp_Pnt(0, 0, z);
    p.normal = gp_Dir(0, 0, -1); // keep below, like the plan cut
    p.direction = gp_Dir(1, 0, 0);
    p.angle = 0;
    return p;
}

CutPlane obliqueCutPlane(const QString& name, const QPointF& a, const QPointF& b, const QPointF& keep,
    double degrees, double baseZ)
{
    CutPlane p = verticalCutPlane(name, a, b, keep, baseZ);
    p.kind = CutPlane::Kind::Oblique;
    p.setAngle(degrees);
    return p;
}

CutPlane faceCutPlane(const QString& name, const gp_Pnt& point, const gp_Dir& faceNormal, const gp_Pnt& eye)
{
    CutPlane p;
    p.name = name.toStdString();
    p.kind = CutPlane::Kind::Oblique;
    p.point = point;
    p.normal = faceNormal;
    // Kept side away from the camera.
    if (gp_Vec(point, eye).Dot(gp_Vec(p.normal)) > 0)
        p.normal.Reverse();
    // A horizontal line in the face, for the angle control; world X when the face is level.
    p.direction = std::abs(p.normal.Z()) > 0.9999 ? gp_Dir(1, 0, 0) : gp::DZ().Crossed(p.normal);
    if (std::abs(p.normal.Z()) < 1e-9)
        p.kind = CutPlane::Kind::Vertical;
    else if (std::abs(p.normal.Z()) > 1 - 1e-9)
        p.kind = CutPlane::Kind::Horizontal;
    else {
        p.kind = CutPlane::Kind::Oblique;
        p.angle = std::asin(std::clamp(p.normal.Z(), -1.0, 1.0)) * 180.0 / M_PI;
        if (p.angle < 0)
            p.angle += 180.0; // keep the tilt readable, the normal still carries the side
    }
    return p;
}

QJsonObject cutPlaneToJson(const CutPlane& p)
{
    const char* kind = p.kind == CutPlane::Kind::Horizontal ? "horizontal"
        : p.kind == CutPlane::Kind::Vertical                    ? "vertical"
                                                                 : "oblique";
    return QJsonObject{{"name", QString::fromStdString(p.name)}, {"enabled", p.enabled},
        {"kind", QLatin1String(kind)},
        {"point", QJsonArray{p.point.X(), p.point.Y(), p.point.Z()}},
        {"normal", QJsonArray{p.normal.X(), p.normal.Y(), p.normal.Z()}},
        {"direction", QJsonArray{p.direction.X(), p.direction.Y(), p.direction.Z()}},
        {"angle", p.angle}};
}

CutPlane cutPlaneFromJson(const QJsonObject& j, bool* ok)
{
    CutPlane p;
    bool good = true;
    const QJsonArray pt = j.value(QStringLiteral("point")).toArray();
    const QJsonArray n = j.value(QStringLiteral("normal")).toArray();
    const QJsonArray d = j.value(QStringLiteral("direction")).toArray();
    if (pt.size() == 3)
        p.point = gp_Pnt(pt[0].toDouble(), pt[1].toDouble(), pt[2].toDouble());
    else
        good = false;
    if (n.size() == 3)
        p.normal = gp_Dir(n[0].toDouble(), n[1].toDouble(), n[2].toDouble());
    else
        good = false;
    if (d.size() == 3)
        p.direction = gp_Dir(d[0].toDouble(), d[1].toDouble(), d[2].toDouble());
    else
        p.direction = gp_Dir(1, 0, 0);
    p.name = j.value(QStringLiteral("name")).toString().toStdString();
    p.enabled = j.value(QStringLiteral("enabled")).toBool(true);
    const QString kind = j.value(QStringLiteral("kind")).toString();
    p.kind = kind == QLatin1String("horizontal") ? CutPlane::Kind::Horizontal
        : kind == QLatin1String("vertical")      ? CutPlane::Kind::Vertical
                                                 : CutPlane::Kind::Oblique;
    p.angle = j.value(QStringLiteral("angle")).toDouble();
    if (ok)
        *ok = good;
    return p;
}

void planeBasis(const gp_Pln& plane, gp_Pnt* origin, gp_Dir* u, gp_Dir* v)
{
    *origin = plane.Location();
    const gp_Dir n = plane.Axis().Direction();
    if (std::abs(n.Z()) > 0.999) { // horizontal: keep the world X/Y axes
        *u = gp_Dir(1, 0, 0);
        *v = gp_Dir(0, 1, 0);
    } else {
        *u = gp::DZ().Crossed(n);
        *v = n.Crossed(*u);
    }
}

} // namespace kimbim
