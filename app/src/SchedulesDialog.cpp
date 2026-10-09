// SPDX-License-Identifier: GPL-3.0-or-later
#include "SchedulesDialog.h"

#include "PythonEngine.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QElapsedTimer>
#include <QEvent>
#include <QFileDialog>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QLocale>
#include <QMessageBox>
#include <QPushButton>
#include <QTableWidget>
#include <QTimer>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>

namespace kimcad {

namespace {

constexpr int GuidsRole = Qt::UserRole;
constexpr int FieldRole = Qt::UserRole + 1;
constexpr int ShownRole = Qt::UserRole + 2; // the scheme editor: a field's text as first shown
constexpr double QuickRefresh = 0.3; // seconds: refresh after every edit only below this

QString compact(const QJsonValue& v)
{
    if (v.isObject())
        return QString::fromUtf8(QJsonDocument(v.toObject()).toJson(QJsonDocument::Compact));
    if (v.isArray())
        return QString::fromUtf8(QJsonDocument(v.toArray()).toJson(QJsonDocument::Compact));
    return QString::fromUtf8(QJsonDocument(QJsonArray{v}).toJson(QJsonDocument::Compact)).mid(1).chopped(1);
}

QString fieldKey(const QJsonObject& f)
{
    if (f.value("source").toString() == QLatin1String("property"))
        return QStringLiteral("property:%1:%2").arg(f.value("pset").toString(), f.value("name").toString());
    return QStringLiteral("%1:%2").arg(f.value("source").toString(), f.value("name").toString());
}

QString unitSuffix(const QString& kind)
{
    if (kind == QLatin1String("length"))
        return QStringLiteral(" (m)");
    if (kind == QLatin1String("area"))
        return QStringLiteral(" (m²)");
    if (kind == QLatin1String("volume"))
        return QStringLiteral(" (m³)");
    return {};
}

} // namespace

QString SchedulesDialog::translatedLabel(const QString& english)
{
    static const QHash<QString, QString> labels = {
        {QStringLiteral("Name"), tr("Name")}, {QStringLiteral("Mark"), tr("Mark")},
        {QStringLiteral("Long name"), tr("Long name")}, {QStringLiteral("Description"), tr("Description")},
        {QStringLiteral("Object type"), tr("Object type")}, {QStringLiteral("Predefined type"), tr("Predefined type")},
        {QStringLiteral("Class"), tr("Class")}, {QStringLiteral("Type"), tr("Type")}, {QStringLiteral("Level"), tr("Level")},
        {QStringLiteral("Length"), tr("Length")}, {QStringLiteral("Height"), tr("Height")}, {QStringLiteral("Width"), tr("Width")},
        {QStringLiteral("Thickness"), tr("Thickness")}, {QStringLiteral("Perimeter"), tr("Perimeter")},
        {QStringLiteral("Area"), tr("Area")}, {QStringLiteral("Gross area"), tr("Gross area")},
        {QStringLiteral("Net area"), tr("Net area")}, {QStringLiteral("Section area"), tr("Section area")},
        {QStringLiteral("Gross side area"), tr("Gross side area")}, {QStringLiteral("Net side area"), tr("Net side area")},
        {QStringLiteral("Opening area"), tr("Opening area")}, {QStringLiteral("Volume"), tr("Volume")},
        {QStringLiteral("Gross volume"), tr("Gross volume")}, {QStringLiteral("Count"), tr("Count")},
        {QStringLiteral("Number"), tr("Number")},
    };
    return labels.value(english, english);
}

QString SchedulesDialog::translatedSchemeName(const QString& english)
{
    static const QHash<QString, QString> names = {
        {QStringLiteral("Doors"), tr("Doors")}, {QStringLiteral("Windows"), tr("Windows")},
        {QStringLiteral("Walls"), tr("Walls")}, {QStringLiteral("Slabs"), tr("Slabs")},
        {QStringLiteral("Columns"), tr("Columns")}, {QStringLiteral("Beams"), tr("Beams")},
        {QStringLiteral("Rooms"), tr("Rooms")},
    };
    return names.value(english, english);
}

SchedulesDialog::SchedulesDialog(QWidget* parent)
    : QDialog(parent)
    , m_scheme(new QComboBox(this))
    , m_merge(new QCheckBox(tr("&Merge identical items"), this))
    , m_table(new QTableWidget(this))
    , m_status(new QLabel(this))
    , m_delete(new QPushButton(tr("&Delete"), this))
{
    setObjectName(QStringLiteral("schedulesDialog"));
    setWindowTitle(tr("Schedules"));
    setWindowFlag(Qt::WindowMaximizeButtonHint);
    setModal(false);
    m_scheme->setObjectName(QStringLiteral("scheduleScheme"));
    m_merge->setObjectName(QStringLiteral("scheduleMerge"));
    m_merge->setToolTip(tr("One row per group of elements that share the scheme's group fields, with their quantities summed"));
    m_table->setObjectName(QStringLiteral("scheduleTable"));
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setSelectionMode(QAbstractItemView::ExtendedSelection);
    m_table->setEditTriggers(QAbstractItemView::DoubleClicked | QAbstractItemView::EditKeyPressed);
    m_table->horizontalHeader()->setStretchLastSection(true);
    m_table->verticalHeader()->setVisible(false);
    m_table->setToolTip(tr("Click rows to select their elements; double-click a name, mark or property to edit it"));
    m_delete->setObjectName(QStringLiteral("scheduleDelete"));

    auto* create = new QPushButton(tr("&New..."), this);
    auto* edit = new QPushButton(tr("&Edit..."), this);
    auto* refreshButton = new QPushButton(tr("&Refresh"), this);
    auto* exportButton = new QPushButton(tr("E&xport..."), this);
    exportButton->setObjectName(QStringLiteral("scheduleExport"));
    auto* top = new QHBoxLayout;
    top->addWidget(new QLabel(tr("Schedule:"), this));
    top->addWidget(m_scheme, 1);
    top->addWidget(m_merge);
    for (QPushButton* b : {create, edit, m_delete, refreshButton, exportButton})
        top->addWidget(b);
    auto* close = new QDialogButtonBox(QDialogButtonBox::Close, this);
    auto* bottom = new QHBoxLayout;
    bottom->addWidget(m_status, 1);
    bottom->addWidget(close);
    auto* layout = new QVBoxLayout(this);
    layout->addLayout(top);
    layout->addWidget(m_table, 1);
    layout->addLayout(bottom);
    resize(900, 480);

    connect(close, &QDialogButtonBox::rejected, this, &QDialog::hide);
    connect(m_scheme, &QComboBox::currentIndexChanged, this, [this] {
        if (!m_filling)
            refresh();
    });
    connect(m_merge, &QCheckBox::toggled, this, [this] { refresh(); });
    connect(refreshButton, &QPushButton::clicked, this, [this] { refresh(); });
    connect(create, &QPushButton::clicked, this, [this] { editScheme(true); });
    connect(edit, &QPushButton::clicked, this, [this] { editScheme(false); });
    connect(m_delete, &QPushButton::clicked, this, &SchedulesDialog::deleteScheme);
    connect(exportButton, &QPushButton::clicked, this, &SchedulesDialog::exportSchedule);
    connect(m_table, &QTableWidget::itemChanged, this, &SchedulesDialog::onItemChanged);
    connect(m_table, &QTableWidget::itemSelectionChanged, this, [this] {
        if (m_filling)
            return;
        QStringList guids;
        QList<int> rows;
        for (const QModelIndex& i : m_table->selectionModel()->selectedRows())
            rows << i.row();
        std::sort(rows.begin(), rows.end());
        for (int r : std::as_const(rows))
            guids << guidsOfRow(r);
        if (!guids.isEmpty())
            emit selectRequested(guids);
    });
    reloadSchemes(QStringLiteral("doors"));
}

QJsonObject SchedulesDialog::bridge(const char* fn, const QStringList& args) const
{
    QString error;
    QJsonObject r = PythonEngine::instance().callJson(fn, args, &error).object();
    if (r.isEmpty() && !error.isEmpty())
        r = QJsonObject{{"ok", false}, {"error", error}};
    return r;
}

void SchedulesDialog::reloadSchemes(const QString& select)
{
    m_schemes = bridge("schedule_schemes").value("schemes").toArray();
    m_filling = true;
    m_scheme->clear();
    for (const QJsonValue& v : std::as_const(m_schemes)) {
        const QJsonObject s = v.toObject();
        const QString name = s.value("builtin").toBool() && !s.value("modified").toBool()
            ? translatedSchemeName(s.value("name").toString()) : s.value("name").toString();
        m_scheme->addItem(name, s.value("id").toString());
    }
    const int i = m_scheme->findData(select);
    m_scheme->setCurrentIndex(i >= 0 ? i : 0);
    m_filling = false;
}

QString SchedulesDialog::currentScheme() const
{
    return m_scheme->currentData().toString();
}

void SchedulesDialog::showScheme(const QString& id)
{
    reloadSchemes(id);
    refresh();
}

void SchedulesDialog::refresh()
{
    m_stale = false;
    if (currentScheme().isEmpty())
        return;
    const QJsonObject s = [this] {
        for (const QJsonValue& v : std::as_const(m_schemes))
            if (v.toObject().value("id").toString() == currentScheme())
                return v.toObject();
        return QJsonObject();
    }();
    m_delete->setText(s.value("builtin").toBool() ? tr("Re&set") : tr("&Delete"));
    m_delete->setEnabled(!s.value("builtin").toBool() || s.value("modified").toBool());
    fill(bridge("schedule", {currentScheme(), m_merge->isChecked() ? QStringLiteral("true") : QStringLiteral("false")}));
}

void SchedulesDialog::modelChanged()
{
    if (!isVisible())
        return;
    if (m_seconds < QuickRefresh)
        QTimer::singleShot(0, this, [this] { refresh(); });
    else {
        m_stale = true;
        m_status->setText(tr("The model changed: Refresh to update the schedule"));
    }
}

bool SchedulesDialog::event(QEvent* e)
{
    if (e->type() == QEvent::WindowActivate && m_stale)
        QTimer::singleShot(0, this, [this] { refresh(); });
    return QDialog::event(e);
}

QStringList SchedulesDialog::guidsOfRow(int row) const
{
    const QTableWidgetItem* item = m_table->item(row, 0);
    return item ? item->data(GuidsRole).toStringList() : QStringList();
}

void SchedulesDialog::fill(const QJsonObject& data)
{
    if (!data.value("ok").toBool()) {
        m_status->setText(tr("Could not make the schedule: %1").arg(data.value("error").toString()));
        return;
    }
    m_filling = true;
    const bool merged = data.value("merged").toBool();
    m_columns = data.value("columns").toArray();
    const QJsonArray rows = data.value("rows").toArray();
    const QJsonArray totals = data.value("totals").toArray();
    QStringList headers;
    QStringList kinds;
    for (const QJsonValue& v : std::as_const(m_columns)) {
        const QJsonObject c = v.toObject();
        headers << translatedLabel(c.value("label").toString()) + unitSuffix(c.value("kind").toString());
        kinds << c.value("kind").toString();
    }
    if (merged) {
        headers << tr("Count");
        kinds << QStringLiteral("count");
    }
    m_table->clear();
    m_table->setColumnCount(int(headers.size()));
    m_table->setHorizontalHeaderLabels(headers);
    m_table->setRowCount(int(rows.size()) + 1);
    m_rows = int(rows.size());
    const QLocale locale;
    auto text = [&](const QJsonValue& v, const QString& kind) -> QString {
        if (v.isNull() || v.isUndefined())
            return {};
        if (v.isBool())
            return v.toBool() ? tr("Yes") : tr("No");
        if (v.isDouble()) {
            if (kind == QLatin1String("count"))
                return locale.toString(qlonglong(std::llround(v.toDouble())));
            if (kind == QLatin1String("text"))
                return locale.toString(v.toDouble(), 'g', 12);
            return locale.toString(v.toDouble(), 'f', kind == QLatin1String("volume") ? 3 : 2);
        }
        return v.toString();
    };
    for (int r = 0; r < rows.size(); ++r) {
        const QJsonObject row = rows[r].toObject();
        const QJsonArray values = row.value("values").toArray();
        const QJsonArray varies = row.value("varies").toArray();
        QStringList guids;
        for (const QJsonValue& g : row.value("guids").toArray())
            guids << g.toString();
        for (int c = 0; c < m_columns.size(); ++c) {
            const QJsonObject col = m_columns[c].toObject();
            const QString kind = col.value("kind").toString();
            auto* item = new QTableWidgetItem(varies[c].toBool() ? tr("(varies)") : text(values[c], kind));
            if (kind != QLatin1String("text"))
                item->setTextAlignment(Qt::AlignRight | Qt::AlignVCenter);
            Qt::ItemFlags flags = Qt::ItemIsSelectable | Qt::ItemIsEnabled;
            if (col.value("editable").toBool())
                flags |= Qt::ItemIsEditable;
            item->setFlags(flags);
            item->setData(FieldRole, col.value("field").toObject());
            if (c == 0)
                item->setData(GuidsRole, guids);
            m_table->setItem(r, c, item);
        }
        if (merged) {
            auto* count = new QTableWidgetItem(locale.toString(row.value("count").toInt()));
            count->setTextAlignment(Qt::AlignRight | Qt::AlignVCenter);
            count->setFlags(Qt::ItemIsSelectable | Qt::ItemIsEnabled);
            m_table->setItem(r, int(m_columns.size()), count);
        }
    }
    // The total row: sums of the summed quantities (and the element count when merged).
    QFont bold = m_table->font();
    bold.setBold(true);
    for (int c = 0; c < headers.size(); ++c) {
        const QJsonValue v = c < totals.size() ? totals[c] : QJsonValue(data.value("count").toInt());
        auto* item = new QTableWidgetItem(c == 0 && (v.isNull() || v.isUndefined()) ? tr("Total") : text(v, kinds[c]));
        item->setFont(bold);
        item->setFlags(Qt::ItemIsEnabled);
        if (kinds[c] != QLatin1String("text"))
            item->setTextAlignment(Qt::AlignRight | Qt::AlignVCenter);
        m_table->setItem(m_rows, c, item);
    }
    m_table->resizeColumnsToContents();
    m_seconds = data.value("seconds").toDouble();
    m_status->setText(tr("%n element(s)", nullptr, data.value("count").toInt())
        + (merged ? QStringLiteral(" · ") + tr("%n row(s)", nullptr, m_rows) : QString()));
    m_filling = false;
}

void SchedulesDialog::onItemChanged(QTableWidgetItem* item)
{
    if (m_filling || !item || item->row() >= m_rows)
        return;
    const QJsonObject field = item->data(FieldRole).toJsonObject();
    const QStringList guids = guidsOfRow(item->row());
    if (field.isEmpty() || guids.isEmpty())
        return;
    const QJsonObject r = bridge("set_schedule_value",
        {compact(QJsonArray::fromStringList(guids)), compact(field), compact(QJsonValue(item->text()))});
    if (!r.value("ok").toBool())
        QMessageBox::warning(this, tr("Could not change it"), r.value("error").toString());
    emit edited(r);
    const int row = item->row();
    QTimer::singleShot(0, this, [this, row] {
        refresh();
        if (row < m_rows) {
            m_filling = true; // keep the row selected without re-selecting its elements
            m_table->selectRow(row);
            m_filling = false;
        }
    });
}

void SchedulesDialog::editScheme(bool create)
{
    QJsonObject s;
    if (create) {
        s = QJsonObject{{"name", tr("New schedule")}, {"classes", QJsonArray{QStringLiteral("IfcWall")}},
            {"fields", QJsonArray{QJsonObject{{"source", "attribute"}, {"name", "Name"}},
                           QJsonObject{{"source", "info"}, {"name", "type"}},
                           QJsonObject{{"source", "quantity"}, {"name", "count"}}}},
            {"group_by", QJsonArray{QStringLiteral("info:type")}}};
    } else {
        for (const QJsonValue& v : std::as_const(m_schemes))
            if (v.toObject().value("id").toString() == currentScheme())
                s = v.toObject();
        if (s.value("builtin").toBool() && !s.value("modified").toBool())
            s["name"] = translatedSchemeName(s.value("name").toString());
    }
    ScheduleSchemeDialog dialog(s, this);
    if (dialog.exec() != QDialog::Accepted)
        return;
    QJsonObject changed = dialog.scheme();
    if (!create)
        changed["id"] = currentScheme();
    const QJsonObject r = bridge("save_schedule_scheme", {compact(changed)});
    if (!r.value("ok").toBool()) {
        QMessageBox::warning(this, tr("Could not save the schedule"), r.value("error").toString());
        return;
    }
    emit edited(QJsonObject{{"ok", true}}); // the project settings changed: unsaved work
    showScheme(r.value("id").toString());
}

void SchedulesDialog::deleteScheme()
{
    const QString id = currentScheme();
    const QJsonObject r = bridge("delete_schedule_scheme", {id});
    if (!r.value("ok").toBool())
        return;
    emit edited(QJsonObject{{"ok", true}});
    showScheme(id); // a built-in one comes back as it was; a custom one is gone
}

void SchedulesDialog::exportSchedule()
{
    QString filter;
    const QString path = QFileDialog::getSaveFileName(this, tr("Export schedule"), m_scheme->currentText() + QStringLiteral(".xlsx"),
        tr("Excel workbooks (*.xlsx)") + QStringLiteral(";;") + tr("CSV files (*.csv)"), &filter);
    if (path.isEmpty())
        return;
    const QJsonObject r = bridge("export_schedule",
        {currentScheme(), m_merge->isChecked() ? QStringLiteral("true") : QStringLiteral("false"), path});
    m_status->setText(r.value("ok").toBool() ? tr("Schedule saved to %1").arg(path)
                                             : tr("Could not export it: %1").arg(r.value("error").toString()));
}

// ---------------------------------------------------------------- the scheme editor

ScheduleSchemeDialog::ScheduleSchemeDialog(const QJsonObject& scheme, QWidget* parent)
    : QDialog(parent)
    , m_scheme(scheme)
    , m_name(new QLineEdit(scheme.value("name").toString(), this))
    , m_classes(new QListWidget(this))
    , m_available(new QListWidget(this))
    , m_fields(new QListWidget(this))
{
    setObjectName(QStringLiteral("scheduleSchemeDialog"));
    setWindowTitle(tr("Schedule scheme"));
    QStringList chosen;
    for (const QJsonValue& c : scheme.value("classes").toArray())
        chosen << c.toString();
    // The model's classes (with counts) plus the scheme's own, so a class not in the model stays.
    QStringList names;
    for (const QJsonValue& v : bridge("schedule_classes").value("classes").toArray()) {
        const QJsonObject c = v.toObject();
        auto* item = new QListWidgetItem(QStringLiteral("%1 (%2)").arg(c.value("name").toString()).arg(c.value("count").toInt()), m_classes);
        item->setData(Qt::UserRole, c.value("name").toString());
        names << c.value("name").toString();
    }
    for (const QString& c : std::as_const(chosen))
        if (!names.contains(c))
            (new QListWidgetItem(c, m_classes))->setData(Qt::UserRole, c);
    for (int i = 0; i < m_classes->count(); ++i) {
        QListWidgetItem* item = m_classes->item(i);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable);
        item->setCheckState(chosen.contains(item->data(Qt::UserRole).toString()) ? Qt::Checked : Qt::Unchecked);
    }
    QStringList group;
    for (const QJsonValue& g : scheme.value("group_by").toArray())
        group << g.toString();
    const QJsonObject defaults = bridge("schedule_schemes").value("labels").toObject(); // field key -> English label
    for (const QJsonValue& v : scheme.value("fields").toArray()) {
        const QJsonObject f = v.toObject();
        const QString label = f.value("label").toString();
        const QString text = !label.isEmpty() ? label
            : SchedulesDialog::translatedLabel(defaults.value(fieldKey(f)).toString(f.value("name").toString()));
        auto* item = new QListWidgetItem(text, m_fields);
        item->setData(Qt::UserRole, f);
        item->setData(ShownRole, text);
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable | Qt::ItemIsEditable);
        item->setCheckState(group.contains(fieldKey(f)) ? Qt::Checked : Qt::Unchecked);
        item->setToolTip(fieldKey(f));
    }
    m_fields->setToolTip(tr("Fields in column order. Ticked fields are what identical items share when merging; "
                            "double-click a field to rename its column"));
    m_available->setToolTip(tr("Double-click a field to add it"));

    auto* add = new QPushButton(tr("Add →"), this);
    auto* remove = new QPushButton(tr("Remove"), this);
    auto* up = new QPushButton(tr("Up"), this);
    auto* down = new QPushButton(tr("Down"), this);
    auto* middle = new QVBoxLayout;
    middle->addStretch();
    for (QPushButton* b : {add, remove, up, down})
        middle->addWidget(b);
    middle->addStretch();
    auto* lists = new QHBoxLayout;
    auto* left = new QVBoxLayout;
    left->addWidget(new QLabel(tr("Classes:"), this));
    left->addWidget(m_classes);
    auto* centre = new QVBoxLayout;
    centre->addWidget(new QLabel(tr("Available fields:"), this));
    centre->addWidget(m_available);
    auto* right = new QVBoxLayout;
    right->addWidget(new QLabel(tr("Schedule fields:"), this));
    right->addWidget(m_fields);
    lists->addLayout(left, 1);
    lists->addLayout(centre, 2);
    lists->addLayout(middle);
    lists->addLayout(right, 2);
    auto* form = new QFormLayout;
    form->addRow(tr("Name:"), m_name);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    auto* layout = new QVBoxLayout(this);
    layout->addLayout(form);
    layout->addLayout(lists, 1);
    layout->addWidget(buttons);
    resize(860, 460);

    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    connect(m_classes, &QListWidget::itemChanged, this, [this] { reloadFields(); });
    connect(add, &QPushButton::clicked, this, &ScheduleSchemeDialog::addField);
    connect(m_available, &QListWidget::itemDoubleClicked, this, &ScheduleSchemeDialog::addField);
    connect(remove, &QPushButton::clicked, this, [this] { delete m_fields->currentItem(); });
    auto move = [this](int by) {
        const int row = m_fields->currentRow();
        if (row < 0 || row + by < 0 || row + by >= m_fields->count())
            return;
        QListWidgetItem* item = m_fields->takeItem(row);
        m_fields->insertItem(row + by, item);
        m_fields->setCurrentRow(row + by);
    };
    connect(up, &QPushButton::clicked, this, [move] { move(-1); });
    connect(down, &QPushButton::clicked, this, [move] { move(1); });
    reloadFields();
}

