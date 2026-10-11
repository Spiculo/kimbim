// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QPointF>
#include <QString>
#include <QVector>

#include <array>
#include <optional>

#include <qnamespace.h>

#include "InputAids.h"

namespace kimcad {

// D89: the tracker's input (Archicad's Tracker; AutoCAD's dynamic input), pure logic. While a tool
// places points it shows the live length and angle from the tool's previous point (the anchor) and
// the x/y offset (or absolute x/y), and takes typed values: the focused field receives digits, Tab
// and Shift+Tab move between the fields, '<' goes to the angle (AutoCAD's "length<angle"), ';' to
// the next field, 'a' or '#' switches x/y to absolute coordinates and '@' back to relative (the
// default). Typed values lock the cursor (locks()) and Enter places target(). Without an anchor (the
// first point of a shape) only the absolute x/y fields are offered. Lengths in metres, angles in
// degrees counter-clockwise from east.
class Tracker {
public:
    enum Field { Length, Angle, X, Y };

    void setAnchor(const std::optional<QPointF>& anchor);
    std::optional<QPointF> anchor() const { return m_anchor; }
    void setCursor(QPointF p) { m_cursor = p; }
    QPointF cursor() const { return m_cursor; }

    // A key while drawing: true if the tracker used it (Enter and Esc are the caller's).
    bool key(int key, const QString& text, Qt::KeyboardModifiers modifiers = Qt::NoModifier);
    void type(const QString& text); // each character as a key (tests, scripts)
    void clear();                    // typed values gone, focus back to the first field

    QVector<Field> fields() const; // the fields shown: length, angle, x, y (x, y only without an anchor)
    Field focus() const { return m_focus; }
    void setFocus(Field f);
    bool absolute() const { return m_absolute || !m_anchor; }
    void setAbsolute(bool on) { m_absolute = on; }
    bool hasInput() const;
    QString typed(Field f) const { return m_text[f]; }
    std::optional<double> value(Field f) const; // the typed number, if any and valid
    double live(Field f) const;                 // what the cursor shows now
    // Only a length typed (relative): the classic typed length, which each tool knows how to use.
    bool lengthOnly() const;

    InputAids::Locks locks() const;
    std::optional<QPointF> target() const; // the point Enter places (nullopt: nothing typed)

private:
    std::optional<QPointF> m_anchor;
    QPointF m_cursor;
    std::array<QString, 4> m_text;
    Field m_focus = X;
    bool m_absolute = false;
};

} // namespace kimcad
