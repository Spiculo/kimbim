// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QWidget>

class QListWidget;
class QListWidgetItem;
class QPushButton;

namespace kimcad {

// Sections and elevations of the model (Slice 14, D60): open one in a drawing tab, rename, delete.
class DrawingsPanel : public QWidget {
    Q_OBJECT
public:
    explicit DrawingsPanel(QWidget* parent = nullptr);

    // [{guid, name, kind, stale, ...}] from the bridge's drawings().
    void setDrawings(const QJsonArray& drawings);
    QString selectedDrawing() const;
    QListWidget* list() const { return m_list; }
    int count() const;

signals:
    void openRequested(const QString& guid);
    void renameRequested(const QString& guid, const QString& name);
    void deleteRequested(const QString& guid);

private:
    QListWidget* m_list;
    QPushButton* m_open;
    QPushButton* m_rename;
    QPushButton* m_delete;
    bool m_filling = false;
};

} // namespace kimcad
