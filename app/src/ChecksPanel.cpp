// SPDX-License-Identifier: GPL-3.0-or-later
#include "ChecksPanel.h"

#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPushButton>
#include <QSet>
#include <QStyle>
#include <QToolButton>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {

constexpr int GuidsRole = Qt::UserRole + 1; // QStringList: the elements an issue (or group) is about
constexpr int KindRole = Qt::UserRole + 2;  // "check", "group" or "issue"

QIcon severityIcon(const QString& severity)
{
    QStyle* s = QApplication::style();
    if (severity == QLatin1String("error") || severity == QLatin1String("fail"))
        return s->standardIcon(QStyle::SP_MessageBoxCritical);
    if (severity == QLatin1String("warning"))
        return s->standardIcon(QStyle::SP_MessageBoxWarning);
    if (severity == QLatin1String("pass"))
        return s->standardIcon(QStyle::SP_DialogApplyButton);
    return s->standardIcon(QStyle::SP_MessageBoxInformation);
}

QStringList strings(const QJsonValue& v)
{
    QStringList out;
    for (const auto& x : v.toArray())
        out << x.toString();
    return out;
}

} // namespace

ChecksPanel::ChecksPanel(QWidget* parent)
    : QWidget(parent)
    , m_schema(new QCheckBox(tr("Schema validation"), this))
    , m_rules(new QCheckBox(tr("EXPRESS rules"), this))
    , m_ids(new QCheckBox(tr("IDS"), this))
    , m_clash(new QCheckBox(tr("Clash detection"), this))
    , m_model(new QCheckBox(tr("Model checks"), this))
    , m_idsList(new QListWidget(this))
    , m_clashList(new QListWidget(this))
    , m_results(new QTreeWidget(this))
    , m_summary(new QLabel(this))
{
    setObjectName(QStringLiteral("checksPanel"));
    auto button = [this](const QString& text, const QString& tip, const char* name) {
        auto* b = new QToolButton(this); // compact: the panel is narrow
        b->setText(text);
        b->setToolTip(tip);
        b->setObjectName(QLatin1String(name));
        return b;
    };
    m_schema->setObjectName(QStringLiteral("checkSchema"));
    m_rules->setObjectName(QStringLiteral("checkRules"));
    m_ids->setObjectName(QStringLiteral("checkIds"));
    m_clash->setObjectName(QStringLiteral("checkClash"));
    m_model->setObjectName(QStringLiteral("checkModel"));
    m_schema->setToolTip(tr("The IFC schema: attribute types, counts and inverses (ifcopenshell.validate)"));
    m_rules->setToolTip(tr("Also the schema's WHERE rules and functions; slower on large models"));
    m_ids->setToolTip(tr("Information requirements from the project's IDS files (IfcTester)"));
    m_clash->setToolTip(tr("Hard clashes and clearances between the project's clash sets"));
    m_model->setToolTip(tr("Duplicates, rooms without a number or name, zero-length walls, elements not on a level, "
                           "doors and windows without a host"));
    for (QCheckBox* c : {m_schema, m_rules, m_ids, m_clash, m_model})
        c->setChecked(true);
    connect(m_schema, &QCheckBox::toggled, m_rules, &QCheckBox::setEnabled);

    auto* run = new QPushButton(tr("Run checks"), this);
    run->setObjectName(QStringLiteral("runChecks"));
    run->setDefault(true);
    connect(run, &QPushButton::clicked, this, &ChecksPanel::run);

    auto* which = new QGroupBox(tr("Checks"), this);
    auto* whichLayout = new QVBoxLayout(which);
    auto* schemaRow = new QHBoxLayout;
    schemaRow->addWidget(m_schema);
    schemaRow->addWidget(m_rules);
    schemaRow->addStretch(1);
    whichLayout->addLayout(schemaRow);
    auto* otherRow = new QHBoxLayout;
    otherRow->addWidget(m_model);
    otherRow->addWidget(m_ids);
    otherRow->addWidget(m_clash);
    otherRow->addStretch(1);
    whichLayout->addLayout(otherRow);
    whichLayout->addWidget(run);

    // IDS files: kept in the project settings (their XML, so they are versioned).
    m_idsList->setObjectName(QStringLiteral("idsFiles"));
    m_idsList->setMaximumHeight(64);
    QToolButton* addIds = button(tr("Add..."), tr("Add an .ids file to the project"), "addIds");
    QToolButton* removeIds = button(tr("Remove"), tr("Remove the selected IDS file from the project"), "removeIds");
    QToolButton* report = button(tr("Report..."), tr("Save the last IDS results as IfcTester's HTML or JSON report"), "idsReport");
    connect(addIds, &QToolButton::clicked, this, &ChecksPanel::addIdsRequested);
    connect(removeIds, &QToolButton::clicked, this, [this] {
        if (QListWidgetItem* i = m_idsList->currentItem())
            emit removeIdsRequested(i->text());
    });
    connect(report, &QToolButton::clicked, this, &ChecksPanel::exportReportRequested);
    auto* ids = new QGroupBox(tr("IDS files"), this);
    auto* idsLayout = new QVBoxLayout(ids);
    idsLayout->addWidget(m_idsList);
    auto* idsButtons = new QHBoxLayout;
    idsButtons->addWidget(addIds);
    idsButtons->addWidget(removeIds);
    idsButtons->addStretch(1);
    idsButtons->addWidget(report);
    idsLayout->addLayout(idsButtons);

    // Clash sets.
    m_clashList->setObjectName(QStringLiteral("clashSets"));
    m_clashList->setMaximumHeight(64);
    QToolButton* newSet = button(tr("New..."), tr("A new clash set: two groups of elements and a tolerance"), "newClashSet");
    QToolButton* editSet = button(tr("Edit..."), tr("Edit the selected clash set"), "editClashSet");
    QToolButton* deleteSet = button(tr("Delete"), tr("Delete the selected clash set"), "deleteClashSet");
    connect(newSet, &QToolButton::clicked, this, [this] { editClashSet(QString()); });
    connect(editSet, &QToolButton::clicked, this, [this] {
        if (QListWidgetItem* i = m_clashList->currentItem())
            editClashSet(i->data(Qt::UserRole).toString());
    });
    connect(m_clashList, &QListWidget::itemDoubleClicked, this,
        [this](QListWidgetItem* i) { editClashSet(i->data(Qt::UserRole).toString()); });
    connect(deleteSet, &QToolButton::clicked, this, [this] {
        if (QListWidgetItem* i = m_clashList->currentItem())
            emit deleteClashSetRequested(i->data(Qt::UserRole).toString());
    });
    auto* clash = new QGroupBox(tr("Clash sets"), this);
    auto* clashLayout = new QVBoxLayout(clash);
    clashLayout->addWidget(m_clashList);
    auto* clashButtons = new QHBoxLayout;
    clashButtons->addWidget(newSet);
    clashButtons->addWidget(editSet);
    clashButtons->addWidget(deleteSet);
    clashButtons->addStretch(1);
    clashLayout->addLayout(clashButtons);

    // Results.
    m_results->setObjectName(QStringLiteral("checkResults"));
    m_results->setColumnCount(2);
    m_results->setHeaderLabels({tr("Issue"), tr("Elements")});
    m_results->header()->setStretchLastSection(false);
    m_results->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_results->header()->setSectionResizeMode(1, QHeaderView::Interactive);
    m_results->header()->resizeSection(1, 110);
    m_results->setUniformRowHeights(true);
    m_results->setWordWrap(false);
    m_results->setTextElideMode(Qt::ElideRight);
    connect(m_results, &QTreeWidget::itemClicked, this, [this](QTreeWidgetItem* item) {
        const QStringList guids = item->data(0, GuidsRole).toStringList();
        if (!guids.isEmpty())
            emit issueActivated(guids);
    });
    m_summary->setObjectName(QStringLiteral("checkSummary"));
    m_summary->setWordWrap(true);
    m_summary->setText(tr("Pick the checks and press Run checks"));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(4, 4, 4, 4);
    layout->addWidget(which);
    layout->addWidget(ids);
    layout->addWidget(clash);
    layout->addWidget(m_summary);
    layout->addWidget(m_results, 1);
}

