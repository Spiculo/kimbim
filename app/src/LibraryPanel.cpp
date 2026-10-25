// SPDX-License-Identifier: GPL-3.0-or-later
#include "LibraryPanel.h"

#include "Translations.h"

#include <QCoreApplication>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLineEdit>
#include <QMenu>
#include <QPainter>
#include <QPainterPath>
#include <QPixmap>
#include <QPushButton>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>

namespace kimbim {

namespace {

enum { IdRole = Qt::UserRole + 1 };

// The category names (kimbim/library.py) and group headings, so lupdate finds them; object and
// parameter names come from the object files (D99).
[[maybe_unused]] const char* const kNames[] = {
    QT_TRANSLATE_NOOP("LibraryPanel", "Furniture"), QT_TRANSLATE_NOOP("LibraryPanel", "Sanitary"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Kitchen"), QT_TRANSLATE_NOOP("LibraryPanel", "People, trees and cars"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Office library"), QT_TRANSLATE_NOOP("LibraryPanel", "Project"),
    // the bundled objects' parameter group headings (D100; an object file may give its own Spanish)
    QT_TRANSLATE_NOOP("LibraryPanel", "Seat"), QT_TRANSLATE_NOOP("LibraryPanel", "Legs"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Back"), QT_TRANSLATE_NOOP("LibraryPanel", "Arms"),
};

} // namespace

QString LibraryPanel::translated(const QString& english, const QString& spanish)
{
    if (!spanish.isEmpty() && currentLanguage() == QLatin1String("es"))
        return spanish;
    return QCoreApplication::translate("LibraryPanel", english.toUtf8().constData());
}

QIcon LibraryPanel::symbolIcon(const QJsonArray& symbol, double width, double depth, int size)
{
    QPixmap pixmap(size, size);
    pixmap.fill(Qt::white);
    double x0 = 0, y0 = 0, x1 = std::max(width, 0.01), y1 = std::max(depth, 0.01);
    for (const auto& c : symbol)
        for (const auto& p : c.toArray()) {
            const QJsonArray a = p.toArray();
            x0 = std::min(x0, a.at(0).toDouble());
            x1 = std::max(x1, a.at(0).toDouble());
            y0 = std::min(y0, a.at(1).toDouble());
            y1 = std::max(y1, a.at(1).toDouble());
        }
    const double margin = size * 0.1;
    const double k = (size - 2 * margin) / std::max(x1 - x0, y1 - y0);
    const double ox = (size - (x1 - x0) * k) / 2, oy = (size - (y1 - y0) * k) / 2;
    QPainter painter(&pixmap);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(QPen(QColor(40, 40, 40), 1.0));
    for (const auto& c : symbol) {
        QPainterPath path;
        bool first = true;
        for (const auto& p : c.toArray()) {
            const QJsonArray a = p.toArray();
            const QPointF q(ox + (a.at(0).toDouble() - x0) * k, size - oy - (a.at(1).toDouble() - y0) * k); // y up
            if (first)
                path.moveTo(q);
            else
                path.lineTo(q);
            first = false;
        }
        painter.drawPath(path);
    }
    painter.end();
    return QIcon(pixmap);
}

LibraryPanel::LibraryPanel(QWidget* parent)
    : QWidget(parent)
    , m_tree(new QTreeWidget(this))
    , m_search(new QLineEdit(this))
{
    setObjectName(QStringLiteral("libraryPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);
    m_search->setObjectName(QStringLiteral("librarySearch"));
    m_search->setPlaceholderText(tr("Search objects"));
    m_search->setClearButtonEnabled(true);
    layout->addWidget(m_search);
    m_tree->setObjectName(QStringLiteral("libraryTree"));
    m_tree->setHeaderHidden(true);
    m_tree->setIconSize(QSize(36, 36));
    m_tree->setContextMenuPolicy(Qt::CustomContextMenu);
    m_tree->setToolTip(tr("Click an object to place it; right-click for its settings and saved versions, or to edit it"));
    layout->addWidget(m_tree, 1);
    auto* row = new QHBoxLayout;
    auto* create = new QPushButton(tr("New object..."), this);
    create->setObjectName(QStringLiteral("libraryNewObject"));
    create->setToolTip(tr("Make a new library object in the Object Editor"));
    row->addWidget(create);
    auto* office = new QPushButton(tr("Office library..."), this);
    office->setObjectName(QStringLiteral("libraryOffice"));
    office->setToolTip(tr("Choose the office library folder: object files (.kimobj) and IFC type libraries (.ifc)"));
    auto* ifc = new QPushButton(tr("Load IFC types..."), this);
    ifc->setObjectName(QStringLiteral("libraryIfc"));
    ifc->setToolTip(tr("Add the types of an IFC file (e.g. IfcFurnitureType definitions) to the office library"));
    row->addWidget(office);
    row->addWidget(ifc);
    layout->addLayout(row);

    connect(m_search, &QLineEdit::textChanged, this, &LibraryPanel::setFilter);
    connect(m_tree, &QTreeWidget::currentItemChanged, this, [this](QTreeWidgetItem* item) {
        const QString id = item ? item->data(0, IdRole).toString() : QString();
        if (id.isEmpty() || id == m_current)
            return;
        m_current = id;
        emit currentChanged();
    });
    const auto place = [this](QTreeWidgetItem* item) {
        if (!item || item->data(0, IdRole).toString().isEmpty())
            return;
        m_tree->setCurrentItem(item);
        emit placeRequested();
    };
    connect(m_tree, &QTreeWidget::itemClicked, this, place);
    connect(m_tree, &QTreeWidget::itemActivated, this, place); // Enter
    connect(m_tree, &QTreeWidget::customContextMenuRequested, this, [this](const QPoint& pos) {
        QTreeWidgetItem* item = m_tree->itemAt(pos);
        const QString id = item ? item->data(0, IdRole).toString() : QString();
        if (id.isEmpty())
            return;
        m_tree->setCurrentItem(item);
        showObjectMenu(id, m_tree->viewport()->mapToGlobal(pos));
    });
    connect(create, &QPushButton::clicked, this, &LibraryPanel::newObjectRequested);
    connect(office, &QPushButton::clicked, this, &LibraryPanel::officeLibraryRequested);
    connect(ifc, &QPushButton::clicked, this, &LibraryPanel::ifcLibraryRequested);
}

void LibraryPanel::showObjectMenu(const QString& id, const QPoint& globalPos)
{
    QMenu menu(this);
    menu.setObjectName(QStringLiteral("libraryObjectMenu"));
    connect(menu.addAction(tr("Settings...")), &QAction::triggered, this, [this, id] { emit settingsRequested(id); });
    // D101: office and project objects open for editing, bundled ones as a copy; an office IFC type is
    // fixed geometry, nothing to edit.
    if (!id.startsWith(QLatin1String("ifc:"))) {
        const bool own = id.startsWith(QLatin1String("office:")) || id.startsWith(QLatin1String("project:"));
        QAction* edit = menu.addAction(own ? tr("Edit object...") : tr("Customise a copy..."));
        edit->setToolTip(own ? tr("Change this object's definition in the Object Editor")
                             : tr("A new object made from this one in the Object Editor; the bundled object stays as it is"));
        connect(edit, &QAction::triggered, this, [this, id] { emit editorRequested(id); });
    }
    menu.exec(globalPos);
}

void LibraryPanel::setListing(const QJsonObject& listing)
{
    const QString keep = m_current;
    const QHash<QString, QJsonObject> before = m_objects;
    m_tree->clear();
    m_objects.clear();
    QHash<QString, QTreeWidgetItem*> categories;
    for (const auto& c : listing.value("categories").toArray()) {
        const QJsonObject o = c.toObject();
        auto* item = new QTreeWidgetItem(m_tree, {translated(o.value("name").toString(), o.value("name_es").toString())});
        item->setFlags(Qt::ItemIsEnabled);
        categories.insert(o.value("id").toString(), item);
    }
    for (const auto& v : listing.value("objects").toArray()) {
        const QJsonObject o = v.toObject();
        const QString id = o.value("id").toString();
        m_objects.insert(id, o);
        QTreeWidgetItem* parent = categories.value(o.value("category").toString());
        if (!parent)
            parent = categories.value(QStringLiteral("office"));
        if (!parent)
            continue;
        auto* item = new QTreeWidgetItem(parent, {entryText(id)});
        item->setData(0, IdRole, id);
        item->setToolTip(0, o.value("ifc_class").toString());
        // drawn once per object (default sizes), again when its symbol changed (an edited object, D101)
        const QJsonObject old = before.value(id);
        if (!m_icons.contains(id) || old.value("symbol") != o.value("symbol") || old.value("width") != o.value("width")
            || old.value("depth") != o.value("depth"))
            m_icons.insert(id, symbolIcon(o.value("symbol").toArray(), o.value("width").toDouble(1.0), o.value("depth").toDouble(1.0)));
        item->setIcon(0, m_icons.value(id));
    }
    for (QTreeWidgetItem* c : std::as_const(categories)) {
        c->setHidden(c->childCount() == 0);
        c->setExpanded(true);
    }
    setFilter(m_search->text());
    if (!keep.isEmpty() && m_objects.contains(keep)) {
        const QSignalBlocker block(this); // the same object: no change
        m_current.clear();
        selectObject(keep);
    } else if (!keep.isEmpty()) {
        m_current.clear(); // gone from the library
        emit currentChanged();
    }
}

QStringList LibraryPanel::objectIds() const
{
    return m_objects.keys();
}

QTreeWidgetItem* LibraryPanel::itemOf(const QString& id) const
{
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        QTreeWidgetItem* category = m_tree->topLevelItem(i);
        for (int j = 0; j < category->childCount(); ++j)
            if (category->child(j)->data(0, IdRole).toString() == id)
                return category->child(j);
    }
    return nullptr;
}

QString LibraryPanel::entryText(const QString& id) const
{
    const QJsonObject o = m_objects.value(id);
    const QString name = translated(o.value("name").toString(), o.value("name_es").toString());
    const QString label = m_labels.value(id);
    return label.isEmpty() ? name : name + QStringLiteral(" · ") + label;
}

void LibraryPanel::setVersionLabel(const QString& id, const QString& label)
{
    if (label.isEmpty())
        m_labels.remove(id);
    else
        m_labels.insert(id, label);
    if (QTreeWidgetItem* item = itemOf(id))
        item->setText(0, entryText(id));
}

void LibraryPanel::setFilter(const QString& text)
{
    const QString needle = text.trimmed();
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        QTreeWidgetItem* category = m_tree->topLevelItem(i);
        int shown = 0;
        for (int j = 0; j < category->childCount(); ++j) {
            QTreeWidgetItem* item = category->child(j);
            const QString id = item->data(0, IdRole).toString();
            const bool match = needle.isEmpty() || item->text(0).contains(needle, Qt::CaseInsensitive)
                || m_objects.value(id).value("name").toString().contains(needle, Qt::CaseInsensitive);
            item->setHidden(!match);
            shown += match ? 1 : 0;
        }
        category->setHidden(shown == 0);
    }
}

int LibraryPanel::visibleObjectCount() const
{
    int n = 0;
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        const QTreeWidgetItem* category = m_tree->topLevelItem(i);
        for (int j = 0; j < category->childCount(); ++j)
            n += (!category->isHidden() && !category->child(j)->isHidden()) ? 1 : 0;
    }
    return n;
}

bool LibraryPanel::selectObject(const QString& id)
{
    QTreeWidgetItem* item = itemOf(id);
    if (!item)
        return false;
    m_tree->setCurrentItem(item);
    return true;
}

QString LibraryPanel::currentName() const
{
    const QJsonObject o = m_objects.value(m_current);
    return translated(o.value("name").toString(), o.value("name_es").toString());
}

QJsonObject LibraryPanel::currentInfo(const QJsonObject& values) const
{
    QJsonObject info = m_objects.value(m_current);
    for (const char* key : {"width", "depth", "height"})
        if (values.contains(QLatin1String(key)))
            info.insert(QLatin1String(key), values.value(QLatin1String(key)));
    if (!values.contains(QStringLiteral("depth")) && values.contains(QStringLiteral("width")))
        info.insert(QStringLiteral("depth"), values.value(QStringLiteral("width"))); // round (a tree's crown)
    return info;
}

} // namespace kimbim
