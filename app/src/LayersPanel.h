// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QSet>
#include <QWidget>

class QComboBox;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

// Layers (shown / locked / active, element count) and views (named collections of layer states).
class LayersPanel : public QWidget {
    Q_OBJECT
public:
    explicit LayersPanel(QWidget* parent = nullptr);

    void setLayers(const QJsonArray& layers, const QString& active, const QSet<QString>& hidden, const QSet<QString>& locked);
    void setViews(const QStringList& names, const QString& current);
    QString selectedLayer() const;
    QTreeWidget* list() const { return m_list; }

signals:
    void visibilityToggled(const QString& layer, bool visible);
    void lockToggled(const QString& layer, bool locked);
    void activeRequested(const QString& layer);
    void createRequested();
    void deleteRequested(const QString& layer);
    void renameRequested(const QString& oldName, const QString& newName);
    void assignRequested(const QString& layer);
    void viewRequested(const QString& view);
    void saveViewRequested();
    void deleteViewRequested(const QString& view);

private:
    void onItemChanged(QTreeWidgetItem* item, int column);

    QTreeWidget* m_list;
    QComboBox* m_views;
    bool m_filling = false;
};

} // namespace kimbim
