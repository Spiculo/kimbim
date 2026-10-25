// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QHash>
#include <QIcon>
#include <QJsonArray>
#include <QJsonObject>
#include <QWidget>

class QLineEdit;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

// The object library (D86, Archicad's Library): categories with the objects' plan symbols as
// thumbnails and a search field. Each entry shows the version a click places next to its name
// ("Chair · Dining", D100); a click starts the Object tool with it, a right click asks for the Object
// settings dialog. The panel only lists; the main window places (kimbim.library), keeps each
// object's current version and the office library paths.
class LibraryPanel : public QWidget {
    Q_OBJECT
public:
    explicit LibraryPanel(QWidget* parent = nullptr);

    // library_objects' listing: {"categories": [{id, name}], "objects": [{id, name, category,
    // params: [{key, label, value, kind, min, max}], symbol: [[[x, y]...]...], width, depth, height}]}.
    void setListing(const QJsonObject& listing);
    void setFilter(const QString& text); // the search field
    bool selectObject(const QString& id);
    QString currentObject() const { return m_current; }
    QString currentName() const;          // translated
    // The listing's entry of the current object, its sizes (width, depth, height) from `values`.
    QJsonObject currentInfo(const QJsonObject& values = {}) const;
    QStringList objectIds() const; // every listed object
    // The current version shown after the object's name ("" shows the name alone: the Default).
    // Kept across listings.
    void setVersionLabel(const QString& id, const QString& label);
    int visibleObjectCount() const;
    QTreeWidget* tree() const { return m_tree; }
    // A plan symbol drawn as an icon (cached by the caller); `size` pixels square.
    static QIcon symbolIcon(const QJsonArray& symbol, double width, double depth, int size = 48);
    static QString translated(const QString& english, const QString& spanish = {}); // object, category and parameter names

signals:
    void placeRequested(); // a click on an object (the current one)
    void settingsRequested(const QString& id); // a right click on an object: its Object settings
    void currentChanged();
    void officeLibraryRequested(); // choose the office library folder
    void ifcLibraryRequested();    // load an IFC type library file

private:
    QTreeWidgetItem* itemOf(const QString& id) const;
    QString entryText(const QString& id) const;
    QTreeWidget* m_tree;
    QLineEdit* m_search;
    QHash<QString, QJsonObject> m_objects;
    QHash<QString, QIcon> m_icons;
    QHash<QString, QString> m_labels;
    QString m_current;
};

} // namespace kimbim
