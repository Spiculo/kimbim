// SPDX-License-Identifier: GPL-3.0-or-later
#include "LibraryPanel.h"

#include <QCoreApplication>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QPainter>
#include <QPainterPath>
#include <QPixmap>
#include <QPushButton>
#include <QSpinBox>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>

namespace kimbim {

namespace {

enum { IdRole = Qt::UserRole + 1 };

// The library's English names (kimbim/library.py), so lupdate finds them for translation.
[[maybe_unused]] const char* const kNames[] = {
    QT_TRANSLATE_NOOP("LibraryPanel", "Furniture"), QT_TRANSLATE_NOOP("LibraryPanel", "Sanitary"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Kitchen"), QT_TRANSLATE_NOOP("LibraryPanel", "People, trees and cars"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Office library"), QT_TRANSLATE_NOOP("LibraryPanel", "Table"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Chair"), QT_TRANSLATE_NOOP("LibraryPanel", "Sofa"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Single bed"), QT_TRANSLATE_NOOP("LibraryPanel", "Double bed"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Wardrobe"), QT_TRANSLATE_NOOP("LibraryPanel", "Desk"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Shelf"), QT_TRANSLATE_NOOP("LibraryPanel", "WC"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Washbasin"), QT_TRANSLATE_NOOP("LibraryPanel", "Bathtub"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Shower tray"), QT_TRANSLATE_NOOP("LibraryPanel", "Bidet"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Base cabinets"), QT_TRANSLATE_NOOP("LibraryPanel", "Wall cabinets"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Sink unit"), QT_TRANSLATE_NOOP("LibraryPanel", "Fridge"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Cooktop and oven"), QT_TRANSLATE_NOOP("LibraryPanel", "Person"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Tree"), QT_TRANSLATE_NOOP("LibraryPanel", "Car"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Width"), QT_TRANSLATE_NOOP("LibraryPanel", "Depth"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Height"), QT_TRANSLATE_NOOP("LibraryPanel", "Seat height"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Seats"), QT_TRANSLATE_NOOP("LibraryPanel", "Doors"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Shelves"), QT_TRANSLATE_NOOP("LibraryPanel", "Units"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Mounting height"), QT_TRANSLATE_NOOP("LibraryPanel", "Bowls"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Burners"), QT_TRANSLATE_NOOP("LibraryPanel", "Crown diameter"),
    QT_TRANSLATE_NOOP("LibraryPanel", "Trunk diameter"),
};

} // namespace

QString LibraryPanel::translated(const QString& english)
{
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
    layout->addWidget(m_tree, 3);
    m_title = new QLabel(this);
    m_title->setObjectName(QStringLiteral("libraryTitle"));
    QFont bold = m_title->font();
    bold.setBold(true);
    m_title->setFont(bold);
    layout->addWidget(m_title);
    m_formHost = new QWidget(this);
    m_form = new QFormLayout(m_formHost);
    m_form->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(m_formHost);
    auto* place = new QPushButton(tr("Place"), this);
    place->setObjectName(QStringLiteral("libraryPlace"));
    place->setToolTip(tr("Click in the view to place the object; Tab turns it 90 degrees, a typed number sets its angle"));
    layout->addWidget(place);
    auto* row = new QHBoxLayout;
    auto* office = new QPushButton(tr("Office library..."), this);
    office->setObjectName(QStringLiteral("libraryOffice"));
    office->setToolTip(tr("Choose the office library folder: Python objects (.py) and IFC type libraries (.ifc)"));
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
        m_params = QJsonObject();
        for (const auto& p : m_objects.value(id).value("params").toArray())
            m_params.insert(p.toObject().value("key").toString(), p.toObject().value("value"));
        showParams();
        emit currentChanged();
    });
    connect(m_tree, &QTreeWidget::itemDoubleClicked, this, [this](QTreeWidgetItem* item) {
        if (!item->data(0, IdRole).toString().isEmpty())
            emit placeRequested();
    });
    connect(place, &QPushButton::clicked, this, [this] {
        if (!m_current.isEmpty())
            emit placeRequested();
    });
    connect(office, &QPushButton::clicked, this, &LibraryPanel::officeLibraryRequested);
    connect(ifc, &QPushButton::clicked, this, &LibraryPanel::ifcLibraryRequested);
}