QStringList ChecksPanel::checkedChecks() const
{
    QStringList out;
    if (m_schema->isChecked())
        out << QStringLiteral("schema");
    if (m_ids->isChecked())
        out << QStringLiteral("ids");
    if (m_clash->isChecked())
        out << QStringLiteral("clash");
    if (m_model->isChecked())
        out << QStringLiteral("model");
    return out;
}

void ChecksPanel::setChecked(const QString& check, bool on)
{
    QCheckBox* box = check == QLatin1String("schema") ? m_schema
        : check == QLatin1String("ids")              ? m_ids
        : check == QLatin1String("clash")            ? m_clash
        : check == QLatin1String("model")            ? m_model
        : check == QLatin1String("rules")            ? m_rules
                                                     : nullptr;
    if (box)
        box->setChecked(on);
}

QJsonObject ChecksPanel::options() const
{
    return {{"express_rules", m_rules->isChecked()}};
}

void ChecksPanel::run()
{
    const QStringList checks = checkedChecks();
    if (checks.isEmpty()) {
        setSummary(tr("Tick at least one check"));
        return;
    }
    emit runRequested(checks, options());
}

void ChecksPanel::setIdsFiles(const QStringList& names)
{
    const QString current = m_idsList->currentItem() ? m_idsList->currentItem()->text() : QString();
    m_idsList->clear();
    m_idsList->addItems(names);
    const auto found = m_idsList->findItems(current, Qt::MatchExactly);
    if (!found.isEmpty())
        m_idsList->setCurrentItem(found.first());
}

