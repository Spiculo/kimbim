// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveObject.hxx>
#include <QString>
#include <QVector>

#include "MeasureTool.h"

namespace kimcad {

// The measure tool's path in a view (D79): the segments, a dashed closing edge from three points,
// a dot on every point and the readout beside the last one. Drawn over the model (topmost layer),
// display only.
class MeasureOverlay : public AIS_InteractiveObject {
public:
    MeasureOverlay(QVector<MeasurePoint> path, QString label);
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override;
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}

private:
    QVector<MeasurePoint> m_path;
    QString m_label;
};

} // namespace kimcad
