// SPDX-License-Identifier: GPL-3.0-or-later
#include "LevelsDialog.h"

#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLocale>
#include <QMessageBox>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>

namespace kimcad {

namespace {
constexpr double kDefaultHeight = 3.0; // metres: a new level's height when nothing says otherwise
constexpr double kSame = 1e-7;
enum Column { Name, Elevation, Height, Show, Elements, Columns };
} // namespace

// ---------------------------------------------------------------- LevelsTable

LevelsTable::LevelsTable(const QJsonArray& levels)
{
    for (const auto& v : levels) {
        const QJsonObject o = v.toObject();
        m_rows.push_back({o.value("guid").toString(), o.value("name").toString(), o.value("elevation").toDouble(),
            o.value("show").toBool(true), o.value("elements").toInt(), m_nextKey++});
    }
    sort();
    m_original = m_rows;
}

void LevelsTable::sort()
{
    std::stable_sort(m_rows.begin(), m_rows.end(), [](const Row& a, const Row& b) { return a.elevation < b.elevation; });
}

double LevelsTable::heightToNext(int i) const
{
    return i >= 0 && i + 1 < count() ? m_rows[i + 1].elevation - m_rows[i].elevation : -1.0;
}

void LevelsTable::setName(int i, const QString& name)
{
    if (i >= 0 && i < count() && !name.trimmed().isEmpty())
        m_rows[i].name = name.trimmed();
}

void LevelsTable::setShown(int i, bool show)
{
    if (i >= 0 && i < count())
        m_rows[i].show = show;
}

int LevelsTable::setElevation(int i, double metres)
{
    if (i < 0 || i >= count())
        return i;
    m_rows[i].elevation = metres;
    const int key = m_rows[i].key;
    sort();
    for (int j = 0; j < count(); ++j)
        if (m_rows[j].key == key)
            return j;
    return i;
}

void LevelsTable::setHeightToNext(int i, double metres)
{
    const double now = heightToNext(i);
    if (now < 0 || metres <= 0)
        return;
    const double delta = metres - now;
    for (int j = i + 1; j < count(); ++j)
        m_rows[j].elevation += delta;
}

int LevelsTable::insertAbove(int i, const QString& name)
{
    if (count() == 0) {
        m_rows.push_back({QString(), name, 0.0, true, 0, m_nextKey++});
        return 0;
    }
    i = std::clamp(i, 0, count() - 1);
    const double h = heightToNext(i) > 0 ? heightToNext(i) : kDefaultHeight;
    for (int j = i + 1; j < count(); ++j)
        m_rows[j].elevation += h;
    m_rows.insert(i + 1, Row{QString(), name, m_rows[i].elevation + h, true, 0, m_nextKey++});
    return i + 1;
}

int LevelsTable::insertBelow(int i, const QString& name)
{
    if (count() == 0)
        return insertAbove(0, name);
    i = std::clamp(i, 0, count() - 1);
    const double h = heightToNext(i) > 0 ? heightToNext(i) : kDefaultHeight;
    const double at = m_rows[i].elevation;
    for (int j = i; j < count(); ++j)
        m_rows[j].elevation += h;
    m_rows.insert(i, Row{QString(), name, at, true, 0, m_nextKey++});
    return i;
}

QString LevelsTable::neighbourFor(int i) const
{
    for (int j = i - 1; j >= 0; --j)
        if (!m_rows[j].guid.isEmpty())
            return m_rows[j].guid;
    for (int j = i + 1; j < count(); ++j)
        if (!m_rows[j].guid.isEmpty())
            return m_rows[j].guid;
    return {};
}

bool LevelsTable::remove(int i, const QString& elements, const QString& moveTo)
{
    if (i < 0 || i >= count() || count() <= 1)
        return false; // a model keeps at least one level
    const Row row = m_rows[i];
    if (row.elements > 0 && elements != QLatin1String("delete") && !(elements == QLatin1String("move") && !moveTo.isEmpty()))
        return false;
    m_rows.removeAt(i);
    if (row.elements > 0 && elements == QLatin1String("move"))
        for (Row& r : m_rows)
            if (r.guid == moveTo)
                r.elements += row.elements; // they count there now (deleting that level asks again)
    if (!row.guid.isEmpty())
        m_deleted.push_back({row.guid, row.elements > 0 ? elements : QString(), row.elements > 0 ? moveTo : QString()});
    return true;
}

bool LevelsTable::modified() const
{
    if (!m_deleted.isEmpty() || m_rows.size() != m_original.size())
        return true;
    for (const Row& r : m_rows) {
        if (r.guid.isEmpty())
            return true;
        const auto it = std::find_if(m_original.begin(), m_original.end(), [&](const Row& o) { return o.guid == r.guid; });
        if (it == m_original.end() || it->name != r.name || it->show != r.show || std::abs(it->elevation - r.elevation) > kSame)
            return true;
    }
    return false;
}

QJsonObject LevelsTable::changes() const
{
    QJsonArray levels, deleted;
    for (const Row& r : m_rows)
        levels.append(QJsonObject{{"guid", r.guid}, {"name", r.name}, {"elevation", r.elevation}, {"show", r.show}});
    for (const Deleted& d : m_deleted) {
        QJsonObject o{{"guid", d.guid}};
        if (!d.elements.isEmpty())
            o.insert("elements", d.elements);
        if (!d.moveTo.isEmpty())
            o.insert("move_to", d.moveTo);
        deleted.append(o);
    }
    return {{"levels", levels}, {"deleted", deleted}};
}

// ---------------------------------------------------------------- LevelsDialog

LevelsDialog::LevelsDialog(const QJsonArray& levels, const QString& unit, double factor, int decimals, QWidget* parent)
    : QDialog(parent)
    , m_table(levels)
    , m_unit(unit)
    , m_factor(factor > 0 ? factor : 1.0)
    , m_decimals(decimals)
{
    setObjectName(QStringLiteral("levelsDialog"));
    setWindowTitle(tr("Levels"));
    auto* layout = new QVBoxLayout(this);
    m_grid = new QTableWidget(0, Columns, this);
    m_grid->setObjectName(QStringLiteral("levelsGrid"));
    m_grid->setHorizontalHeaderLabels({tr("Name"), tr("Elevation (%1)").arg(unit), tr("Height to next (%1)").arg(unit),
        tr("Show in level list"), tr("Elements")});
    m_grid->verticalHeader()->hide();
    m_grid->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_grid->setSelectionMode(QAbstractItemView::SingleSelection);
    m_grid->horizontalHeader()->setSectionResizeMode(Name, QHeaderView::Stretch);
    for (int c = Elevation; c < Columns; ++c)
        m_grid->horizontalHeader()->setSectionResizeMode(c, QHeaderView::ResizeToContents);
    m_grid->setMinimumWidth(560);
    layout->addWidget(m_grid);
    auto* note = new QLabel(tr("Highest level first. A new elevation moves that level and its elements; a new "
                               "height to next moves every level above. Changes apply on OK, as one undo step."), this);
    note->setWordWrap(true);
    layout->addWidget(note);
    auto* row = new QHBoxLayout;
    auto* above = new QPushButton(tr("Insert &above"), this);
    above->setObjectName(QStringLiteral("insertAbove"));
    auto* below = new QPushButton(tr("Insert &below"), this);
    below->setObjectName(QStringLiteral("insertBelow"));
    m_delete = new QPushButton(tr("&Delete"), this);
    m_delete->setObjectName(QStringLiteral("deleteLevel"));
    row->addWidget(above);
    row->addWidget(below);
    row->addWidget(m_delete);
    row->addStretch(1);
    layout->addLayout(row);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    layout->addWidget(buttons);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    connect(above, &QPushButton::clicked, this, &LevelsDialog::insertAbove);
    connect(below, &QPushButton::clicked, this, &LevelsDialog::insertBelow);
    connect(m_delete, &QPushButton::clicked, this, [this] { deleteSelected(); });
    connect(m_grid, &QTableWidget::cellChanged, this, &LevelsDialog::edited);
    connect(m_grid, &QTableWidget::itemSelectionChanged, this,
        [this] { m_delete->setEnabled(currentRow() >= 0 && m_table.count() > 1); });
    fill();
    selectRow(0);
}

QString LevelsDialog::lengthText(double metres) const
{
    return QLocale().toString(metres * m_factor, 'f', m_decimals);
}

bool LevelsDialog::parseLength(const QString& text, double* metres) const
{
    bool ok = false;
    double v = QLocale().toDouble(text.trimmed(), &ok);
    if (!ok)
        v = QLocale::c().toDouble(QString(text.trimmed()).replace(QLatin1Char(','), QLatin1Char('.')), &ok);
    if (ok && std::isfinite(v))
        *metres = v / m_factor;
    return ok && std::isfinite(v);
}

int LevelsDialog::currentRow() const
{
    const int r = m_grid->currentRow();
    return r < 0 || r >= m_table.count() ? -1 : m_table.count() - 1 - r;
}

void LevelsDialog::selectRow(int tableIndex)
{
    if (tableIndex >= 0 && tableIndex < m_table.count())
        m_grid->selectRow(m_table.count() - 1 - tableIndex);
}

void LevelsDialog::fill()
{
    m_filling = true;
    const int n = m_table.count();
    m_grid->setRowCount(n);
    for (int i = 0; i < n; ++i) {
        const LevelsTable::Row& level = m_table.rows()[i];
        const int r = n - 1 - i; // highest first (Archicad)
        auto set = [&](int column, const QString& text, bool editable) {
            auto* item = new QTableWidgetItem(text);
            if (!editable)
                item->setFlags(item->flags() & ~Qt::ItemIsEditable);
            if (column != Name)
                item->setTextAlignment(Qt::AlignRight | Qt::AlignVCenter);
            m_grid->setItem(r, column, item);
        };
        set(Name, level.name, true);
        set(Elevation, lengthText(level.elevation), true);
        const double h = m_table.heightToNext(i);
        set(Height, h < 0 ? QString() : lengthText(h), h >= 0);
        auto* show = new QTableWidgetItem;
        show->setFlags((show->flags() | Qt::ItemIsUserCheckable) & ~Qt::ItemIsEditable);
        show->setCheckState(level.show ? Qt::Checked : Qt::Unchecked);
        m_grid->setItem(r, Show, show);
        set(Elements, level.guid.isEmpty() ? tr("new") : QString::number(level.elements), false);
    }
    m_filling = false;
    m_delete->setEnabled(currentRow() >= 0 && n > 1);
}

void LevelsDialog::edited(int row, int column)
{
    if (m_filling)
        return;
    const int i = m_table.count() - 1 - row;
    QTableWidgetItem* item = m_grid->item(row, column);
    if (!item || i < 0)
        return;
    int keep = i;
    double metres = 0;
    switch (column) {
    case Name:
        m_table.setName(i, item->text());
        break;
    case Elevation:
        if (parseLength(item->text(), &metres))
            keep = m_table.setElevation(i, metres);
        break;
    case Height:
        if (parseLength(item->text(), &metres) && metres > 0)
            m_table.setHeightToNext(i, metres);
        break;
    case Show:
        m_table.setShown(i, item->checkState() == Qt::Checked);
        break;
    default:
        break;
    }
    // Refill after the edit is committed (the view is still inside the item's setData).
    QMetaObject::invokeMethod(this, [this, keep] {
        fill();
        selectRow(keep);
    }, Qt::QueuedConnection);
}

void LevelsDialog::insertAbove()
{
    const int i = currentRow() >= 0 ? currentRow() : m_table.count() - 1;
    const int at = m_table.insertAbove(i, tr("Level %1").arg(m_table.count() + 1));
    fill();
    selectRow(at);
}

void LevelsDialog::insertBelow()
{
    const int i = currentRow() >= 0 ? currentRow() : 0;
    const int at = m_table.insertBelow(i, tr("Level %1").arg(m_table.count() + 1));
    fill();
    selectRow(at);
}

void LevelsDialog::deleteSelected(const QString& quietChoice)
{
    const int i = currentRow();
    if (i < 0 || m_table.count() <= 1)
        return;
    const LevelsTable::Row level = m_table.rows()[i];
    QString choice, target;
    if (level.elements > 0) {
        target = m_table.neighbourFor(i);
        QString targetName;
        for (const auto& r : m_table.rows())
            if (r.guid == target)
                targetName = r.name;
        if (quietChoice == QLatin1String("ask")) {
            // Archicad deletes a story's elements with it (after a warning); moving them is offered too.
            QMessageBox box(QMessageBox::Warning, tr("Delete level"),
                tr("%1 has %n element(s) on it.", nullptr, level.elements).arg(level.name), QMessageBox::Cancel, this);
            box.setInformativeText(tr("Delete them with the level, or move them to another level where they are?"));
            QPushButton* del = box.addButton(tr("Delete the elements too"), QMessageBox::DestructiveRole);
            QPushButton* move = target.isEmpty() ? nullptr
                                                 : box.addButton(tr("Move them to %1").arg(targetName), QMessageBox::AcceptRole);
            box.setDefaultButton(QMessageBox::Cancel);
            box.exec();
            if (box.clickedButton() == del)
                choice = QStringLiteral("delete");
            else if (move && box.clickedButton() == move)
                choice = QStringLiteral("move");
            else
                return;
        } else {
            choice = quietChoice;
        }
    }
    if (!m_table.remove(i, choice, choice == QLatin1String("move") ? target : QString()))
        return;
    fill();
    selectRow(std::min(i, m_table.count() - 1));
}

} // namespace kimcad
