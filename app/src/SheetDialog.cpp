// SPDX-License-Identifier: GPL-3.0-or-later
#include "SheetDialog.h"

#include <QAbstractItemView>
#include <QColorDialog>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QIcon>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPixmap>
#include <QPushButton>
#include <QSpinBox>
#include <QTableWidget>
#include <QVBoxLayout>

#include <algorithm>

namespace kimbim {

namespace {
QString kindLabel(const QString& kind)
{
    return kind == QLatin1String("plan") ? SheetSettingsDialog::tr("Floor plan")
        : kind == QLatin1String("section") ? SheetSettingsDialog::tr("Section")
                                           : SheetSettingsDialog::tr("Elevation");
}
} // namespace

SheetSettingsDialog::SheetSettingsDialog(const QJsonObject& sheet, QWidget* parent)
    : QDialog(parent)
    , m_title(new QLineEdit(sheet.value(QStringLiteral("title")).toString(), this))
    , m_number(new QLineEdit(sheet.value(QStringLiteral("number")).toString(), this))
    , m_paper(new QComboBox(this))
    , m_background(new QPushButton(this))
    , m_titleBlock(new QPushButton(tr("Title block..."), this))
    , m_colour(QColor(sheet.value(QStringLiteral("background")).toString()))
    , m_placed(new QTableWidget(this))
{
    setObjectName(QStringLiteral("sheetSettingsDialog"));
    setWindowTitle(tr("Sheet settings"));
    setMinimumSize(560, 420);
    if (!m_colour.isValid())
        m_colour = QColor(Qt::white);

    m_title->setObjectName(QStringLiteral("sheetSettingsTitle"));
    m_number->setObjectName(QStringLiteral("sheetSettingsNumber"));
    m_paper->setObjectName(QStringLiteral("sheetSettingsPaper"));
    m_paper->addItem(tr("A1 (841 x 594 mm)"), QStringLiteral("A1"));
    m_paper->addItem(tr("A3 (420 x 297 mm)"), QStringLiteral("A3"));
    const int paper = m_paper->findData(sheet.value(QStringLiteral("paper")).toString());
    m_paper->setCurrentIndex(std::max(0, paper));
    m_background->setObjectName(QStringLiteral("sheetSettingsBackground"));
    connect(m_background, &QPushButton::clicked, this, &SheetSettingsDialog::chooseBackground);
    updateBackground();

    connect(m_titleBlock, &QPushButton::clicked, this, &SheetSettingsDialog::titleBlockRequested);
    auto* form = new QFormLayout;
    form->addRow(tr("Title:"), m_title);
    form->addRow(tr("Number:"), m_number);
    form->addRow(tr("Paper:"), m_paper);
    form->addRow(tr("Background:"), m_background);
    form->addRow(tr("Title block text:"), m_titleBlock);

    m_placed->setObjectName(QStringLiteral("sheetSettingsPlaced"));
    m_placed->setColumnCount(3);
    m_placed->setHorizontalHeaderLabels({tr("Drawing"), tr("Scale 1:"), tr("Remove")});
    m_placed->verticalHeader()->setVisible(false);
    m_placed->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_placed->setSelectionMode(QAbstractItemView::NoSelection);
    m_placed->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_placed->horizontalHeader()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    m_placed->horizontalHeader()->setSectionResizeMode(2, QHeaderView::ResizeToContents);
    const QJsonArray views = sheet.value(QStringLiteral("views")).toArray();
    m_placed->setRowCount(views.size());
    for (int row = 0; row < views.size(); ++row) {
        const QJsonObject view = views[row].toObject();
        auto* name = new QTableWidgetItem(view.value(QStringLiteral("name")).toString());
        name->setFlags(Qt::ItemIsEnabled);
        m_placed->setItem(row, 0, name);
        auto* scale = new QSpinBox(m_placed);
        scale->setObjectName(QStringLiteral("sheetPlacedScale.") + view.value(QStringLiteral("drawing")).toString());
        scale->setRange(1, 1000);
        scale->setPrefix(QStringLiteral("1:"));
        scale->setValue(view.value(QStringLiteral("scale")).toInt(100));
        m_placed->setCellWidget(row, 1, scale);
        auto* remove = new QTableWidgetItem;
        remove->setFlags(Qt::ItemIsUserCheckable | Qt::ItemIsEnabled | Qt::ItemIsSelectable);
        remove->setCheckState(Qt::Unchecked);
        m_placed->setItem(row, 2, remove);
        m_rows.push_back({view.value(QStringLiteral("drawing")).toString(),
            view.value(QStringLiteral("scale")).toInt(100), scale, remove});
    }

    auto* hint = new QLabel(tr("Drag a placed drawing on the sheet to move it. A drawing's title, scale and "
                              "position are in its right-click menu."),
        this);
    hint->setWordWrap(true);
    hint->setStyleSheet(QStringLiteral("color:#666"));

    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);

