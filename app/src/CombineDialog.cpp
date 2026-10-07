// SPDX-License-Identifier: GPL-3.0-or-later
#include "CombineDialog.h"

#include <QComboBox>
#include <QDialogButtonBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QPushButton>
#include <QSignalBlocker>
#include <QTableWidget>
#include <QVBoxLayout>

namespace kimcad {

namespace {
enum Column { Element, What, Base, Ours, Theirs, Choice, Columns };
} // namespace

CombineDialog::CombineDialog(Bridge bridge, const QStringList& otherOptions, QWidget* parent)
    : QDialog(parent)
    , m_bridge(std::move(bridge))
    , m_option(new QComboBox(this))
    , m_status(new QLabel(this))
    , m_table(new QTableWidget(this))
{
    setObjectName(QStringLiteral("combineDialog"));
    setWindowTitle(tr("Combine options"));
    m_option->setObjectName(QStringLiteral("combineOption"));
    m_option->addItems(otherOptions);
    m_status->setWordWrap(true);
    m_table->setObjectName(QStringLiteral("conflictTable"));
    m_table->setColumnCount(Columns);
    m_table->setHorizontalHeaderLabels({tr("Element"), tr("What"), tr("Common version"), tr("This option"),
        tr("Other option"), tr("Keep")});
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->horizontalHeader()->setStretchLastSection(true);
    m_table->setMinimumSize(820, 280);
    auto* top = new QHBoxLayout;
    top->addWidget(new QLabel(tr("Bring into this option:"), this));
    top->addWidget(m_option, 1);
    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Cancel, this);
    m_combine = buttons->addButton(tr("Combine"), QDialogButtonBox::AcceptRole);
    m_combine->setObjectName(QStringLiteral("combineButton"));
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    auto* layout = new QVBoxLayout(this);
    layout->addLayout(top);
    layout->addWidget(m_status);
    layout->addWidget(m_table, 1);
    layout->addWidget(new QLabel(tr("Combining opens the result as unsaved work: review it, then Save version (or Discard)."), this));
    layout->addWidget(buttons);
    connect(m_option, &QComboBox::currentIndexChanged, this, [this] {
        m_resolutions = {};
        refresh();
    });
    connect(m_table, &QTableWidget::cellClicked, this, [this](int row, int) {
        const QString guid = m_table->item(row, Element)->data(Qt::UserRole).toString();
        if (!guid.isEmpty())
            emit elementActivated(guid);
    });
    refresh();
}

QString CombineDialog::option() const
{
    return m_option->currentText();
}

void CombineDialog::setOption(const QString& option)
{
    m_option->setCurrentText(option);
}

bool CombineDialog::choose(int row, const QString& choice)
{
    auto* box = qobject_cast<QComboBox*>(m_table->cellWidget(row, Choice));
    if (!box)
        return false;
    const int index = box->findData(choice);
    if (index < 0)
        return false;
    box->setCurrentIndex(index); // records the choice (and queues a refresh)
    refresh();
    return true;
}