QStringList ChecksPanel::idsFiles() const
{
    QStringList out;
    for (int i = 0; i < m_idsList->count(); ++i)
        out << m_idsList->item(i)->text();
    return out;
}

void ChecksPanel::setClashSets(const QJsonObject& sets)
{
    m_clashSets = sets;
    m_clashList->clear();
    for (auto it = sets.begin(); it != sets.end(); ++it) {
        const QJsonObject s = it.value().toObject();
        const QString b = s.contains("b") && s.value("b").isObject() ? ClashSetDialog::sideText(s.value("b").toObject()) : tr("itself");
        const bool clearance = s.value("mode").toString() == QLatin1String("clearance");
        const QString what = clearance ? tr("clearance %1 mm").arg(s.value("clearance").toDouble(0.05) * 1000.0, 0, 'f', 0)
                                       : tr("hard, tolerance %1 mm").arg(s.value("tolerance").toDouble(0.002) * 1000.0, 0, 'f', 0);
        auto* item = new QListWidgetItem(QStringLiteral("%1: %2 × %3 (%4)")
                .arg(it.key(), ClashSetDialog::sideText(s.value("a").toObject()), b, what), m_clashList);
        item->setData(Qt::UserRole, it.key());
        item->setToolTip(item->text());
    }
}

QStringList ChecksPanel::clashSetNames() const
{
    return m_clashSets.keys();
}

void ChecksPanel::setChoices(const QStringList& classes, const QStringList& criteria, const QStringList& sets)
{
    m_classes = classes;
    m_criteria = criteria;
    m_sets = sets;
}

void ChecksPanel::editClashSet(const QString& name)
{
    ClashSetDialog dialog(m_classes, m_criteria, m_sets, this);
    if (!name.isEmpty())
        dialog.setSet(name, m_clashSets.value(name).toObject());
    if (dialog.exec() != QDialog::Accepted)
        return;
    if (dialog.name().isEmpty() || dialog.set().value("a").toObject().isEmpty()) {
        setSummary(tr("A clash set needs a name and set A"));
        return;
    }
    emit saveClashSetRequested(dialog.name(), dialog.set(), name);
}

void ChecksPanel::clearResults()
{
    m_results->clear();
}

