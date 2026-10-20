// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QList>
#include <QWidget>

class QHBoxLayout;

namespace kimbim {

// The active tool's fields (type, heights, roof, length) in a strip above the active view (D71).
// Its owner shows and hides the fields per tool; the strip itself shows only while a tool is active
// and has a field to show.
class ToolOptionsBar : public QWidget {
    Q_OBJECT
public:
    explicit ToolOptionsBar(QWidget* parent = nullptr);
    void addField(QWidget* field); // laid out left to right
    void setActive(bool toolActive);

private:
    QHBoxLayout* m_row;
    QList<QWidget*> m_fields;
};

} // namespace kimbim