void CombineDialog::refresh()
{
    if (m_refreshing)
        return;
    m_refreshing = true;
    m_preview = m_option->currentText().isEmpty()
        ? QJsonObject()
        : m_bridge("combine_preview",
              {m_option->currentText(), QString::fromUtf8(QJsonDocument(m_resolutions).toJson(QJsonDocument::Compact))});
    const QJsonArray conflicts = m_preview.value("conflicts").toArray();
    const QString status = m_preview.value("status").toString();
    const int brings = int(m_preview.value("from_theirs").toArray().size());
    const int open = int(m_preview.value("unresolved").toArray().size());
    if (!m_preview.value("ok").toBool())
        m_status->setText(m_preview.value("error").toString());
    else if (status == QLatin1String("up_to_date"))
        m_status->setText(tr("This option already contains everything in %1.").arg(option()));
    else if (status == QLatin1String("fast_forward"))
        m_status->setText(tr("This option has not changed since %1 branched off: it takes %1's latest version (%n element(s) change).", nullptr, brings).arg(option()));
    else if (conflicts.isEmpty())
        m_status->setText(tr("%1 brings %n changed element(s); no conflicts.", nullptr, brings).arg(option()));
    else
        m_status->setText(tr("%1 brings %n changed element(s). Both options changed the same things in %2 place(s): choose what to keep (%3 left).", nullptr, brings)
                              .arg(option()).arg(conflicts.size()).arg(open));
    m_table->setRowCount(int(conflicts.size()));
    const QHash<QString, QString> kinds = {{QStringLiteral("attribute"), tr("changed in both")},
        {QStringLiteral("property"), tr("property changed in both")}, {QStringLiteral("class"), tr("class changed in both")},
        {QStringLiteral("delete_modify"), tr("deleted in one, changed in the other")},
        {QStringLiteral("both_added"), tr("added in both")}, {QStringLiteral("loose"), tr("changed in both")},
        {QStringLiteral("dangling"), tr("refers to something deleted")}, {QStringLiteral("containment"), tr("on two levels")}};
    const QHash<QString, QString> choices = {{QStringLiteral("ours"), tr("This option")},
        {QStringLiteral("theirs"), tr("Other option")}, {QStringLiteral("restore"), tr("Restore what it refers to")},
        {QStringLiteral("remove"), tr("Remove it")}};
    for (int i = 0; i < conflicts.size(); ++i) {
        const QJsonObject c = conflicts[i].toObject();
        const QString name = c.value("name").toString();
        auto* element = new QTableWidgetItem(QStringLiteral("%1 %2").arg(c.value("ifc_type").toString(), name).trimmed());
        element->setData(Qt::UserRole, c.value("guid").toString());
        element->setToolTip(c.value("message").toString());
        m_table->setItem(i, Element, element);
        QString what = kinds.value(c.value("kind").toString(), c.value("kind").toString());
        if (!c.value("attribute").toString().isEmpty() && c.value("kind").toString() != QLatin1String("dangling"))
            what = QStringLiteral("%1: %2").arg(c.value("property").toString().isEmpty() ? c.value("attribute").toString()
                                                                                          : c.value("property").toString(),
                what);
        m_table->setItem(i, What, new QTableWidgetItem(what));
        m_table->setItem(i, Base, new QTableWidgetItem(c.value("base_text").toString()));
        m_table->setItem(i, Ours, new QTableWidgetItem(c.value("ours_text").toString()));
        m_table->setItem(i, Theirs, new QTableWidgetItem(c.value("theirs_text").toString()));
        auto* box = new QComboBox(m_table);
        box->addItem(tr("Choose..."), QString());
        const QJsonArray options = c.value("options").toArray();
        const QJsonArray labels = c.value("option_labels").toArray();
        for (int k = 0; k < options.size(); ++k) {
            const QString o = options[k].toString();
            box->addItem(k < labels.size() ? labels[k].toString() : choices.value(o, o), o);
        }
        box->setCurrentIndex(std::max(0, box->findData(c.value("choice").toString())));
        const QString id = c.value("id").toString();
        connect(box, &QComboBox::currentIndexChanged, this, [this, box, id] {
            const QString choice = box->currentData().toString();
            if (choice.isEmpty())
                m_resolutions.remove(id);
            else
                m_resolutions.insert(id, choice);
            // A choice can raise new questions (e.g. deleting what a new element refers to).
            QMetaObject::invokeMethod(this, &CombineDialog::refresh, Qt::QueuedConnection);
        });
        m_table->setCellWidget(i, Choice, box);
    }
    m_table->resizeColumnsToContents();
    m_combine->setEnabled(m_preview.value("ok").toBool() && status != QLatin1String("up_to_date") && open == 0);
    m_refreshing = false;
}

} // namespace kimcad