void ChecksPanel::addResult(const QJsonObject& r)
{
    auto* top = new QTreeWidgetItem(m_results);
    top->setData(0, KindRole, QStringLiteral("check"));
    const QString title = r.value("title").toString(r.value("check").toString());
    QFont bold = top->font(0);
    bold.setBold(true);
    top->setFont(0, bold);
    if (!r.value("ok").toBool()) {
        top->setText(0, r.value("cancelled").toBool() ? tr("%1: stopped").arg(title)
                                                      : tr("%1: could not run").arg(title));
        top->setIcon(0, severityIcon(QStringLiteral("warning")));
        top->setToolTip(0, r.value("error").toString());
        if (!r.value("cancelled").toBool()) {
            auto* why = new QTreeWidgetItem(top, {r.value("error").toString()});
            why->setToolTip(0, r.value("error").toString());
        }
        top->setExpanded(true);
        return;
    }
    const QJsonObject counts = r.value("counts").toObject();
    const int errors = counts.value("error").toInt(), warnings = counts.value("warning").toInt();
    const int total = r.value("total").toInt();
    QString text = total == 0 ? tr("%1: no issues").arg(title)
                              : tr("%1: %2").arg(title, tr("%n issue(s)", nullptr, total));
    text += QStringLiteral(" (%1 s)").arg(r.value("seconds").toDouble(), 0, 'f', 1);
    top->setText(0, text);
    top->setIcon(0, severityIcon(errors ? QStringLiteral("error") : warnings ? QStringLiteral("warning") : QStringLiteral("pass")));
    if (!r.value("detail").toString().isEmpty())
        top->setToolTip(0, r.value("detail").toString());
    if (errors || warnings)
        top->setText(1, QStringLiteral("%1 / %2").arg(errors).arg(warnings));
    top->setToolTip(1, tr("errors / warnings"));

    // Groups: those the check names (with pass/fail), then any its issues name.
    QHash<QString, QTreeWidgetItem*> groups;
    auto group = [&](const QString& name) {
        if (QTreeWidgetItem* g = groups.value(name))
            return g;
        auto* g = new QTreeWidgetItem(top, {name.isEmpty() ? title : name});
        g->setData(0, KindRole, QStringLiteral("group"));
        g->setToolTip(0, g->text(0));
        groups.insert(name, g);
        return g;
    };
    for (const auto& v : r.value("groups").toArray()) {
        const QJsonObject g = v.toObject();
        QTreeWidgetItem* item = group(g.value("name").toString());
        item->setIcon(0, severityIcon(g.value("status").toString()));
        item->setText(1, g.value("detail").toString());
        item->setToolTip(1, g.value("detail").toString());
    }
    QHash<QTreeWidgetItem*, QStringList> groupGuids;
    for (const auto& v : r.value("issues").toArray()) {
        const QJsonObject i = v.toObject();
        QTreeWidgetItem* g = group(i.value("group").toString());
        if (g->icon(0).isNull())
            g->setIcon(0, severityIcon(i.value("severity").toString()));
        const QStringList guids = strings(i.value("guids"));
        const QStringList labels = strings(i.value("labels"));
        auto* item = new QTreeWidgetItem(g, {i.value("message").toString()});
        item->setData(0, KindRole, QStringLiteral("issue"));
        item->setData(0, GuidsRole, guids);
        item->setIcon(0, severityIcon(i.value("severity").toString()));
        QString elements = labels.mid(0, 2).join(QStringLiteral(", "));
        if (guids.size() > 2)
            elements += QStringLiteral(" +%1").arg(guids.size() - 2);
        item->setText(1, elements);
        item->setToolTip(0, i.value("message").toString() + (labels.isEmpty() ? QString() : QStringLiteral("\n") + labels.join(QStringLiteral("\n"))));
        item->setToolTip(1, labels.join(QStringLiteral("\n")));
        groupGuids[g] << guids;
    }
    for (auto it = groupGuids.begin(); it != groupGuids.end(); ++it) {
        QStringList all = it.value();
        all.removeDuplicates();
        it.key()->setData(0, GuidsRole, all); // a group selects all of its elements
        if (it.key()->text(1).isEmpty())
            it.key()->setText(1, tr("%n issue(s)", nullptr, it.key()->childCount()));
    }
    if (r.value("truncated").toBool())
        new QTreeWidgetItem(top, {tr("%n more not shown", nullptr, total - int(r.value("issues").toArray().size()))});
    top->setExpanded(true);
    for (QTreeWidgetItem* g : std::as_const(groups))
        g->setExpanded(g->childCount() > 0 && g->childCount() <= 50);
}

QList<QTreeWidgetItem*> ChecksPanel::issueItems() const
{
    QList<QTreeWidgetItem*> out;
    for (QTreeWidgetItemIterator it(m_results); *it; ++it)
        if ((*it)->data(0, KindRole).toString() == QLatin1String("issue"))
            out << *it;
    return out;
}

int ChecksPanel::issueCount() const
{
    return int(issueItems().size());
}

QStringList ChecksPanel::issueGuids(int n) const
{
    const auto items = issueItems();
    return n >= 0 && n < items.size() ? items.at(n)->data(0, GuidsRole).toStringList() : QStringList();
}

QString ChecksPanel::issueText(int n) const
{
    const auto items = issueItems();
    return n >= 0 && n < items.size() ? items.at(n)->text(0) : QString();
}

bool ChecksPanel::activateIssue(int n)
{
    const auto items = issueItems();
    if (n < 0 || n >= items.size())
        return false;
    m_results->setCurrentItem(items.at(n));
    m_results->scrollToItem(items.at(n));
    emit m_results->itemClicked(items.at(n), 0);
    return true;
}

void ChecksPanel::setSummary(const QString& text)
{
    m_summary->setText(text);
}

QString ChecksPanel::summary() const
{
    return m_summary->text();
}

void ChecksPanel::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
    emit refreshRequested();
}

// ---------------------------------------------------------------- clash set dialog