void LibraryPanel::setListing(const QJsonObject& listing)
{
    const QString keep = m_current;
    m_tree->clear();
    m_objects.clear();
    QHash<QString, QTreeWidgetItem*> categories;
    for (const auto& c : listing.value("categories").toArray()) {
        const QJsonObject o = c.toObject();
        auto* item = new QTreeWidgetItem(m_tree, {translated(o.value("name").toString())});
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
        auto* item = new QTreeWidgetItem(parent, {translated(o.value("name").toString())});
        item->setData(0, IdRole, id);
        item->setToolTip(0, o.value("ifc_class").toString());
        if (!m_icons.contains(id)) // drawn once per object (default sizes), not on every refresh
            m_icons.insert(id, symbolIcon(o.value("symbol").toArray(), o.value("width").toDouble(1.0), o.value("depth").toDouble(1.0)));
        item->setIcon(0, m_icons.value(id));
    }
    for (QTreeWidgetItem* c : std::as_const(categories)) {
        c->setHidden(c->childCount() == 0);
        c->setExpanded(true);
    }
    setFilter(m_search->text());
    if (!keep.isEmpty() && m_objects.contains(keep)) {
        const QJsonObject params = m_params;
        m_current.clear();
        selectObject(keep);
        for (auto it = params.begin(); it != params.end(); ++it)
            m_params.insert(it.key(), it.value());
        showParams();
    }
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
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        QTreeWidgetItem* category = m_tree->topLevelItem(i);
        for (int j = 0; j < category->childCount(); ++j)
            if (category->child(j)->data(0, IdRole).toString() == id) {
                m_tree->setCurrentItem(category->child(j));
                return true;
            }
    }
    return false;
}

QString LibraryPanel::currentName() const
{
    return translated(m_objects.value(m_current).value("name").toString());
}

QJsonObject LibraryPanel::currentParams() const
{
    return m_params;
}

QJsonObject LibraryPanel::currentInfo() const
{
    QJsonObject info = m_objects.value(m_current);
    for (const char* key : {"width", "depth", "height"})
        if (m_params.contains(QLatin1String(key)))
            info.insert(QLatin1String(key), m_params.value(QLatin1String(key)));
    if (!m_params.contains(QStringLiteral("depth")) && m_params.contains(QStringLiteral("width")))
        info.insert(QStringLiteral("depth"), m_params.value(QStringLiteral("width"))); // round (a tree's crown)
    return info;
}

void LibraryPanel::setParam(const QString& key, double value)
{
    m_params.insert(key, value);
    showParams();
}

void LibraryPanel::showParams()
{
    while (m_form->rowCount() > 0)
        m_form->removeRow(0);
    const QJsonObject o = m_objects.value(m_current);
    m_title->setText(o.isEmpty() ? QString() : translated(o.value("name").toString()));
    for (const auto& v : o.value("params").toArray()) {
        const QJsonObject p = v.toObject();
        const QString key = p.value("key").toString();
        const double value = m_params.value(key).toDouble(p.value("value").toDouble());
        QWidget* field = nullptr;
        if (p.value("kind").toString() == QLatin1String("count")) {
            auto* spin = new QSpinBox(m_formHost);
            spin->setRange(p.value("min").toInt(1), p.value("max").toInt(20));
            spin->setValue(int(std::lround(value)));
            connect(spin, &QSpinBox::valueChanged, this, [this, key](int n) { m_params.insert(key, n); emit currentChanged(); });
            field = spin;
        } else {
            auto* spin = new QDoubleSpinBox(m_formHost);
            spin->setDecimals(3);
            spin->setSingleStep(0.05);
            spin->setRange(p.value("min").toDouble(0.01), p.value("max").toDouble(50.0));
            spin->setSuffix(QStringLiteral(" m"));
            spin->setValue(value);
            connect(spin, &QDoubleSpinBox::valueChanged, this, [this, key](double d) { m_params.insert(key, d); emit currentChanged(); });
            field = spin;
        }
        field->setObjectName(QStringLiteral("libraryParam_") + key);
        m_form->addRow(translated(p.value("label").toString()) + QLatin1Char(':'), field);
    }
}

} // namespace kimbim