QJsonObject ScheduleSchemeDialog::bridge(const char* fn, const QStringList& args) const
{
    QString error;
    return PythonEngine::instance().callJson(fn, args, &error).object();
}

void ScheduleSchemeDialog::reloadFields()
{
    QJsonArray classes;
    for (int i = 0; i < m_classes->count(); ++i)
        if (m_classes->item(i)->checkState() == Qt::Checked)
            classes << m_classes->item(i)->data(Qt::UserRole).toString();
    m_available->clear();
    for (const QJsonValue& v : bridge("schedule_fields", {QString::fromUtf8(QJsonDocument(classes).toJson(QJsonDocument::Compact))})
             .value("fields").toArray()) {
        const QJsonObject f = v.toObject();
        const QString source = f.value("source").toString();
        const QString text = source == QLatin1String("property")
            ? QStringLiteral("%1 · %2").arg(f.value("pset").toString(), f.value("name").toString())
            : SchedulesDialog::translatedLabel(f.value("label").toString());
        auto* item = new QListWidgetItem(text, m_available);
        QJsonObject plain{{"source", source}, {"name", f.value("name")}};
        if (f.contains("pset"))
            plain["pset"] = f.value("pset");
        item->setData(Qt::UserRole, plain);
        item->setToolTip(f.value("key").toString());
    }
}