ClashSetDialog::ClashSetDialog(const QStringList& classes, const QStringList& criteria, const QStringList& sets, QWidget* parent)
    : QDialog(parent)
    , m_name(new QLineEdit(this))
    , m_a(new QComboBox(this))
    , m_b(new QComboBox(this))
    , m_mode(new QComboBox(this))
    , m_distance(new QDoubleSpinBox(this))
{
    setWindowTitle(tr("Clash set"));
    m_name->setObjectName(QStringLiteral("clashSetName"));
    for (QComboBox* c : {m_a, m_b}) {
        c->setEditable(true); // IFC classes can be typed, several separated by commas
        c->setInsertPolicy(QComboBox::NoInsert);
        c->setMinimumContentsLength(18);
        for (const QString& name : criteria)
            c->addItem(tr("Criteria: %1").arg(name));
        for (const QString& name : sets)
            c->addItem(tr("Selection set: %1").arg(name));
        c->addItems(classes);
    }
    m_b->insertItem(0, tr("(set A against itself)"));
    m_b->setCurrentIndex(0);
    m_a->setCurrentText(classes.contains(QStringLiteral("IfcWall")) ? QStringLiteral("IfcWall") : QString());
    m_a->setToolTip(tr("IFC classes (comma separated), a Find & Select criteria set or a selection set"));
    m_b->setToolTip(m_a->toolTip());
    m_mode->addItem(tr("Hard clash"), QStringLiteral("hard"));
    m_mode->addItem(tr("Clearance"), QStringLiteral("clearance"));
    m_distance->setRange(0, 10000);
    m_distance->setDecimals(0);
    m_distance->setSuffix(QStringLiteral(" mm"));
    m_distance->setValue(2);
    connect(m_mode, &QComboBox::currentIndexChanged, this, [this](int i) {
        m_distance->setValue(i == 1 ? 50 : 2); // the defaults: 2 mm tolerance, 50 mm clearance
    });
    auto* form = new QFormLayout;
    form->addRow(tr("Name:"), m_name);
    form->addRow(tr("Set A:"), m_a);
    form->addRow(tr("Set B:"), m_b);
    form->addRow(tr("Check:"), m_mode);
    form->addRow(tr("Tolerance / clearance:"), m_distance);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    auto* layout = new QVBoxLayout(this);
    auto* hint = new QLabel(tr("Hard clash: the elements intersect deeper than the tolerance. Clearance: they are closer than the distance."), this);
    hint->setWordWrap(true);
    layout->addLayout(form);
    layout->addWidget(hint);
    layout->addWidget(buttons);
}

void ClashSetDialog::setSet(const QString& name, const QJsonObject& set)
{
    m_name->setText(name);
    m_a->setCurrentText(sideText(set.value("a").toObject()));
    if (set.value("b").isObject())
        m_b->setCurrentText(sideText(set.value("b").toObject()));
    else
        m_b->setCurrentIndex(0);
    const bool clearance = set.value("mode").toString() == QLatin1String("clearance");
    m_mode->setCurrentIndex(clearance ? 1 : 0);
    m_distance->setValue((clearance ? set.value("clearance").toDouble(0.05) : set.value("tolerance").toDouble(0.002)) * 1000.0);
}

QString ClashSetDialog::name() const
{
    return m_name->text().trimmed();
}

QJsonObject ClashSetDialog::set() const
{
    QJsonObject s{{"a", parseSide(m_a->currentText())}, {"mode", m_mode->currentData().toString()}};
    if (m_b->currentIndex() != 0 || m_b->currentText() != m_b->itemText(0)) {
        const QJsonObject b = parseSide(m_b->currentText());
        if (!b.isEmpty())
            s.insert("b", b);
    }
    s.insert(m_mode->currentIndex() == 1 ? "clearance" : "tolerance", m_distance->value() / 1000.0);
    return s;
}

QJsonObject ClashSetDialog::parseSide(const QString& text)
{
    const QString criteria = tr("Criteria: %1").arg(QString()), set = tr("Selection set: %1").arg(QString());
    const QString t = text.trimmed();
    if (t.startsWith(criteria) && t.size() > criteria.size())
        return {{"criteria", t.mid(criteria.size()).trimmed()}};
    if (t.startsWith(set) && t.size() > set.size())
        return {{"selection_set", t.mid(set.size()).trimmed()}};
    QJsonArray classes;
    for (QString c : t.split(QLatin1Char(','), Qt::SkipEmptyParts)) {
        c = c.trimmed();
        if (c.startsWith(QLatin1String("Ifc"), Qt::CaseInsensitive))
            classes << (QStringLiteral("Ifc") + c.mid(3));
    }
    return classes.isEmpty() ? QJsonObject() : QJsonObject{{"classes", classes}};
}

QString ClashSetDialog::sideText(const QJsonObject& side)
{
    if (side.contains("criteria"))
        return tr("Criteria: %1").arg(side.value("criteria").toString());
    if (side.contains("selection_set"))
        return tr("Selection set: %1").arg(side.value("selection_set").toString());
    return strings(side.value("classes")).join(QStringLiteral(", "));
}

} // namespace kimcad
