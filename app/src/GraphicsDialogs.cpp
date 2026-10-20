// SPDX-License-Identifier: GPL-3.0-or-later
#include "GraphicsDialogs.h"

#include <QColorDialog>
#include <QCoreApplication>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QJsonArray>
#include <QLabel>
#include <QLineEdit>
#include <QLocale>
#include <QPixmap>
#include <QPushButton>
#include <QRegularExpression>
#include <QTableWidget>
#include <QVBoxLayout>

#include <cmath>

#include "PenGrid.h"

namespace kimbim {

namespace {

const QStringList kTables{"pen_sets", "line_types", "element_styles", "visibility_sets", "override_sets",
    "layer_combinations", "purposes", "renovation_filters"};

QIcon swatch(const QColor& color)
{
    QPixmap p(12, 12);
    p.fill(color);
    return QIcon(p);
}

// Asks for a name (interactive use; tests call the helpers directly).
QString askName(QWidget* parent, const QString& title, const QString& current = {})
{
    bool ok = false;
    const QString name = QInputDialog::getText(parent, title, QObject::tr("Name:"), QLineEdit::Normal, current, &ok);
    return ok ? name.trimmed() : QString();
}

} // namespace

QString kindLabel(const QString& kind)
{
    static const QHash<QString, const char*> labels{
        {"walls", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Walls")},
        {"columns", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Columns")},
        {"beams", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Beams")},
        {"slabs", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Slabs")},
        {"roofs", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Roofs")},
        {"stairs", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Stairs and ramps")},
        {"railings", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Railings")},
        {"doors", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Doors")},
        {"windows", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Windows")},
        {"coverings", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Coverings")},
        {"furniture", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Furniture")},
        {"plumbing", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Plumbing and piping")},
        {"hvac", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "HVAC")},
        {"electrical", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Electrical")},
        {"structure_other", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Other structure (footings, piles, members)")},
        {"rooms", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Rooms")},
        {"annotations", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Annotations")},
        {"grids", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Grids")},
        {"other", QT_TRANSLATE_NOOP("kimbim::GraphicsDialog", "Other elements")},
    };
    const auto it = labels.constFind(kind);
    return it == labels.constEnd() ? kind : QCoreApplication::translate("kimbim::GraphicsDialog", *it);
}

QHash<int, LineStyle> pensOf(const QJsonObject& penSet)
{
    QHash<int, LineStyle> out;
    const QJsonObject pens = penSet.value("pens").toObject();
    for (auto it = pens.constBegin(); it != pens.constEnd(); ++it) {
        const QJsonObject p = it.value().toObject();
        LineStyle s;
        if (QColor(p.value("color").toString()).isValid())
            s.color = QColor(p.value("color").toString());
        s.weight = p.value("weight").toDouble(0.18);
        out.insert(it.key().toInt(), s);
    }
    return out;
}

// ---------------- GraphicsDialog ----------------

GraphicsDialog::GraphicsDialog(const QJsonObject& reply, QWidget* parent)
    : QDialog(parent)
    , m_reply(reply)
    , m_tables(reply.value("tables").toObject())
    , m_layout(new QVBoxLayout(this))
{
}

void GraphicsDialog::finishLayout()
{
    m_buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(m_buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(m_buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    m_layout->addWidget(m_buttons);
}

void GraphicsDialog::setOkEnabled(bool on)
{
    if (m_buttons)
        m_buttons->button(QDialogButtonBox::Ok)->setEnabled(on);
}

bool GraphicsDialog::okEnabled() const
{
    return !m_buttons || m_buttons->button(QDialogButtonBox::Ok)->isEnabled();
}

QJsonObject GraphicsDialog::changes() const
{
    QJsonObject out;
    const QJsonObject original = m_reply.value("tables").toObject();
    for (const QString& key : kTables)
        if (m_tables.value(key) != original.value(key))
            out.insert(key, m_tables.value(key));
    return out;
}

QHash<int, LineStyle> GraphicsDialog::currentPens() const
{
    const QJsonObject purposes = table("purposes");
    const QString set = purposes.value(m_reply.value("purpose").toString()).toObject().value("pen_set").toString();
    const QJsonObject sets = table("pen_sets");
    return pensOf(sets.contains(set) ? sets.value(set).toObject()
                                     : sets.isEmpty() ? QJsonObject() : sets.begin().value().toObject());
}

// ---------------- NamedSetsDialog ----------------

NamedSetsDialog::NamedSetsDialog(const QJsonObject& reply, const QString& key, const QString& reference, QWidget* parent)
    : GraphicsDialog(reply, parent)
    , m_key(key)
    , m_reference(reference)
{
}

void NamedSetsDialog::buildPicker()
{
    auto* row = new QHBoxLayout;
    m_combo = new QComboBox(this);
    m_combo->setObjectName(QStringLiteral("set"));
    row->addWidget(m_combo, 1);
    auto button = [&](const char* name, const QString& text) {
        auto* b = new QPushButton(text, this);
        b->setObjectName(QLatin1String(name));
        row->addWidget(b);
        return b;
    };
    QPushButton* add = button("newSet", tr("New..."));
    QPushButton* copy = button("copySet", tr("Copy..."));
    QPushButton* rename = button("renameSet", tr("Rename..."));
    m_delete = button("deleteSet", tr("Delete"));
    connect(add, &QPushButton::clicked, this, [this] {
        if (const QString n = askName(this, tr("New")); !n.isEmpty())
            newSet(n);
    });
    connect(copy, &QPushButton::clicked, this, [this] {
        if (const QString n = askName(this, tr("Copy"), currentSet() + tr(" (copy)")); !n.isEmpty())
            copySetAs(n);
    });
    connect(rename, &QPushButton::clicked, this, [this] {
        if (const QString n = askName(this, tr("Rename"), currentSet()); !n.isEmpty())
            renameSetTo(n);
    });
    connect(m_delete, &QPushButton::clicked, this, [this] { deleteCurrentSet(); });
    connect(m_combo, &QComboBox::currentTextChanged, this, [this](const QString& name) {
        if (!name.isEmpty())
            showSet(name);
    });
    m_layout->addLayout(row);
}

void NamedSetsDialog::refresh(const QString& select)
{
    const QJsonObject sets = table(m_key);
    QSignalBlocker block(m_combo);
    m_combo->clear();
    m_combo->addItems(sets.keys());
    m_combo->setCurrentText(sets.contains(select) ? select : sets.keys().value(0));
    m_delete->setEnabled(sets.size() > 1);
    if (!m_combo->currentText().isEmpty())
        showSet(m_combo->currentText());
}

void NamedSetsDialog::selectSet(const QString& name)
{
    refresh(name);
}

QString NamedSetsDialog::currentSet() const
{
    return m_combo ? m_combo->currentText() : QString();
}

QJsonObject NamedSetsDialog::currentValue() const
{
    return table(m_key).value(currentSet()).toObject();
}

void NamedSetsDialog::setCurrentValue(const QJsonObject& value)
{
    QJsonObject sets = table(m_key);
    sets.insert(currentSet(), value);
    setTable(m_key, sets);
}

bool NamedSetsDialog::validName(const QString& name) const
{
    return !name.trimmed().isEmpty() && name.size() <= 64 && !table(m_key).contains(name);
}

bool NamedSetsDialog::newSet(const QString& name)
{
    const QJsonObject sets = table(m_key);
    if (!validName(name) || sets.isEmpty())
        return false;
    QJsonObject updated = sets;
    updated.insert(name, sets.begin().value());
    setTable(m_key, updated);
    refresh(name);
    return true;
}

bool NamedSetsDialog::copySetAs(const QString& name)
{
    if (!validName(name) || currentSet().isEmpty())
        return false;
    QJsonObject sets = table(m_key);
    sets.insert(name, sets.value(currentSet()));
    setTable(m_key, sets);
    refresh(name);
    return true;
}

bool NamedSetsDialog::renameSetTo(const QString& name)
{
    const QString old = currentSet();
    if (!validName(name) || old.isEmpty())
        return false;
    QJsonObject sets = table(m_key);
    sets.insert(name, sets.take(old));
    setTable(m_key, sets);
    if (!m_reference.isEmpty()) { // the purposes using it follow
        QJsonObject purposes = table("purposes");
        for (const QString& p : purposes.keys()) {
            QJsonObject purpose = purposes.value(p).toObject();
            if (purpose.value(m_reference).toString() == old) {
                purpose.insert(m_reference, name);
                purposes.insert(p, purpose);
            }
        }
        setTable("purposes", purposes);
    }
    refresh(name);
    return true;
}

bool NamedSetsDialog::deleteCurrentSet()
{
    const QString old = currentSet();
    QJsonObject sets = table(m_key);
    if (old.isEmpty() || sets.size() <= 1)
        return false;
    sets.remove(old);
    setTable(m_key, sets);
    if (!m_reference.isEmpty()) { // the purposes using it take the first remaining set (layers: none)
        QJsonObject purposes = table("purposes");
        for (const QString& p : purposes.keys()) {
            QJsonObject purpose = purposes.value(p).toObject();
            if (purpose.value(m_reference).toString() == old) {
                purpose.insert(m_reference, m_reference == QLatin1String("layers") ? QJsonValue() : QJsonValue(sets.keys().first()));
                purposes.insert(p, purpose);
            }
        }
        setTable("purposes", purposes);
    }
    refresh(sets.keys().first());
    return true;
}

// ---------------- PenSetsDialog ----------------

PenSetsDialog::PenSetsDialog(const QJsonObject& reply, QWidget* parent)
    : NamedSetsDialog(reply, QStringLiteral("pen_sets"), QStringLiteral("pen_set"), parent)
{
    setWindowTitle(tr("Pen sets"));
    auto* body = new QHBoxLayout;
    m_grid = new PenGrid(this);
    m_grid->setObjectName(QStringLiteral("grid"));
    m_grid->setFixedSize(16 * 22, 16 * 22);
    body->addWidget(m_grid);
    auto* form = new QFormLayout;
    m_color = new QPushButton(this);
    m_color->setObjectName(QStringLiteral("penColor"));
    m_weight = new QDoubleSpinBox(this);
    m_weight->setObjectName(QStringLiteral("penWeight"));
    m_weight->setRange(0.05, 5.0);
    m_weight->setSingleStep(0.05);
    m_weight->setDecimals(2);
    m_weight->setSuffix(tr(" mm"));
    m_name = new QLineEdit(this);
    m_name->setObjectName(QStringLiteral("penName"));
    auto* number = new QLabel(this);
    number->setObjectName(QStringLiteral("penNumber"));
    form->addRow(tr("Pen:"), number);
    form->addRow(tr("Colour:"), m_color);
    form->addRow(tr("Weight on paper:"), m_weight);
    form->addRow(tr("Name:"), m_name);
    body->addLayout(form);
    buildPicker();
    m_layout->addLayout(body);
    m_layout->addWidget(new QLabel(tr("Elements use pens by number (Graphics > Element styles), so switching the pen set restyles everything."), this));
    finishLayout();
    connect(m_grid, &PenGrid::penClicked, this, &PenSetsDialog::selectPen);
    connect(m_color, &QPushButton::clicked, this, [this] {
        const QColor c = QColorDialog::getColor(QColor(pen(m_pen).value("color").toString()), this, tr("Pen colour"));
        if (c.isValid())
            setPenColor(c);
    });
    connect(m_weight, &QDoubleSpinBox::valueChanged, this, [this](double w) {
        if (!m_loading)
            setPenWeight(w);
    });
    connect(m_name, &QLineEdit::textEdited, this, &PenSetsDialog::setPenName);
    selectSet(reply.value("tables").toObject().value("purposes").toObject()
                  .value(reply.value("purpose").toString()).toObject().value("pen_set").toString());
}

QJsonObject PenSetsDialog::pen(int n) const
{
    return currentValue().value("pens").toObject().value(QString::number(n)).toObject();
}

void PenSetsDialog::setPen(int n, const QJsonObject& value)
{
    QJsonObject set = currentValue();
    QJsonObject pens = set.value("pens").toObject();
    pens.insert(QString::number(n), value);
    set.insert("pens", pens);
    setCurrentValue(set);
    m_grid->setPens(pensOf(set));
}

void PenSetsDialog::showSet(const QString&)
{
    const QJsonObject set = currentValue();
    m_grid->setPens(pensOf(set));
    QHash<int, QString> names;
    const QJsonObject pens = set.value("pens").toObject();
    for (auto it = pens.constBegin(); it != pens.constEnd(); ++it)
        names.insert(it.key().toInt(), it.value().toObject().value("name").toString());
    m_grid->setNames(names);
    selectPen(m_pen);
}

void PenSetsDialog::selectPen(int n)
{
    if (n < 1 || n > 255)
        return;
    m_pen = n;
    m_grid->setCurrent(n);
    const QJsonObject p = pen(n);
    m_loading = true;
    findChild<QLabel*>(QStringLiteral("penNumber"))->setText(QString::number(n));
    m_color->setIcon(swatch(QColor(p.value("color").toString("#000000"))));
    m_color->setText(p.value("color").toString("#000000"));
    m_weight->setValue(p.value("weight").toDouble(0.18));
    m_name->setText(p.value("name").toString());
    m_loading = false;
}

void PenSetsDialog::setPenColor(const QColor& color)
{
    QJsonObject p = pen(m_pen);
    p.insert("color", color.name());
    if (!p.contains("weight"))
        p.insert("weight", 0.18);
    setPen(m_pen, p);
    selectPen(m_pen);
}

void PenSetsDialog::setPenWeight(double weight)
{
    QJsonObject p = pen(m_pen);
    p.insert("weight", std::round(weight * 100.0) / 100.0);
    if (!p.contains("color"))
        p.insert("color", "#000000");
    setPen(m_pen, p);
}

void PenSetsDialog::setPenName(const QString& name)
{
    QJsonObject p = pen(m_pen);
    if (name.trimmed().isEmpty())
        p.remove("name");
    else
        p.insert("name", name.trimmed());
    if (!p.contains("color"))
        p.insert("color", "#000000");
    if (!p.contains("weight"))
        p.insert("weight", 0.18);
    setPen(m_pen, p);
}

// ---------------- LineTypesDialog ----------------

LineTypesDialog::LineTypesDialog(const QJsonObject& reply, QWidget* parent)
    : GraphicsDialog(reply, parent)
{
    setWindowTitle(tr("Line types"));
    m_layout->addWidget(new QLabel(tr("Dash and gap lengths in millimetres on paper, e.g. \"3 1.5\". Empty: a solid line."), this));
    m_list = new QTableWidget(0, 2, this);
    m_list->setObjectName(QStringLiteral("lineTypes"));
    m_list->setHorizontalHeaderLabels({tr("Name"), tr("Pattern")});
    m_list->horizontalHeader()->setStretchLastSection(true);
    m_list->verticalHeader()->hide();
    m_layout->addWidget(m_list);
    auto* row = new QHBoxLayout;
    auto* add = new QPushButton(tr("Add"), this);
    add->setObjectName(QStringLiteral("addLine"));
    auto* remove = new QPushButton(tr("Delete"), this);
    remove->setObjectName(QStringLiteral("deleteLine"));
    row->addWidget(add);
    row->addWidget(remove);
    row->addStretch(1);
    m_layout->addLayout(row);
    finishLayout();
    connect(add, &QPushButton::clicked, this, [this] {
        if (const QString n = askName(this, tr("New line type")); !n.isEmpty())
            addLineType(n, QStringLiteral("2 1"));
    });
    connect(remove, &QPushButton::clicked, this, [this] {
        if (m_list->currentRow() >= 0)
            deleteLineType(m_list->item(m_list->currentRow(), 0)->text());
    });
    connect(m_list, &QTableWidget::itemChanged, this, [this](QTableWidgetItem* item) {
        if (m_loading || item->column() != 1)
            return;
        setPattern(m_list->item(item->row(), 0)->text(), item->text());
    });
    fill();
}

std::optional<QJsonArray> LineTypesDialog::parse(const QString& pattern)
{
    QJsonArray out;
    for (const QString& part : pattern.split(QRegularExpression(QStringLiteral("[\\s;]+")), Qt::SkipEmptyParts)) {
        bool ok = false;
        const double v = QLocale().toDouble(part, &ok);
        const double c = ok ? v : part.toDouble(&ok); // "1.5" whatever the locale
        if (!ok || c <= 0)
            return std::nullopt;
        out.append(c);
    }
    if (out.size() % 2 || out.size() > 12)
        return std::nullopt;
    return out;
}

void LineTypesDialog::fill()
{
    m_loading = true;
    const QJsonObject types = table("line_types");
    QStringList names = types.keys();
    names.removeAll(QStringLiteral("Solid"));
    names.prepend(QStringLiteral("Solid"));
    m_list->setRowCount(0);
    for (const QString& name : names) {
        if (!types.contains(name))
            continue;
        const int r = m_list->rowCount();
        m_list->insertRow(r);
        auto* n = new QTableWidgetItem(name);
        n->setFlags(n->flags() & ~Qt::ItemIsEditable);
        m_list->setItem(r, 0, n);
        QStringList parts;
        for (const auto& v : types.value(name).toArray())
            parts << QLocale().toString(v.toDouble());
        auto* p = new QTableWidgetItem(m_bad.value(name, parts.join(QLatin1Char(' '))));
        if (name == QLatin1String("Solid"))
            p->setFlags(p->flags() & ~Qt::ItemIsEditable);
        if (m_bad.contains(name))
            p->setBackground(QColor(255, 200, 200));
        m_list->setItem(r, 1, p);
    }
    m_loading = false;
}

void LineTypesDialog::validate()
{
    setOkEnabled(m_bad.isEmpty());
}

bool LineTypesDialog::setPattern(const QString& name, const QString& pattern)
{
    QJsonObject types = table("line_types");
    if (!types.contains(name))
        return false;
    const auto parsed = parse(pattern);
    if (name == QLatin1String("Solid"))
        return parsed && parsed->isEmpty();
    if (!parsed || parsed->isEmpty()) {
        m_bad.insert(name, pattern);
    } else {
        m_bad.remove(name);
        types.insert(name, *parsed);
        setTable("line_types", types);
    }
    fill();
    validate();
    return !m_bad.contains(name);
}

bool LineTypesDialog::addLineType(const QString& name, const QString& pattern)
{
    QJsonObject types = table("line_types");
    const auto parsed = parse(pattern);
    if (name.trimmed().isEmpty() || types.contains(name) || !parsed || parsed->isEmpty())
        return false;
    types.insert(name.trimmed(), *parsed);
    setTable("line_types", types);
    fill();
    return true;
}

bool LineTypesDialog::deleteLineType(const QString& name)
{
    QJsonObject types = table("line_types");
    if (name == QLatin1String("Solid") || !types.contains(name))
        return false;
    types.remove(name);
    m_bad.remove(name);
    setTable("line_types", types);
    fill();
    validate();
    return true;
}

// ---------------- ElementStylesDialog ----------------

ElementStylesDialog::ElementStylesDialog(const QJsonObject& reply, QWidget* parent)
    : GraphicsDialog(reply, parent)
{
    setWindowTitle(tr("Element styles"));
    for (const auto& k : reply.value("kinds").toArray())
        m_kinds << k.toString();
    m_list = new QTableWidget(int(m_kinds.size()), 6, this);
    m_list->setObjectName(QStringLiteral("elementStyles"));
    m_list->setHorizontalHeaderLabels({tr("Element"), tr("Cut pen"), tr("Cut line"), tr("Projection pen"),
        tr("Projection line"), tr("Cut fill pen")});
    m_list->verticalHeader()->hide();
    m_list->horizontalHeader()->setSectionResizeMode(QHeaderView::ResizeToContents);
    m_layout->addWidget(m_list);
    m_layout->addWidget(new QLabel(tr("Pens are numbers in the current pen set: each purpose can colour them differently."), this));
    finishLayout();
    resize(760, 560);
    fill();
}

void ElementStylesDialog::set(const QString& kind, const QString& part, const QString& field, const QJsonValue& value)
{
    QJsonObject styles = table("element_styles");
    QJsonObject style = styles.value(kind).toObject();
    if (part.isEmpty()) {
        style.insert(field, value);
    } else {
        QJsonObject p = style.value(part).toObject();
        p.insert(field, value);
        style.insert(part, p);
    }
    styles.insert(kind, style);
    setTable("element_styles", styles);
    fill();
}

void ElementStylesDialog::setCutPen(const QString& kind, int pen) { set(kind, QStringLiteral("cut"), QStringLiteral("pen"), pen); }
void ElementStylesDialog::setProjectionPen(const QString& kind, int pen) { set(kind, QStringLiteral("projection"), QStringLiteral("pen"), pen); }
void ElementStylesDialog::setFillPen(const QString& kind, int pen) { set(kind, QString(), QStringLiteral("fill"), pen); }
void ElementStylesDialog::setCutLine(const QString& kind, const QString& line) { set(kind, QStringLiteral("cut"), QStringLiteral("line"), line); }
void ElementStylesDialog::setProjectionLine(const QString& kind, const QString& line) { set(kind, QStringLiteral("projection"), QStringLiteral("line"), line); }

void ElementStylesDialog::fill()
{
    const QJsonObject styles = table("element_styles");
    const QStringList lines = table("line_types").keys();
    const QHash<int, LineStyle> pens = currentPens();
    for (int r = 0; r < m_kinds.size(); ++r) {
        const QString kind = m_kinds[r];
        const QJsonObject st = styles.value(kind).toObject();
        auto* label = new QTableWidgetItem(kindLabel(kind));
        label->setFlags(label->flags() & ~Qt::ItemIsEditable);
        m_list->setItem(r, 0, label);
        auto penButton = [&](int col, int pen, auto setter) {
            auto* b = new QPushButton(QString::number(pen), m_list);
            b->setIcon(swatch(pens.value(pen, LineStyle{}).color));
            connect(b, &QPushButton::clicked, this, [this, b, kind, pen, pens, setter] {
                const int picked = PenGrid::pick(b, pens, {}, pen);
                if (picked > 0) // after this click: the table's buttons are rebuilt
                    QMetaObject::invokeMethod(this, [this, kind, picked, setter] { (this->*setter)(kind, picked); },
                        Qt::QueuedConnection);
            });
            m_list->setCellWidget(r, col, b);
        };
        auto lineCombo = [&](int col, const QString& line, auto setter) {
            auto* c = new QComboBox(m_list);
            c->addItems(lines);
            c->setCurrentText(line);
            connect(c, &QComboBox::currentTextChanged, this, [this, kind, setter](const QString& l) {
                QMetaObject::invokeMethod(this, [this, kind, setter, l] { (this->*setter)(kind, l); }, Qt::QueuedConnection);
            });
            m_list->setCellWidget(r, col, c);
        };
        penButton(1, st.value("cut").toObject().value("pen").toInt(25), &ElementStylesDialog::setCutPen);
        lineCombo(2, st.value("cut").toObject().value("line").toString(QStringLiteral("Solid")), &ElementStylesDialog::setCutLine);
        penButton(3, st.value("projection").toObject().value("pen").toInt(25), &ElementStylesDialog::setProjectionPen);
        lineCombo(4, st.value("projection").toObject().value("line").toString(QStringLiteral("Solid")), &ElementStylesDialog::setProjectionLine);
        penButton(5, st.value("fill").toInt(12), &ElementStylesDialog::setFillPen);
    }
}

} // namespace kimbim
