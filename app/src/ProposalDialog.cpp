// SPDX-License-Identifier: GPL-3.0-or-later
#include "ProposalDialog.h"

#include <QColor>
#include <QComboBox>
#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QHash>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QSplitter>
#include <QTabWidget>
#include <QTableWidget>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <algorithm>

namespace kimbim {

namespace {

enum ConflictColumn { ConflictElement, ConflictWhat, ConflictBase, ConflictOurs, ConflictTheirs, ConflictChoice, ConflictColumns };
enum DetailColumn { DetailField, DetailBase, DetailAgent, DetailColumns };

QString compact(const QJsonObject& value)
{
    return QString::fromUtf8(QJsonDocument(value).toJson(QJsonDocument::Compact));
}

} // namespace

ProposalDialog::ProposalDialog(Bridge bridge, const QJsonObject& proposal, QWidget* parent)
    : QDialog(parent)
    , m_bridge(std::move(bridge))
    , m_proposal(proposal)
    , m_baseRev(proposal.value(QStringLiteral("base_version")).toString())
    , m_option(proposal.value(QStringLiteral("option")).toString())
    , m_tabs(new QTabWidget(this))
    , m_changes(new QTreeWidget(this))
    , m_details(new QTableWidget(this))
    , m_detailNote(new QLabel(this))
    , m_show(new QPushButton(tr("Show in 3D"), this))
    , m_conflicts(new QTableWidget(this))
    , m_conflictStatus(new QLabel(this))
    , m_accept(new QPushButton(tr("Accept proposal"), this))
{
    if (m_baseRev.isEmpty())
        m_baseRev = proposal.value(QStringLiteral("base_option")).toString();
    if (m_baseRev.isEmpty())
        m_baseRev = QStringLiteral("WORKING");
    setObjectName(QStringLiteral("proposalDialog"));
    setWindowTitle(tr("Review agent proposal"));
    setMinimumSize(980, 640);

    const QString title = proposal.value(QStringLiteral("title")).toString();
    const QString client = proposal.value(QStringLiteral("client")).toString();
    const QString baseOption = proposal.value(QStringLiteral("base_option")).toString();
    const QJsonObject counts = proposal.value(QStringLiteral("counts")).toObject();
    const int changed = counts.value(QStringLiteral("added")).toInt() + counts.value(QStringLiteral("modified")).toInt()
        + counts.value(QStringLiteral("removed")).toInt();
    auto* heading = new QLabel(QStringLiteral("<b>%1</b>").arg(title.toHtmlEscaped()), this);
    heading->setObjectName(QStringLiteral("proposalDialogTitle"));
    auto* subtitle = new QLabel(tr("%1 changed element(s) - agent option: %2%3")
                                    .arg(changed)
                                    .arg(m_option)
                                    .arg(baseOption.isEmpty() ? QString() : tr(" - into: %1").arg(baseOption)),
        this);
    subtitle->setWordWrap(true);
    subtitle->setStyleSheet(QStringLiteral("color:#555"));
    auto* summary = new QLabel(proposal.value(QStringLiteral("summary")).toString(), this);
    summary->setWordWrap(true);
    summary->setStyleSheet(QStringLiteral("color:#333"));
    auto* who = new QLabel(client.isEmpty() ? QString() : tr("Prepared by %1").arg(client), this);
    who->setStyleSheet(QStringLiteral("color:#777"));

    // Changes: the elements the proposal touches, and the selected element's fields.
    auto* changesTab = new QWidget(this);
    auto* changesLayout = new QVBoxLayout(changesTab);
    changesLayout->setContentsMargins(0, 6, 0, 0);
    auto* split = new QSplitter(Qt::Horizontal, changesTab);
    m_changes->setObjectName(QStringLiteral("proposalChanges"));
    m_changes->setHeaderLabels({tr("Change"), tr("Type")});
    m_changes->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_changes->setMinimumWidth(300);
    const QJsonObject compare = m_bridge("compare", {m_baseRev, m_option});
    const struct {
        const char* key;
        QString title;
        QColor colour;
    } groups[] = {{"added", tr("Added"), QColor(60, 175, 90)}, {"modified", tr("Modified"), QColor(235, 150, 40)},
        {"removed", tr("Removed"), QColor(150, 150, 150)}};
    int total = 0;
    for (const auto& group : groups) {
        const QJsonArray items = compare.value(QLatin1String(group.key)).toArray();
        auto* top = new QTreeWidgetItem(m_changes, {QStringLiteral("%1 (%2)").arg(group.title).arg(items.size())});
        top->setForeground(0, group.colour);
        for (const auto& value : items) {
            const QJsonObject item = value.toObject();
            const QString guid = item.value(QStringLiteral("guid")).toString();
            auto* child = new QTreeWidgetItem(top,
                {item.value(QStringLiteral("name")).toString().isEmpty() ? guid
                                                                         : item.value(QStringLiteral("name")).toString(),
                    item.value(QStringLiteral("type")).toString()});
            child->setData(0, Qt::UserRole, guid);
            ++total;
        }
        top->setExpanded(items.size() <= 50);
    }
    if (!compare.value(QStringLiteral("ok")).toBool())
        new QTreeWidgetItem(m_changes, {tr("Could not compare: %1").arg(compare.value(QStringLiteral("error")).toString())});
    else if (total == 0)
        new QTreeWidgetItem(m_changes, {tr("No element changes.")});

    auto* detailPane = new QWidget(split);
    auto* detailLayout = new QVBoxLayout(detailPane);
    detailLayout->setContentsMargins(8, 0, 0, 0);
    m_detailNote->setObjectName(QStringLiteral("proposalDetailNote"));
    m_detailNote->setWordWrap(true);
    m_detailNote->setStyleSheet(QStringLiteral("color:#666"));
    m_details->setObjectName(QStringLiteral("proposalDetails"));
    m_details->setColumnCount(DetailColumns);
    m_details->setHorizontalHeaderLabels({tr("Field"), tr("Base"), tr("Agent")});
    m_details->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_details->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_details->horizontalHeader()->setStretchLastSection(true);
    m_show->setObjectName(QStringLiteral("proposalShowIn3d"));
    m_show->setEnabled(false);
    auto* showRow = new QHBoxLayout;
    showRow->addWidget(m_detailNote, 1);
    showRow->addWidget(m_show);
    detailLayout->addLayout(showRow);
    detailLayout->addWidget(m_details, 1);
    split->addWidget(m_changes);
    split->addWidget(detailPane);
    split->setStretchFactor(0, 1);
    split->setStretchFactor(1, 2);
    changesLayout->addWidget(split, 1);
    connect(m_changes, &QTreeWidget::currentItemChanged, this,
        [this](QTreeWidgetItem* current, QTreeWidgetItem*) { showElement(current); });
    connect(m_show, &QPushButton::clicked, this, [this] {
        const auto items = m_changes->selectedItems();
        if (!items.isEmpty()) {
            const QString guid = items.first()->data(0, Qt::UserRole).toString();
            if (!guid.isEmpty())
                emit elementActivated(guid);
        }
    });

    // Conflicts: what both sides changed, with a choice per conflict.
    auto* conflictsTab = new QWidget(this);
    auto* conflictsLayout = new QVBoxLayout(conflictsTab);
    conflictsLayout->setContentsMargins(0, 6, 0, 0);
    m_conflictStatus->setObjectName(QStringLiteral("proposalConflictStatus"));
    m_conflictStatus->setWordWrap(true);
    m_conflicts->setObjectName(QStringLiteral("proposalConflicts"));
    m_conflicts->setColumnCount(ConflictColumns);
    m_conflicts->setHorizontalHeaderLabels({tr("Element"), tr("What"), tr("Common version"),
        tr("Base option"), tr("Agent option"), tr("Keep")});
    m_conflicts->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_conflicts->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_conflicts->horizontalHeader()->setStretchLastSection(true);
    conflictsLayout->addWidget(m_conflictStatus);
    conflictsLayout->addWidget(m_conflicts, 1);

    m_tabs->addTab(changesTab, tr("Changes (%1)").arg(total));
    m_tabs->addTab(conflictsTab, tr("Conflicts"));

    auto* close = new QPushButton(tr("Close"), this);
    close->setObjectName(QStringLiteral("proposalDialogClose"));
    auto* reject = new QPushButton(tr("Reject proposal"), this);
    reject->setObjectName(QStringLiteral("proposalDialogReject"));
    m_accept->setObjectName(QStringLiteral("proposalDialogAccept"));
    m_accept->setDefault(true);
    auto* buttons = new QHBoxLayout;
    buttons->addWidget(reject);
    buttons->addStretch(1);
    buttons->addWidget(close);
    buttons->addWidget(m_accept);
    connect(close, &QPushButton::clicked, this, &QDialog::reject);
    connect(reject, &QPushButton::clicked, this, &ProposalDialog::confirmReject);
    connect(m_accept, &QPushButton::clicked, this, &QDialog::accept);

    auto* layout = new QVBoxLayout(this);
    layout->addWidget(heading);
    layout->addWidget(subtitle);
    layout->addWidget(summary);
    layout->addWidget(who);
    layout->addWidget(m_tabs, 1);
    layout->addLayout(buttons);
    refreshConflicts();
}

void ProposalDialog::showElement(QTreeWidgetItem* item)
{
    const QString guid = item ? item->data(0, Qt::UserRole).toString() : QString();
    m_details->setRowCount(0);
    m_show->setEnabled(false);
    if (guid.isEmpty()) {
        m_detailNote->clear();
        return;
    }
    const QJsonObject result = m_bridge("before_after", {guid, m_baseRev, m_option});
    if (!result.value(QStringLiteral("ok")).toBool()) {
        m_detailNote->setText(tr("Could not read this element: %1").arg(result.value(QStringLiteral("error")).toString()));
        return;
    }
    const QJsonArray rows = result.value(QStringLiteral("rows")).toArray();
    m_details->setRowCount(int(rows.size()));
    int changed = 0;
    for (int i = 0; i < rows.size(); ++i) {
        const QJsonObject row = rows[i].toObject();
        const bool isChanged = row.value(QStringLiteral("changed")).toBool();
        changed += isChanged ? 1 : 0;
        const QStringList cells = {row.value(QStringLiteral("field")).toString(),
            row.value(QStringLiteral("before")).toString(), row.value(QStringLiteral("after")).toString()};
        for (int c = 0; c < DetailColumns; ++c) {
            auto* cell = new QTableWidgetItem(cells[c]);
            if (isChanged && c > 0)
                cell->setBackground(QColor(255, 236, 200));
            m_details->setItem(i, c, cell);
        }
    }
    m_details->resizeColumnsToContents();
    if (!result.value(QStringLiteral("before_exists")).toBool())
        m_detailNote->setText(tr("Added by the proposal: it did not exist in the base version."));
    else if (!result.value(QStringLiteral("after_exists")).toBool())
        m_detailNote->setText(tr("Removed by the proposal."));
    else if (changed == 0)
        m_detailNote->setText(tr("No field changed."));
    else
        m_detailNote->setText(tr("%1 field(s) changed.").arg(changed));
    m_show->setEnabled(true);
}

void ProposalDialog::refreshConflicts()
{
    if (m_refreshing)
        return;
    m_refreshing = true;
    m_refreshQueued = false;
    m_preview = m_bridge("combine_preview", {m_option, compact(m_resolutions)});
    const QJsonArray conflicts = m_preview.value(QStringLiteral("conflicts")).toArray();
    const QString status = m_preview.value(QStringLiteral("status")).toString();
    const int unresolved = int(m_preview.value(QStringLiteral("unresolved")).toArray().size());
    const int brings = int(m_preview.value(QStringLiteral("from_theirs")).toArray().size());
    m_tabs->setTabText(1, tr("Conflicts (%1)").arg(conflicts.size()));
    if (!m_preview.value(QStringLiteral("ok")).toBool()) {
        m_conflictStatus->setText(tr("Could not preview the merge: %1")
                                      .arg(m_preview.value(QStringLiteral("error")).toString()));
    } else if (status == QLatin1String("up_to_date")) {
        m_conflictStatus->setText(tr("The base option already has everything in this proposal."));
    } else if (status == QLatin1String("fast_forward")) {
        m_conflictStatus->setText(tr("The proposal applies cleanly: %1 changed element(s) will be brought in.")
                                      .arg(brings));
    } else if (conflicts.isEmpty()) {
        m_conflictStatus->setText(tr("No conflicts: %1 changed element(s) will be brought in.").arg(brings));
    } else {
        m_conflictStatus->setText(tr("%1 conflict(s), %2 left to choose.").arg(conflicts.size()).arg(unresolved));
    }
    const QString baseOption = m_proposal.value(QStringLiteral("base_option")).toString();
    const QHash<QString, QString> kinds = {{QStringLiteral("attribute"), tr("changed in both")},
        {QStringLiteral("property"), tr("property changed in both")},
        {QStringLiteral("class"), tr("class changed in both")},
        {QStringLiteral("delete_modify"), tr("deleted in one, changed in the other")},
        {QStringLiteral("both_added"), tr("added in both")}, {QStringLiteral("loose"), tr("changed in both")},
        {QStringLiteral("dangling"), tr("refers to something deleted")},
        {QStringLiteral("containment"), tr("on two levels")}};
    m_conflicts->setRowCount(int(conflicts.size()));
    for (int i = 0; i < conflicts.size(); ++i) {
        const QJsonObject conflict = conflicts[i].toObject();
        auto* element = new QTableWidgetItem(QStringLiteral("%1 %2")
                                                 .arg(conflict.value(QStringLiteral("ifc_type")).toString(),
                                                     conflict.value(QStringLiteral("name")).toString())
                                                 .trimmed());
        element->setToolTip(conflict.value(QStringLiteral("message")).toString());
        m_conflicts->setItem(i, ConflictElement, element);
        QString what = kinds.value(conflict.value(QStringLiteral("kind")).toString(),
            conflict.value(QStringLiteral("kind")).toString());
        if (!conflict.value(QStringLiteral("attribute")).toString().isEmpty()
            && conflict.value(QStringLiteral("kind")).toString() != QLatin1String("dangling"))
            what = QStringLiteral("%1: %2")
                       .arg(conflict.value(QStringLiteral("property")).toString().isEmpty()
                               ? conflict.value(QStringLiteral("attribute")).toString()
                               : conflict.value(QStringLiteral("property")).toString(),
                           what);
        m_conflicts->setItem(i, ConflictWhat, new QTableWidgetItem(what));
        m_conflicts->setItem(i, ConflictBase, new QTableWidgetItem(conflict.value(QStringLiteral("base_text")).toString()));
        m_conflicts->setItem(i, ConflictOurs,
            new QTableWidgetItem(conflict.value(QStringLiteral("ours_text")).toString()));
        m_conflicts->setItem(i, ConflictTheirs,
            new QTableWidgetItem(conflict.value(QStringLiteral("theirs_text")).toString()));
        auto* box = new QComboBox(m_conflicts);
        box->addItem(tr("Choose..."), QString());
        const QJsonArray options = conflict.value(QStringLiteral("options")).toArray();
        const QJsonArray labels = conflict.value(QStringLiteral("option_labels")).toArray();
        for (int k = 0; k < options.size(); ++k) {
            const QString option = options[k].toString();
            QString label = k < labels.size() ? labels[k].toString() : QString();
            if (label.isEmpty())
                label = option == QLatin1String("ours") ? tr("Base option (%1)").arg(baseOption)
                    : option == QLatin1String("theirs")      ? tr("Agent option (%1)").arg(m_option)
                    : option == QLatin1String("restore")     ? tr("Restore what it refers to")
                    : option == QLatin1String("remove")      ? tr("Remove it")
                                                             : option;
            box->addItem(label, option);
        }
        box->setCurrentIndex(std::max(0, box->findData(conflict.value(QStringLiteral("choice")).toString())));
        const QString id = conflict.value(QStringLiteral("id")).toString();
        connect(box, &QComboBox::currentIndexChanged, this, [this, box, id] {
            if (m_refreshing)
                return;
            const QString choice = box->currentData().toString();
            if (choice.isEmpty())
                m_resolutions.remove(id);
            else
                m_resolutions.insert(id, choice);
            if (!m_refreshQueued) {
                m_refreshQueued = true;
                QMetaObject::invokeMethod(this, [this] {
                    if (m_refreshQueued)
                        refreshConflicts();
                }, Qt::QueuedConnection);
            }
        });
        m_conflicts->setCellWidget(i, ConflictChoice, box);
    }
    m_conflicts->resizeColumnsToContents();
    updateAccept();
    m_refreshing = false;
}

void ProposalDialog::updateAccept()
{
    const QString status = m_preview.value(QStringLiteral("status")).toString();
    const bool clean = m_preview.value(QStringLiteral("unresolved")).toArray().isEmpty();
    m_accept->setEnabled(m_preview.value(QStringLiteral("ok")).toBool() && status != QLatin1String("up_to_date") && clean);
}

void ProposalDialog::confirmReject()
{
    const auto answer = QMessageBox::question(this, tr("Reject proposal"),
        tr("Reject the proposal and delete the agent's design option? This can't be undone."),
        QMessageBox::Yes | QMessageBox::No, QMessageBox::No);
    if (answer != QMessageBox::Yes)
        return;
    m_rejected = true;
    reject();
}

} // namespace kimbim