void ScheduleSchemeDialog::addField()
{
    for (QListWidgetItem* a : m_available->selectedItems()) {
        auto* item = new QListWidgetItem(a->text(), m_fields);
        item->setData(Qt::UserRole, a->data(Qt::UserRole));
        item->setData(ShownRole, a->text());
        item->setFlags(item->flags() | Qt::ItemIsUserCheckable | Qt::ItemIsEditable);
        item->setCheckState(Qt::Unchecked);
        item->setToolTip(a->toolTip());
    }
}

QJsonObject ScheduleSchemeDialog::scheme() const
{
    QJsonObject s;
    s["name"] = m_name->text().trimmed();
    QJsonArray classes;
    for (int i = 0; i < m_classes->count(); ++i)
        if (m_classes->item(i)->checkState() == Qt::Checked)
            classes << m_classes->item(i)->data(Qt::UserRole).toString();
    s["classes"] = classes;
    QJsonArray fields;
    QJsonArray group;
    for (int i = 0; i < m_fields->count(); ++i) {
        const QListWidgetItem* item = m_fields->item(i);
        QJsonObject f = item->data(Qt::UserRole).toJsonObject();
        // A renamed column keeps its new label; one left as shown keeps the built-in (translated) label.
        if (item->text() != item->data(ShownRole).toString() && !item->text().trimmed().isEmpty())
            f["label"] = item->text().trimmed();
        fields << f;
        if (item->checkState() == Qt::Checked)
            group << fieldKey(f);
    }
    s["fields"] = fields;
    s["group_by"] = group;
    return s;
}

} // namespace kimcad
