// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QPointF>
#include <QVector>

#include <optional>

namespace kimcad {

// D89: the drawing aids every tool's Snapper shares (pure logic, one per window).
//
// Temporary guides (AutoCAD object tracking, Archicad temporary guides, SketchUp inference): resting
// the cursor on a snap point for half a second acquires it (again: releases it); at most kMaxGuides,
// the oldest goes first. An acquired point casts a horizontal and a vertical guide line, plus the
// extension of the wall or line it belongs to; the cursor snaps to those lines, to where two of them
// cross, and to where they cross the horizontal/vertical through the tool's previous point. Drawing
// from a previous point parallel to an acquired wall snaps too.
//
// Tracker locks: values typed into the tracker hold the cursor (a typed angle fixes the direction
// from the previous point, a typed length the distance, a typed x or y that coordinate) until the
// point is placed or the input is cleared.
//
// Last snap: what the most recent Snapper::snap() call saw, so the tracker can show the live length
// and angle from the tool's previous point without asking each tool.
class InputAids {
public:
    static constexpr int kMaxGuides = 4;
    static constexpr int kAcquireMs = 500;

    struct Guide {
        QPointF at;
        std::optional<QPointF> direction; // unit vector of the wall/line the point belongs to
    };
    struct Locks {
        std::optional<double> angle;  // radians, counter-clockwise from +x, from the previous point
        std::optional<double> length; // metres from the previous point
        std::optional<double> x, y;   // absolute plan coordinates (metres)
        bool any() const { return angle || length || x || y; }
    };

    // Guides
    void setGuidesEnabled(bool on);
    bool guidesEnabled() const { return m_enabled; }
    const QVector<Guide>& guides() const { return m_guides; }
    void clearGuides();
    // The point snap under the cursor (nullopt: none); restarts the rest timer when it changes.
    void hover(const std::optional<Guide>& point);
    std::optional<Guide> hovered() const { return m_hover; }
    // The cursor rested on the hovered point long enough: acquire it (or release it if it was
    // acquired). Once per rest: true if the guides changed.
    bool acquireHovered();
    void acquire(const Guide& g); // directly (tests, scripts)

    // Locks
    void setLocks(const Locks& locks) { m_locks = locks; }
    const Locks& locks() const { return m_locks; }

    // Last snap
    void record(const std::optional<QPointF>& from, QPointF point, int kind);
    int serial() const { return m_serial; } // bumps on every record()
    std::optional<QPointF> lastFrom() const { return m_from; }
    QPointF lastPoint() const { return m_point; }
    int lastKind() const { return m_kind; }

private:
    bool m_enabled = true;
    QVector<Guide> m_guides;
    std::optional<Guide> m_hover;
    bool m_hoverUsed = false; // this rest already acquired/released its point
    Locks m_locks;
    int m_serial = 0;
    std::optional<QPointF> m_from;
    QPointF m_point;
    int m_kind = 0;
};

} // namespace kimcad
