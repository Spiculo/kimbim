// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveObject.hxx>
#include <QLineF>
#include <QPoint>
#include <QPointF>
#include <QString>
#include <QVector>

namespace kimcad {

// D89: the temporary guides in a view: a small cross on every acquired point and the dashed guide
// lines the cursor is on (at height z). Topmost layer, display only.
class GuidesOverlay : public AIS_InteractiveObject {
public:
    GuidesOverlay(QVector<QPointF> points, QVector<QLineF> lines, double crossSize, double z);
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override;
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}

private:
    QVector<QPointF> m_points;
    QVector<QLineF> m_lines;
    double m_cross, m_z;
};

// D89: the tracker beside the cursor: one box per field ("L 3.250", "A 30.0°", "x 2.815", "y 1.625");
// the focused field stands out, typed values show with a caret. In window pixels (2D persistence),
// `at` = the boxes' lower left corner from the window's lower left.
class TrackerOverlay : public AIS_InteractiveObject {
public:
    struct Box {
        QString text;
        bool focused = false;
        bool typed = false;
    };
    TrackerOverlay(QVector<Box> boxes, QPoint at, double pixelRatio);
    void Compute(const Handle(PrsMgr_PresentationManager)&, const Handle(Prs3d_Presentation)& prs, const int) override;
    void ComputeSelection(const Handle(SelectMgr_Selection)&, const int) override {}
    const QVector<Box>& boxes() const { return m_boxes; }
    static double boxWidth(const QString& text, double pixelRatio);
    static double width(const QVector<Box>& boxes, double pixelRatio); // all boxes, pixels

private:
    QVector<Box> m_boxes;
    double m_ratio;
};

} // namespace kimcad
