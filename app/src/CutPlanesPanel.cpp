// SPDX-License-Identifier: GPL-3.0-or-later
#include "CutPlanesPanel.h"

#include <QAbstractItemView>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLocale>
#include <QPushButton>
#include <QSignalBlocker>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QVBoxLayout>

namespace kimbim {

CutPlanesPanel::CutPlanesPanel(QWidget* parent)
    : QWidget(parent)
{
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(6, 6, 6, 6);
    layout->setSpacing(4);

    auto* adds = new QHBoxLayout;
    auto add = [this, adds](const char* name, const QString& text) {
        auto* b = new QPushButton(text, this);
        b->setObjectName(QLatin1String(name));
        b->setAutoDefault(false);
        adds->addWidget(b);
        return b;
    };
    connect(add("cutAddVertical", tr("Vertical")), &QPushButton::clicked, this, &CutPlanesPanel::addVerticalRequested);
    connect(add("cutAddHorizontal", tr("Horizontal...")), &QPushButton::clicked, this, &CutPlanesPanel::addHorizontalRequested);
    connect(add("cutAddOblique", tr("Oblique...")), &QPushButton::clicked, this, &CutPlanesPanel::addObliqueRequested);
    connect(add("cutAddFace", tr("From a face")), &QPushButton::clicked, this, &CutPlanesPanel::addFaceRequested);
    layout->addLayout(adds);

    m_table = new QTableWidget(this);
    m_table->setObjectName(QStringLiteral("cutPlanesTable"));
    m_table->setColumnCount(6);
    m_table->setHorizontalHeaderLabels({tr("Enabled"), tr("Visible"), tr("Name"), tr("Kind"),
        tr("Offset (m)"), tr("Angle (°)")});
    m_table->verticalHeader()->setVisible(false);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setSelectionMode(QAbstractItemView::SingleSelection);
    m_table->horizontalHeader()->setStretchLastSection(false);
    m_table->horizontalHeader()->setSectionResizeMode(2, QHeaderView::Stretch);
    m_table->setEditTriggers(QAbstractItemView::DoubleClicked | QAbstractItemView::SelectedClicked
        | QAbstractItemView::EditKeyPressed);
    layout->addWidget(m_table, 1);

    auto* edits = new QHBoxLayout;
    m_flip = new QPushButton(tr("Flip side"), this);
    m_flip->setObjectName(QStringLiteral("cutFlip"));
    m_section = new QPushButton(tr("Section..."), this);
    m_section->setObjectName(QStringLiteral("cutSection"));
    m_section->setToolTip(tr("Create a section drawing from the selected cut plane"));
    m_delete = new QPushButton(tr("Delete"), this);
    m_delete->setObjectName(QStringLiteral("cutDelete"));
    edits->addWidget(m_flip);
    edits->addWidget(m_section);
    edits->addStretch(1);
    edits->addWidget(m_delete);
    layout->addLayout(edits);

    connect(m_table, &QTableWidget::itemChanged, this, &CutPlanesPanel::onItemChanged);
    connect(m_table, &QTableWidget::itemSelectionChanged, this, &CutPlanesPanel::onSelectionChanged);
    connect(m_flip, &QPushButton::clicked, this, [this] {
        const int row = selectedRow();
        if (row >= 0)
            emit flipRequested(row);
    });
    connect(m_section, &QPushButton::clicked, this, [this] {
        const int row = selectedRow();
        if (row >= 0)
            emit sectionRequested(row);
    });
    connect(m_delete, &QPushButton::clicked, this, [this] {
        const int row = selectedRow();
        if (row >= 0)
            emit deleteRequested(row);
    });
    setPlanes({}, -1);
}

void CutPlanesPanel::setPlanes(const QVector<CutPlane>& planes, int selected)
{
    m_filling = true;
    const QSignalBlocker block(m_table);
    m_table->setRowCount(planes.size());
    const QLocale locale;
    for (int row = 0; row < planes.size(); ++row) {
        const CutPlane& p = planes[row];
        auto* on = new QTableWidgetItem;
        on->setFlags(Qt::ItemIsUserCheckable | Qt::ItemIsEnabled | Qt::ItemIsSelectable);
        on->setCheckState(p.enabled ? Qt::Checked : Qt::Unchecked);
        on->setToolTip(tr("On: the plane cuts the model; off: it only keeps its place in the list"));
        m_table->setItem(row, 0, on);
        auto* visible = new QTableWidgetItem;
        visible->setFlags(Qt::ItemIsUserCheckable | Qt::ItemIsEnabled | Qt::ItemIsSelectable);
        visible->setCheckState(p.visible ? Qt::Checked : Qt::Unchecked);
        visible->setToolTip(tr("Show the selected plane's face and handle in the view"));
        m_table->setItem(row, 1, visible);
        auto* name = new QTableWidgetItem(QString::fromStdString(p.name));
        name->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
        m_table->setItem(row, 2, name);
        const QString kind = p.kind == CutPlane::Kind::Horizontal ? tr("Horizontal")
            : p.kind == CutPlane::Kind::Vertical                    ? tr("Vertical")
                                                                    : tr("Oblique");
        auto* kindItem = new QTableWidgetItem(kind);
        kindItem->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
        m_table->setItem(row, 3, kindItem);
        m_table->setItem(row, 4, new QTableWidgetItem(locale.toString(p.offset(), 'f', 3)));
        auto* angle = new QTableWidgetItem(locale.toString(p.angle, 'f', 1));
        if (p.kind != CutPlane::Kind::Oblique)
            angle->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
        m_table->setItem(row, 5, angle);
    }
    m_filling = false;
    if (selected >= 0 && selected < planes.size())
        m_table->selectRow(selected);
    else
        m_table->clearSelection();
    m_flip->setEnabled(selected >= 0);
    m_section->setEnabled(selected >= 0);
    m_delete->setEnabled(selected >= 0);
}

int CutPlanesPanel::selectedRow() const
{
    const auto rows = m_table->selectionModel()->selectedRows();
    return rows.isEmpty() ? -1 : rows.first().row();
}

void CutPlanesPanel::onItemChanged(QTableWidgetItem* item)
{
    if (m_filling || !item)
        return;
    const int row = item->row();
    if (item->column() == 0) {
        emit enabledChanged(row, item->checkState() == Qt::Checked);
        return;
    }
    if (item->column() == 1) {
        emit visibleChanged(row, item->checkState() == Qt::Checked);
        return;
    }
    const QLocale locale;
    bool ok = false;
    if (item->column() == 4) {
        const double value = locale.toDouble(item->text(), &ok);
        if (ok)
            emit offsetChanged(row, value);
    } else if (item->column() == 5) {
        const double value = locale.toDouble(item->text(), &ok);
        if (ok)
            emit angleChanged(row, value);
    }
}

void CutPlanesPanel::onSelectionChanged()
{
    const int row = selectedRow();
    m_flip->setEnabled(row >= 0);
    m_section->setEnabled(row >= 0);
    m_delete->setEnabled(row >= 0);
    if (!m_filling)
        emit planeSelected(row);
}

} // namespace kimbim
