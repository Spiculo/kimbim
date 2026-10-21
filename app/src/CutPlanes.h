// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QPointF>
#include <QString>

#include "Cuts.h"

namespace kimbim {

// D95: the user cut planes' construction, storage and drawing helpers.
CutPlane verticalCutPlane(const QString& name, const QPointF& a, const QPointF& b, const QPointF& keep,
    double baseZ);
CutPlane horizontalCutPlane(const QString& name, double z);
CutPlane obliqueCutPlane(const QString& name, const QPointF& a, const QPointF& b, const QPointF& keep,
    double degrees, double baseZ);
CutPlane faceCutPlane(const QString& name, const gp_Pnt& point, const gp_Dir& faceNormal, const gp_Pnt& eye);

QJsonObject cutPlaneToJson(const CutPlane& plane);
CutPlane cutPlaneFromJson(const QJsonObject& json, bool* ok = nullptr);

// An orthonormal in-plane basis (origin, u, v) with v = normal x u. Horizontal planes use world
// X/Y, so a plan cut's outlines keep their orientation.
void planeBasis(const gp_Pln& plane, gp_Pnt* origin, gp_Dir* u, gp_Dir* v);

} // namespace kimbim
