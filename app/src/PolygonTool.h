// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointF>
#include <QVector>

#include <cstdint>
#include <optional>
#include <vector>

#include "Snapper.h"

namespace kimcad {

// Draws a closed outline (slabs) from plan points: click points (snapped like walls), close by
// clicking the first point again or with finish() (Enter / double click). Pure logic: the viewport
// feeds it work-plane points.
class PolygonTool : public QObject {
    Q_OBJECT
public:
    explicit PolygonTool(QObject* parent = nullptr);

    Snapper& snapper() { return m_snapper; }
    void setTolerance(double metres) { m_tolerance = metres; }
    void setOrtho(bool ortho) { m_ortho = ortho; }
    bool isDrawing() const { return !m_points.isEmpty(); }
    const QVector<QPointF>& points() const { return m_points; }
    std::optional<QPointF> hover() const { return m_hover; }

    Snap move(QPointF p);
    void click(QPointF p);
    void finish();
    void cancel();

    // Simple polygon (no crossing edges, non-zero area), either winding.
    static bool isSimple(const QVector<QPointF>& polygon);
    // Ear clipping: triangle indices into `polygon` (either winding; empty if not simple).
    static std::vector<uint32_t> triangulate(const QVector<QPointF>& polygon);

signals:
    void polygonFinished(const QVector<QPointF>& polygon);
    void rejected(const QString& reason);
    void previewChanged();

private:
    Snap snapAt(QPointF p) const;

    Snapper m_snapper;
    double m_tolerance = 0.1;
    bool m_ortho = false;
    QVector<QPointF> m_points;
    std::optional<QPointF> m_hover;
};

} // namespace kimcad
