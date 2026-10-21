// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointF>
#include <QString>
#include <QVector>

#include <optional>

#include "Snapper.h"

namespace kimbim {

// The 2D drafting tools (D84, doc 14 §12): line, polyline, rectangle, circle (centre and radius),
// arc (three points, or centre, start and end) and fill. Clicks snap like the other tools (Shift:
// right angles); a typed value finishes the next point: a length along the mouse direction, "length<angle"
// (degrees), a radius, or a rectangle's "width;height". Pure logic: the window feeds it plan points.
class DraftTool : public QObject {
    Q_OBJECT
public:
    enum class Mode { Line, Polyline, Rectangle, Circle, Arc3, ArcCentre, Fill };
    explicit DraftTool(QObject* parent = nullptr);

    Snapper& snapper() { return m_snapper; }
    void setMode(Mode mode);
    Mode mode() const { return m_mode; }
    void setTolerance(double metres) { m_tolerance = metres; }
    void setOrtho(bool ortho) { m_ortho = ortho; }
    void setLengthFactor(double f) { m_lengthFactor = f > 0 ? f : 1.0; } // D92: typed lengths' unit
    bool isDrawing() const { return !m_points.isEmpty(); }
    const QVector<QPointF>& points() const { return m_points; }
    std::optional<QPointF> hover() const { return m_hover; }

    Snap move(QPointF p);
    void click(QPointF p);
    bool typeInput(const QString& text); // false if it means nothing at this stage
    // Enter: a polyline ends open, a fill closes. Esc: a polyline of two points or more ends open,
    // anything else is dropped.
    void finish();
    void escape();
    void cancel();

    // What the shape would be with the mouse where it is (plan polylines, metres).
    QVector<QVector<QPointF>> preview() const;
    QString hint() const;

    // The kind add_drafting takes and its points for a finished shape.
    static QVector<QPointF> arcFromCentre(QPointF centre, QPointF start, QPointF end); // start, middle, end (counter-clockwise)
    static QVector<QPointF> circlePoints(QPointF centre, double radius, int segments = 48);
    static std::optional<std::pair<QPointF, double>> circumcircle(QPointF a, QPointF b, QPointF c);
    static QVector<QPointF> arcPoints(QPointF a, QPointF b, QPointF c, int segments = 32);

signals:
    // kind: line, polyline, rectangle, circle, arc, fill (add_drafting's); closed: a polyline closed on its start.
    void shapeFinished(const QString& kind, const QVector<QPointF>& points, bool closed);
    void rejected(const QString& reason);
    void previewChanged();

private:
    Snap snapAt(QPointF p) const;
    void add(QPointF p);
    void emitShape(const QString& kind, const QVector<QPointF>& points, bool closed = false);
    int needed() const; // points that finish the shape (0: open-ended)

    Snapper m_snapper;
    Mode m_mode = Mode::Line;
    double m_tolerance = 0.1;
    double m_lengthFactor = 1.0; // D92: typed lengths in the project unit
    bool m_ortho = false;
    QVector<QPointF> m_points;
    std::optional<QPointF> m_hover;
};

} // namespace kimbim
