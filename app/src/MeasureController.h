// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointF>
#include <QPointer>

#include <functional>

#include "MeasureTool.h"

namespace kimcad {

class Viewport;

// Ties the measure tool (D79) to the views: work-plane points from the view the mouse is in (and,
// in 3D views, the element surface under it), the path drawn in that view, the readout for the
// bottom bar and the clipboard. Never touches the model.
class MeasureController : public QObject {
    Q_OBJECT
public:
    MeasureController(std::function<QString(double)> length, QObject* parent = nullptr);
    MeasureTool* tool() { return &m_tool; }

    void pointer(Viewport* view, QPointF p, double z, double tolerance, bool ortho, bool click);
    void finish() { m_tool.finish(); }
    void clear() { m_tool.clear(); }  // Esc: the path goes, the tool stays
    void stop();                       // the tool is left: clear and remove the drawing
    QString text() const;              // the readout, as in the bottom bar
    void copyToClipboard() const;

signals:
    void message(const QString& text); // for the bottom bar

private:
    void redraw();

    MeasureTool m_tool;
    std::function<QString(double)> m_length;
    QPointer<Viewport> m_view;
};

} // namespace kimcad
