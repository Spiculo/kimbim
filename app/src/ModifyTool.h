// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QObject>
#include <QPointF>
#include <QString>
#include <QVector>

#include <optional>

#include "Snapper.h"

namespace kimcad {

// Split, trim / extend (to an element or a line, or two to their corner), join and unjoin walls and
// beams by clicking them (D80). Pure logic: the window feeds it the level's walls, beams and grid
// lines and turns its requests into model edits. Ctrl on the click that finishes an edit leaves
// the elements unjoined (D54's opt-out).
class ModifyTool : public QObject {
    Q_OBJECT
public:
    enum class Mode { Split, Trim, Corner, Join, Unjoin };
    struct Target {
        QString guid; // empty for a grid line
        QString kind; // "wall", "beam", "grid"
        QPointF a, b;
        double width = 0.0;
    };

    explicit ModifyTool(QObject* parent = nullptr);

    // snap_data's walls and grid, modify_targets' beams.
    void setTargets(const QJsonObject& snapData, const QJsonObject& beams);
    void setTargets(QVector<Target> targets) { m_targets = std::move(targets); }
    Snapper& snapper() { return m_snapper; }
    void setTolerance(double metres) { m_tolerance = metres; }

    void setMode(Mode mode);
    Mode mode() const { return m_mode; }
    int stage() const { return m_first ? 1 : 0; }
    std::optional<Target> first() const { return m_first; }
    std::optional<Target> hovered() const { return m_hover; }
    std::optional<QPointF> splitPoint() const { return m_splitPoint; }

    // The element (or, picking a boundary, grid line) under p.
    std::optional<Target> pick(QPointF p, bool boundary) const;
    void move(QPointF p);
    void click(QPointF p, Qt::KeyboardModifiers mods = Qt::NoModifier);
    void cancel(); // back to the first pick
    QString hint() const;

signals:
    void splitRequested(const QString& guid, QPointF at, bool join);
    void trimRequested(const QString& guid, QPointF keep, const QString& boundary, QPointF b1, QPointF b2, bool join);
    void cornerRequested(const QString& first, QPointF p1, const QString& second, QPointF p2, bool join);
    void joinRequested(const QString& first, const QString& second);
    void unjoinRequested(const QString& first, const QString& second);
    void previewChanged();

private:
    QPointF onAxis(const Target& t, QPointF p) const;

    Snapper m_snapper;
    QVector<Target> m_targets;
    double m_tolerance = 0.1;
    Mode m_mode = Mode::Split;
    std::optional<Target> m_first;
    QPointF m_firstPoint;
    std::optional<Target> m_hover;
    std::optional<QPointF> m_splitPoint;
};

} // namespace kimcad
