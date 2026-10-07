// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QString>
#include <QWidget>

class QHBoxLayout;
class QVBoxLayout;

namespace kimcad {

class Viewport;

// A center tab around a Viewport (D71): the 3D tab or a level's plan tab. The active tab adopts the
// window's per-view chrome: the tool options strip on top and the plan-cut column on the right.
class ViewHost : public QWidget {
    Q_OBJECT
public:
    explicit ViewHost(Viewport* view, QWidget* parent = nullptr);
    Viewport* viewport() const { return m_view; }
    void adoptChrome(QWidget* optionsStrip, QWidget* cutColumn); // moves them into this tab
    void setStorey(const QString& guid) { m_storey = guid; }      // a plan tab's level ("" for 3D)
    QString storey() const { return m_storey; }

private:
    Viewport* m_view;
    QVBoxLayout* m_top; // tool options strip
    QHBoxLayout* m_row; // view | cut column
    QString m_storey;
};

} // namespace kimcad