    auto* layout = new QVBoxLayout(this);
    layout->addLayout(form);
    layout->addSpacing(6);
    layout->addWidget(new QLabel(tr("Drawings on this sheet:"), this));
    layout->addWidget(m_placed, 1);
    if (m_rows.isEmpty()) {
        auto* none = new QLabel(tr("No drawings on this sheet yet."), this);
        none->setStyleSheet(QStringLiteral("color:#777"));
        layout->addWidget(none);
    }
    layout->addWidget(hint);
    layout->addWidget(buttons);
}

void SheetSettingsDialog::chooseBackground()
{
    const QColor colour = QColorDialog::getColor(m_colour, this, tr("Sheet background"));
    if (!colour.isValid())
        return;
    m_colour = colour;
    updateBackground();
}

void SheetSettingsDialog::updateBackground()
{
    QPixmap swatch(16, 16);
    swatch.fill(m_colour);
    m_background->setIcon(QIcon(swatch));
    m_background->setText(m_colour.name().toUpper());
    m_background->setToolTip(tr("The paper colour of the sheet, on screen and when exported"));
}

QJsonObject SheetSettingsDialog::changes() const
{
    QJsonObject changes{{QStringLiteral("title"), m_title->text().trimmed()},
        {QStringLiteral("number"), m_number->text().trimmed()},
        {QStringLiteral("paper"), m_paper->currentData().toString()},
        {QStringLiteral("background"), m_colour.name()}};
    QJsonObject placements;
    QJsonArray removed;
    for (const Row& row : m_rows) {
        if (row.remove->checkState() == Qt::Checked) {
            removed.append(row.guid);
            continue;
        }
        if (row.spin->value() != row.scale)
            placements.insert(row.guid, QJsonObject{{QStringLiteral("scale"), row.spin->value()}});
    }
    if (!placements.isEmpty())
        changes.insert(QStringLiteral("placements"), placements);
    if (!removed.isEmpty())
        changes.insert(QStringLiteral("removed"), removed);
    return changes;
}

PlaceDrawingDialog::PlaceDrawingDialog(const QJsonArray& drawings, const QSet<QString>& placed,
    const QString& preferred, int scale, QWidget* parent)
    : QDialog(parent)
    , m_drawings(new QListWidget(this))
    , m_scale(new QSpinBox(this))
    , m_place(nullptr)
{
    setObjectName(QStringLiteral("placeDrawingDialog"));
    setWindowTitle(tr("Place drawing"));
    setMinimumSize(420, 340);
    m_drawings->setObjectName(QStringLiteral("placeDrawingList"));
    for (const auto& value : drawings) {
        const QJsonObject drawing = value.toObject();
        const QString guid = drawing.value(QStringLiteral("guid")).toString();
        QString label = QStringLiteral("%1  (%2)").arg(drawing.value(QStringLiteral("name")).toString(),
            kindLabel(drawing.value(QStringLiteral("kind")).toString()));
        auto* item = new QListWidgetItem(label, m_drawings);
        item->setData(Qt::UserRole, guid);
        if (placed.contains(guid)) {
            item->setText(item->text() + tr(" — already on this sheet"));
            item->setFlags(item->flags() & ~Qt::ItemIsEnabled);
        } else if (guid == preferred) {
            m_drawings->setCurrentItem(item);
        }
    }
    if (!m_drawings->currentItem() && m_drawings->count()) {
        for (int i = 0; i < m_drawings->count(); ++i)
            if (m_drawings->item(i)->flags() & Qt::ItemIsEnabled) {
                m_drawings->setCurrentRow(i);
                break;
            }
    }
    m_scale->setObjectName(QStringLiteral("placeDrawingScale"));
    m_scale->setRange(1, 1000);
    m_scale->setPrefix(QStringLiteral("1:"));
    m_scale->setValue(scale > 0 ? scale : 100);

    auto* form = new QFormLayout;
    form->addRow(tr("Drawing:"), m_drawings);
    form->addRow(tr("Scale:"), m_scale);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    m_place = buttons->button(QDialogButtonBox::Ok);
    m_place->setText(tr("Place"));
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    connect(m_drawings, &QListWidget::currentItemChanged, this, [this] { updatePlace(); });

    auto* layout = new QVBoxLayout(this);
    layout->addLayout(form, 1);
    if (drawings.isEmpty()) {
        auto* none = new QLabel(tr("There are no drawings yet. Create a section or elevation first."), this);
        none->setWordWrap(true);
        none->setStyleSheet(QStringLiteral("color:#777"));
        layout->addWidget(none);
    }
    layout->addWidget(buttons);
    updatePlace();
}

