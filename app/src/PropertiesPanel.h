// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QWidget>

class QTreeWidget;

namespace kimcad {

// Attributes and property sets of the selected element (read-only in M1; editing comes in M2).
class PropertiesPanel : public QWidget {
    Q_OBJECT
public:
    explicit PropertiesPanel(QWidget* parent = nullptr);
    void showProperties(const QJsonObject& props);
    void clear();
    QTreeWidget* tree() const { return m_tree; }

private:
    QTreeWidget* m_tree;
};

} // namespace kimcad
