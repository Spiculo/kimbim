// SPDX-License-Identifier: GPL-3.0-or-later
#include "UnderlayDialogs.h"

#include <QCheckBox>
#include <QColorDialog>
#include <QComboBox>
#include <QCoreApplication>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFileInfo>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QSlider>
#include <QSpinBox>
#include <QVBoxLayout>

#include <cmath>

namespace kimbim {

namespace {

struct UnitChoice {
    const char* label;
    double metres;
};
const UnitChoice kUnits[] = {{QT_TRANSLATE_NOOP("kimbim::PlaceUnderlayDialog", "millimetres"), 0.001},
    {QT_TRANSLATE_NOOP("kimbim::PlaceUnderlayDialog", "centimetres"), 0.01},
    {QT_TRANSLATE_NOOP("kimbim::PlaceUnderlayDialog", "decimetres"), 0.1},
    {QT_TRANSLATE_NOOP("kimbim::PlaceUnderlayDialog", "metres"), 1.0},
    {QT_TRANSLATE_NOOP("kimbim::PlaceUnderlayDialog", "inches"), 0.0254},
    {QT_TRANSLATE_NOOP("kimbim::PlaceUnderlayDialog", "feet"), 0.3048}};

QDoubleSpinBox* lengthBox(double value, double range = 1e6)
{
    auto* b = new QDoubleSpinBox;
    b->setRange(-range, range);
    b->setDecimals(3);
    b->setSuffix(QStringLiteral(" m"));
    b->setValue(value);
    return b;
}

QDoubleSpinBox* angleBox(double value)
{
    auto* b = new QDoubleSpinBox;
    b->setRange(-360, 360);
    b->setDecimals(2);
    b->setSuffix(QStringLiteral(" °"));
    b->setValue(value);
    return b;
}

QJsonObject call(const UnderlaysDialog::Bridge& bridge, const char* fn, const QStringList& args = {})
{
    return bridge ? bridge(fn, args) : QJsonObject();
}

} // namespace

// ---------------------------------------------------------------- placing

double PlaceUnderlayDialog::rasterScale(const QString& kind, int n, double dpi)
{
    const double perUnit = kind == QLatin1String("pdf") ? 0.0254 / 72.0 : 0.0254 / (dpi > 0 ? dpi : 96.0);
    return perUnit * std::max(1, n);
}

PlaceUnderlayDialog::PlaceUnderlayDialog(const QString& fileName, const QJsonObject& probe, const QStringList& layers, QWidget* parent)
    : QDialog(parent)
    , m_kind(probe.value("kind").toString())
{
    setWindowTitle(tr("Place underlay"));
    auto* form = new QFormLayout;
    form->addRow(tr("File:"), new QLabel(QFileInfo(fileName).fileName()));
    if (m_kind == QLatin1String("dxf")) {
        m_unit = new QComboBox;
        m_unit->setObjectName(QStringLiteral("underlayUnit"));
        const bool unitless = probe.value("units").isNull();
        const double current = unitless ? probe.value("unit_guess").toDouble(0.001) : probe.value("units").toDouble();
        for (const UnitChoice& u : kUnits) {
            m_unit->addItem(tr(u.label), u.metres);
            if (std::abs(u.metres - current) < 1e-12)
                m_unit->setCurrentIndex(m_unit->count() - 1);
        }
        form->addRow(tr("Drawing unit:"), m_unit);
        form->addRow(QString(), new QLabel(unitless ? tr("The DXF does not say which unit it was drawn in: check this.")
                                                    : tr("From the DXF file ($INSUNITS).")));
        form->addRow(tr("Lines:"), new QLabel(QLocale().toString(probe.value("segments").toInt())));
    } else {
        if (m_kind == QLatin1String("pdf")) {
            m_page = new QSpinBox;
            m_page->setObjectName(QStringLiteral("underlayPage"));
            const int pages = int(probe.value("pages").toArray().size());
            m_page->setRange(1, std::max(1, pages));
            form->addRow(tr("Page (of %1):").arg(pages), m_page);
        } else {
            m_dpi = new QDoubleSpinBox;
            m_dpi->setObjectName(QStringLiteral("underlayDpi"));
            m_dpi->setRange(10, 4800);
            m_dpi->setDecimals(0);
            m_dpi->setSuffix(QStringLiteral(" dpi"));
            m_dpi->setValue(probe.value("dpi").toDouble(96));
            form->addRow(tr("Resolution:"), m_dpi);
        }
        m_scale = new QSpinBox;
        m_scale->setObjectName(QStringLiteral("underlayScale"));
        m_scale->setRange(1, 100000);
        m_scale->setPrefix(QStringLiteral("1:"));
        m_scale->setValue(100);
        form->addRow(tr("Drawing scale:"), m_scale);
        form->addRow(QString(), new QLabel(tr("Not sure? Place it, then calibrate it by two points of a known distance.")));
    }
    m_x = lengthBox(0);
    m_y = lengthBox(0);
    m_rotation = angleBox(0);
    form->addRow(tr("Place at X:"), m_x);
    form->addRow(tr("Place at Y:"), m_y);
    form->addRow(tr("Rotation:"), m_rotation);
    m_layer = new QComboBox;
    m_layer->setObjectName(QStringLiteral("underlayLayer"));
    m_layer->setEditable(true);
    QStringList names = layers;
    if (!names.contains(QStringLiteral("Underlays")))
        names.prepend(QStringLiteral("Underlays"));
    m_layer->addItems(names);
    m_layer->setCurrentText(QStringLiteral("Underlays"));
    form->addRow(tr("Layer:"), m_layer);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    buttons->button(QDialogButtonBox::Ok)->setText(tr("Place"));
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    auto* layout = new QVBoxLayout(this);
    layout->addLayout(form);
    layout->addWidget(buttons);
}

QJsonObject PlaceUnderlayDialog::options() const
{
    QJsonObject o{{"x", m_x->value()}, {"y", m_y->value()}, {"rotation", m_rotation->value()},
        {"layer", m_layer->currentText().trimmed().isEmpty() ? QStringLiteral("Underlays") : m_layer->currentText().trimmed()}};
    if (m_unit)
        o.insert("units", m_unit->currentData().toDouble());
    if (m_page)
        o.insert("page", m_page->value() - 1);
    if (m_scale)
        o.insert("scale", rasterScale(m_kind, m_scale->value(), m_dpi ? m_dpi->value() : 0.0));
    return o;
}

// ---------------------------------------------------------------- the list

UnderlaysDialog::UnderlaysDialog(Bridge bridge, const QHash<QString, QString>& levelNames, const QStringList& layers, QWidget* parent)
    : QDialog(parent)
    , m_bridge(std::move(bridge))
    , m_levelNames(levelNames)
{
    setWindowTitle(tr("Underlays"));
    m_list = new QListWidget;
    m_list->setObjectName(QStringLiteral("underlayList"));
    m_list->setMinimumWidth(220);
    m_editor = new QWidget;
    auto* form = new QFormLayout(m_editor);
    m_info = new QLabel;
    m_info->setWordWrap(true);
    form->addRow(m_info);
    m_visible = new QCheckBox(tr("Shown"));
    m_locked = new QCheckBox(tr("Locked"));
    m_show3d = new QCheckBox(tr("Also in 3D"));
    auto* states = new QHBoxLayout;
    states->addWidget(m_visible);
    states->addWidget(m_locked);
    states->addWidget(m_show3d);
    form->addRow(states);
    m_opacity = new QSlider(Qt::Horizontal);
    m_opacity->setObjectName(QStringLiteral("underlayOpacity"));
    m_opacity->setRange(5, 100);
    m_opacity->setTracking(false); // one change when released, not one per step
    form->addRow(tr("Opacity:"), m_opacity);
    m_grey = new QCheckBox(tr("Greyscale"));
    m_tint = new QPushButton;
    auto* colour = new QHBoxLayout;
    colour->addWidget(m_grey);
    colour->addWidget(new QLabel(tr("Tint:")));
    colour->addWidget(m_tint);
    form->addRow(colour);
    m_layer = new QComboBox;
    m_layer->setEditable(true);
    QStringList names = layers;
    if (!names.contains(QStringLiteral("Underlays")))
        names.prepend(QStringLiteral("Underlays"));
    m_layer->addItems(names);
    form->addRow(tr("Layer:"), m_layer);
    m_x = lengthBox(0);
    m_y = lengthBox(0);
    m_rotation = angleBox(0);
    m_rotation->setObjectName(QStringLiteral("underlayRotation"));
    m_scale = new QDoubleSpinBox;
    m_scale->setRange(1e-9, 1e6);
    m_scale->setDecimals(9);
    m_scale->setToolTip(tr("Metres per drawing unit (DXF unit, PDF point or image pixel)"));
    m_page = new QSpinBox;
    m_page->setRange(1, 9999);
    form->addRow(tr("X:"), m_x);
    form->addRow(tr("Y:"), m_y);
    form->addRow(tr("Rotation:"), m_rotation);
    form->addRow(tr("Scale (m per unit):"), m_scale);
    form->addRow(tr("Page:"), m_page);
    auto* calibrate = new QPushButton(tr("&Calibrate..."));
    calibrate->setToolTip(tr("Click two points of the underlay and type their real distance"));
    auto* move = new QPushButton(tr("&Move..."));
    move->setToolTip(tr("Click a point of the underlay, then where it goes"));
    auto* remove = new QPushButton(tr("&Remove"));
    auto* place = new QPushButton(tr("&Place underlay..."));
    auto* actions = new QHBoxLayout;
    actions->addWidget(calibrate);
    actions->addWidget(move);
    actions->addWidget(remove);
    form->addRow(actions);
    auto* close = new QDialogButtonBox(QDialogButtonBox::Close);
    close->addButton(place, QDialogButtonBox::ActionRole);
    connect(close, &QDialogButtonBox::rejected, this, &QDialog::reject);
    auto* top = new QHBoxLayout;
    top->addWidget(m_list);
    top->addWidget(m_editor, 1);
    auto* layout = new QVBoxLayout(this);
    layout->addLayout(top);
    layout->addWidget(close);

    connect(m_list, &QListWidget::currentRowChanged, this, [this] { reload(currentId()); });
    connect(m_visible, &QCheckBox::toggled, this, [this](bool on) { apply({{"visible", on}}); });
    connect(m_locked, &QCheckBox::toggled, this, [this](bool on) { apply({{"locked", on}}); });
    connect(m_show3d, &QCheckBox::toggled, this, [this](bool on) { apply({{"show_3d", on}}); });
    connect(m_grey, &QCheckBox::toggled, this, [this](bool on) { apply({{"greyscale", on}}); });
    connect(m_opacity, &QSlider::valueChanged, this, [this](int v) { apply({{"opacity", v / 100.0}}); });
    connect(m_tint, &QPushButton::clicked, this, [this] {
        const QColor now(m_current.value("tint").toString());
        QColorDialog dialog(now.isValid() ? now : QColor(40, 90, 200), this);
        dialog.setWindowTitle(tr("Underlay tint"));
        auto* none = new QPushButton(tr("No tint"));
        bool cleared = false;
        connect(none, &QPushButton::clicked, &dialog, [&] {
            cleared = true;
            dialog.reject();
        });
        if (auto* box = dialog.findChild<QDialogButtonBox*>())
            box->addButton(none, QDialogButtonBox::ResetRole);
        if (dialog.exec() == QDialog::Accepted)
            apply({{"tint", dialog.selectedColor().name()}});
        else if (cleared)
            apply({{"tint", QString()}});
    });
    connect(m_layer, &QComboBox::currentTextChanged, this, [this](const QString& t) {
        if (!t.trimmed().isEmpty())
            apply({{"layer", t.trimmed()}});
    });
    auto onEdit = [this](QDoubleSpinBox* box, const char* key) {
        connect(box, &QDoubleSpinBox::editingFinished, this, [this, box, key] { apply({{QLatin1String(key), box->value()}}); });
    };
    onEdit(m_x, "x");
    onEdit(m_y, "y");
    onEdit(m_rotation, "rotation");
    onEdit(m_scale, "scale");
    connect(m_page, &QSpinBox::editingFinished, this, [this] { apply({{"page", m_page->value() - 1}}); });
    connect(calibrate, &QPushButton::clicked, this, [this] {
        if (!currentId().isEmpty())
            emit calibrateRequested(currentId());
    });
    connect(move, &QPushButton::clicked, this, [this] {
        if (!currentId().isEmpty())
            emit moveRequested(currentId());
    });
    connect(remove, &QPushButton::clicked, this, [this] {
        const QString id = currentId();
        if (id.isEmpty())
            return;
        call(m_bridge, "remove_underlay", {id});
        reload();
        emit changed();
    });
    connect(place, &QPushButton::clicked, this, &UnderlaysDialog::placeRequested);
    reload();
}

QString UnderlaysDialog::currentId() const
{
    const QListWidgetItem* item = m_list->currentItem();
    return item ? item->data(Qt::UserRole).toString() : QString();
}

void UnderlaysDialog::selectId(const QString& id)
{
    for (int i = 0; i < m_list->count(); ++i)
        if (m_list->item(i)->data(Qt::UserRole).toString() == id)
            m_list->setCurrentRow(i);
}

void UnderlaysDialog::reload(const QString& select)
{
    const QJsonArray all = call(m_bridge, "underlays").value("underlays").toArray();
    {
        const QSignalBlocker block(m_list);
        m_list->clear();
        for (const auto& v : all) {
            const QJsonObject o = v.toObject();
            auto* item = new QListWidgetItem(QStringLiteral("%1 — %2").arg(o.value("name").toString(),
                m_levelNames.value(o.value("storey").toString(), tr("no level"))));
            item->setData(Qt::UserRole, o.value("id").toString());
            if (o.value("missing").toBool())
                item->setForeground(Qt::red);
            m_list->addItem(item);
        }
        int row = m_list->count() ? 0 : -1;
        for (int i = 0; i < m_list->count(); ++i)
            if (m_list->item(i)->data(Qt::UserRole).toString() == select)
                row = i;
        m_list->setCurrentRow(row);
    }
    m_editor->setEnabled(m_list->currentRow() >= 0);
    for (const auto& v : all)
        if (v.toObject().value("id").toString() == currentId()) {
            m_current = v.toObject();
            fill(Underlay::fromJson(m_current), m_current);
        }
}

void UnderlaysDialog::fill(const Underlay& u, const QJsonObject& raw)
{
    m_filling = true;
    const QSignalBlocker b1(m_visible), b2(m_locked), b3(m_show3d), b4(m_grey), b5(m_opacity), b6(m_layer);
    const QSignalBlocker b7(m_x), b8(m_y), b9(m_rotation), b10(m_scale), b11(m_page);
    QString info = u.kind == QLatin1String("dxf") ? tr("DXF drawing") : u.kind == QLatin1String("pdf") ? tr("PDF page") : tr("Image");
    if (u.missing)
        info += QStringLiteral(" — ") + tr("the file is missing from the project");
    m_info->setText(QStringLiteral("<b>%1</b><br>%2").arg(u.name.toHtmlEscaped(), info));
    m_visible->setChecked(u.visible);
    m_locked->setChecked(u.locked);
    m_show3d->setChecked(u.show3d);
    m_grey->setChecked(u.greyscale);
    m_opacity->setValue(int(std::lround(u.opacity * 100)));
    m_tint->setText(u.tint.isEmpty() ? tr("None") : u.tint);
    m_layer->setCurrentText(u.layer);
    m_x->setValue(u.placement.at.x());
    m_y->setValue(u.placement.at.y());
    m_rotation->setValue(u.placement.rotation);
    m_scale->setValue(u.placement.scale);
    m_page->setEnabled(u.kind == QLatin1String("pdf"));
    m_page->setValue(raw.value("page").toInt() + 1);
    m_filling = false;
}

void UnderlaysDialog::apply(const QJsonObject& changes)
{
    const QString id = currentId();
    if (m_filling || id.isEmpty())
        return;
    const QJsonObject r = call(m_bridge, "set_underlay", {id, QString::fromUtf8(QJsonDocument(changes).toJson(QJsonDocument::Compact))});
    if (!r.value("ok").toBool()) {
        m_info->setText(r.value("error").toString());
        return;
    }
    m_current = r.value("underlay").toObject();
    fill(Underlay::fromJson(m_current), m_current);
    emit changed();
}

// ---------------------------------------------------------------- picking two points

void UnderlayPicker::start(const QString& id, Mode mode)
{
    m_id = id;
    m_mode = mode;
    m_points.clear();
}

void UnderlayPicker::cancel()
{
    m_id.clear();
    m_points.clear();
}

Snap UnderlayPicker::move(QPointF p, double tolerance, bool ortho)
{
    const Snap s = m_points.isEmpty() ? m_snapper.snap(p, tolerance) : m_snapper.snap(p, tolerance, &m_points.first(), ortho);
    m_hover = s.point;
    return s;
}

bool UnderlayPicker::click(QPointF p, double tolerance, bool ortho)
{
    if (!isActive() || m_points.size() >= 2)
        return m_points.size() >= 2;
    m_points << move(p, tolerance, ortho).point;
    return m_points.size() >= 2;
}

QString UnderlayPicker::hint() const
{
    if (m_mode == Calibrate)
        return m_points.isEmpty() ? QCoreApplication::translate("UnderlayPicker", "Calibrate: click the first of two points whose real distance you know")
                                  : QCoreApplication::translate("UnderlayPicker", "Calibrate: click the second point (Esc cancels)");
    return m_points.isEmpty() ? QCoreApplication::translate("UnderlayPicker", "Move underlay: click a point to move from")
                              : QCoreApplication::translate("UnderlayPicker", "Move underlay: click where it goes (Esc cancels)");
}

} // namespace kimbim
