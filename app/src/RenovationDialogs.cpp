// SPDX-License-Identifier: GPL-3.0-or-later
// The Graphics menu's renovation filters editor (D74): per status, shown as is, hidden or overridden.
#include "GraphicsDialogs.h"

#include <QColorDialog>
#include <QComboBox>
#include <QHeaderView>
#include <QLabel>
#include <QPixmap>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

#include "PenGrid.h"
#include "PropertiesPanel.h" // renovationKeys, renovationLabel

namespace kimcad {

namespace {
QIcon colorIcon(const QColor& color)
{
    QPixmap p(12, 12);
    p.fill(color.isValid() ? color : QColor(Qt::transparent));
    return QIcon(p);
}
} // namespace

RenovationFiltersDialog::RenovationFiltersDialog(const QJsonObject& reply, QWidget* parent)
    : NamedSetsDialog(reply, QStringLiteral("renovation_filters"), QStringLiteral("renovation"), parent)
{
    setWindowTitle(tr("Renovation filters"));
    buildPicker();
    m_rows = new QTableWidget(3, 6, this);
    m_rows->setObjectName(QStringLiteral("renovationRows"));
    m_rows->setHorizontalHeaderLabels({tr("Status"), tr("Show"), tr("Line pen"), tr("Line type"), tr("Fill pen"), tr("3D colour")});
    m_rows->verticalHeader()->hide();
    m_rows->horizontalHeader()->setSectionResizeMode(QHeaderView::ResizeToContents);
    m_layout->addWidget(m_rows);
    m_layout->addWidget(new QLabel(tr("A purpose picks a renovation filter (Graphics > Purposes); graphic overrides apply on top."), this));
    finishLayout();
    resize(680, 300);
    selectSet(reply.value("tables").toObject().value("renovation_filters").toObject().keys().value(0));
}

QJsonObject RenovationFiltersDialog::treatment(const QString& status) const
{
    return currentValue().value(status).toObject();
}

void RenovationFiltersDialog::setTreatment(const QString& status, const QJsonObject& t)
{
    QJsonObject flt = currentValue();
    flt.insert(status, t);
    setCurrentValue(flt);
    showSet(currentSet());
}

void RenovationFiltersDialog::setShow(const QString& status, const QString& show)
{
    QJsonObject t = show == QLatin1String("override") ? treatment(status) : QJsonObject{};
    t.insert(QStringLiteral("show"), show); // as is and hide carry nothing else
    setTreatment(status, t);
}

void RenovationFiltersDialog::setField(const QString& status, const QString& field, const QJsonValue& value)
{
    QJsonObject t = treatment(status);
    t.insert(QStringLiteral("show"), QStringLiteral("override"));
    if (value.isNull() || (value.isString() && value.toString().isEmpty()))
        t.remove(field);
    else
        t.insert(field, value);
    setTreatment(status, t);
}

void RenovationFiltersDialog::setOverridePen(const QString& status, int pen) { setField(status, QStringLiteral("pen"), pen); }
void RenovationFiltersDialog::setOverrideFill(const QString& status, int pen) { setField(status, QStringLiteral("fill"), pen); }
void RenovationFiltersDialog::setOverrideLine(const QString& status, const QString& line) { setField(status, QStringLiteral("line"), line); }
void RenovationFiltersDialog::setOverrideSurface(const QString& status, const QColor& color)
{
    setField(status, QStringLiteral("surface"), color.isValid() ? QJsonValue(color.name()) : QJsonValue());
}

void RenovationFiltersDialog::showSet(const QString&)
{
    if (!m_rows)
        return;
    const QStringList lines = table("line_types").keys();
    const QHash<int, LineStyle> pens = currentPens();
    const QStringList keys = renovationKeys();
    for (int r = 0; r < keys.size(); ++r) {
        const QString status = keys[r];
        const QJsonObject t = treatment(status);
        const bool over = t.value("show").toString() == QLatin1String("override");
        auto* label = new QTableWidgetItem(renovationLabel(status));
        label->setFlags(label->flags() & ~Qt::ItemIsEditable);
        m_rows->setItem(r, 0, label);
        // Every change rebuilds the row's widgets: apply it after the click or selection that made it.
        auto later = [this](auto f) { QMetaObject::invokeMethod(this, f, Qt::QueuedConnection); };
        auto* show = new QComboBox(m_rows);
        show->addItem(tr("Show as is"), QStringLiteral("as_is"));
        show->addItem(tr("Hide"), QStringLiteral("hide"));
        show->addItem(tr("Override"), QStringLiteral("override"));
        show->setCurrentIndex(std::max(0, show->findData(t.value("show").toString(QStringLiteral("as_is")))));
        connect(show, &QComboBox::activated, this, [this, show, status, later](int i) {
            const QString v = show->itemData(i).toString();
            later([this, status, v] { setShow(status, v); });
        });
        m_rows->setCellWidget(r, 1, show);
        auto penButton = [&](int col, const char* field) {
            const int pen = t.value(QLatin1String(field)).toInt(0);
            auto* b = new QPushButton(pen > 0 ? QString::number(pen) : tr("(style)"), m_rows);
            if (pen > 0)
                b->setIcon(colorIcon(pens.value(pen, LineStyle{}).color));
            b->setEnabled(over);
            connect(b, &QPushButton::clicked, this, [this, b, status, pen, pens, field, later] {
                const int picked = PenGrid::pick(b, pens, {}, pen > 0 ? pen : 1);
                if (picked > 0)
                    later([this, status, picked, field] { setField(status, QLatin1String(field), picked); });
            });
            m_rows->setCellWidget(r, col, b);
        };
        penButton(2, "pen");
        auto* line = new QComboBox(m_rows);
        line->addItem(tr("(style)"), QString());
        for (const QString& l : lines)
            line->addItem(l, l);
        line->setCurrentIndex(std::max(0, line->findData(t.value("line").toString())));
        line->setEnabled(over);
        connect(line, &QComboBox::activated, this, [this, line, status, later](int i) {
            const QString v = line->itemData(i).toString();
            later([this, status, v] { setOverrideLine(status, v); });
        });
        m_rows->setCellWidget(r, 3, line);
        penButton(4, "fill");
        const QColor surface(t.value("surface").toString());
        auto* colour = new QPushButton(surface.isValid() ? surface.name() : tr("(none)"), m_rows);
        colour->setIcon(colorIcon(surface));
        colour->setEnabled(over);
        connect(colour, &QPushButton::clicked, this, [this, status, surface, later] {
            const QColor c = QColorDialog::getColor(surface.isValid() ? surface : Qt::yellow, this, tr("3D colour"));
            if (c.isValid())
                later([this, status, c] { setOverrideSurface(status, c); });
        });
        m_rows->setCellWidget(r, 5, colour);
    }
}

} // namespace kimcad
