// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QHash>
#include <QIcon>
#include <QJsonArray>
#include <QJsonObject>
#include <QWidget>

class QLabel;
class QLineEdit;
class QTreeWidget;
class QTreeWidgetItem;

namespace kimbim {

class ParameterForm;

// The object library (D86, Archicad's Library and Object settings): categories with the objects'
// plan symbols as thumbnails, a search field, and the selected object's parameters. Place (or a
// double click) starts the Object tool with that object and those values. The panel only lists and
// edits; the main window places (kimbim.library) and keeps the office library paths.
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
    QJsonObject currentParams() const;    // {key: value} as edited
    QJsonObject currentInfo() const;      // the listing's entry, with the edited sizes
    void setParam(const QString& key, const QJsonValue& value); // a size, or a part's material (D97)
    int visibleObjectCount() const;
    QTreeWidget* tree() const { return m_tree; }
    // A plan symbol drawn as an icon (cached by the caller); `size` pixels square.
    static QIcon symbolIcon(const QJsonArray& symbol, double width, double depth, int size = 48);
    static QString translated(const QString& english, const QString& spanish = {}); // object, category and parameter names

signals:
    void placeRequested();
    void currentChanged();
    void officeLibraryRequested(); // choose the office library folder
    void ifcLibraryRequested();    // load an IFC type library file

private:
    void showParams();
    QTreeWidget* m_tree;
    QLineEdit* m_search;
    ParameterForm* m_form; // ObjectSettingsDialog.h
    QLabel* m_title;
    QHash<QString, QJsonObject> m_objects;
    QHash<QString, QIcon> m_icons;
    QString m_current;
    QJsonObject m_params;
};

} // namespace kimbim