void PlaceDrawingDialog::updatePlace()
{
    const QListWidgetItem* item = m_drawings->currentItem();
    m_place->setEnabled(item && (item->flags() & Qt::ItemIsEnabled));
}

QString PlaceDrawingDialog::drawing() const
{
    const QListWidgetItem* item = m_drawings->currentItem();
    return item ? item->data(Qt::UserRole).toString() : QString();
}

int PlaceDrawingDialog::scale() const
{
    return m_scale->value();
}

PlacedDrawingDialog::PlacedDrawingDialog(const QString& title, int scale, double x, double y, QWidget* parent)
    : QDialog(parent)
    , m_title(new QLineEdit(title, this))
    , m_scale(new QSpinBox(this))
    , m_x(new QDoubleSpinBox(this))
    , m_y(new QDoubleSpinBox(this))
{
    setObjectName(QStringLiteral("placedDrawingDialog"));
    setWindowTitle(tr("Drawing settings"));
    m_title->setObjectName(QStringLiteral("placedDrawingTitle"));
    m_scale->setObjectName(QStringLiteral("placedDrawingScale"));
    m_scale->setRange(1, 1000);
    m_scale->setPrefix(QStringLiteral("1:"));
    m_scale->setValue(scale > 0 ? scale : 100);
    for (QDoubleSpinBox* box : {m_x, m_y}) {
        box->setRange(0.0, 10000.0);
        box->setDecimals(2);
        box->setSuffix(tr(" mm"));
    }
    m_x->setObjectName(QStringLiteral("placedDrawingX"));
    m_y->setObjectName(QStringLiteral("placedDrawingY"));
    m_x->setValue(x);
    m_y->setValue(y);

    auto* position = new QHBoxLayout;
    position->addWidget(new QLabel(tr("X:"), this));
    position->addWidget(m_x, 1);
    position->addWidget(new QLabel(tr("Y:"), this));
    position->addWidget(m_y, 1);
    auto* form = new QFormLayout;
    form->addRow(tr("Title:"), m_title);
    form->addRow(tr("Scale:"), m_scale);
    form->addRow(tr("Position:"), position);

    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &PlacedDrawingDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    auto* layout = new QVBoxLayout(this);
    layout->addLayout(form);
    layout->addWidget(buttons);
    setMinimumWidth(360);
}

void PlacedDrawingDialog::accept()
{
    if (m_title->text().trimmed().isEmpty()) {
        QMessageBox::warning(this, tr("Drawing settings"), tr("Type a name for the drawing."));
        m_title->setFocus();
        return;
    }
    QDialog::accept();
}

QString PlacedDrawingDialog::title() const
{
    return m_title->text().trimmed();
}

int PlacedDrawingDialog::scale() const
{
    return m_scale->value();
}

double PlacedDrawingDialog::x() const
{
    return m_x->value();
}

double PlacedDrawingDialog::y() const
{
    return m_y->value();
}

} // namespace kimbim
