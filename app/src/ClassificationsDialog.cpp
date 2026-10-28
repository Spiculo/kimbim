// SPDX-License-Identifier: GPL-3.0-or-later
#include "ClassificationsDialog.h"

#include "PythonEngine.h"

#include <QComboBox>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPushButton>
#include <QVBoxLayout>

namespace kimbim {

ClassificationsDialog::ClassificationsDialog(const QStringList& selection, QWidget* parent)
    : QDialog(parent)
    , m_selection(selection)
    , m_systems(new QComboBox(this))
    , m_references(new QListWidget(this))
    , m_identification(new QLineEdit(this))
    , m_name(new QLineEdit(this))
    , m_assign(new QPushButton(tr("Assign to selection"), this))
    , m_unassign(new QPushButton(tr("Unassign from selection"), this))
    , m_remove(new QPushButton(tr("Remove code"), this))
{
    setObjectName(QStringLiteral("classificationsDialog"));
    setWindowTitle(tr("Classifications"));
    m_systems->setObjectName(QStringLiteral("classificationSystems"));
    m_references->setObjectName(QStringLiteral("classificationReferences"));
    m_references->setSelectionMode(QAbstractItemView::ExtendedSelection);
    m_identification->setObjectName(QStringLiteral("classificationIdentification"));
    m_identification->setPlaceholderText(tr("Code, e.g. Pr_20_93_85"));
    m_name->setObjectName(QStringLiteral("classificationName"));
    m_name->setPlaceholderText(tr("Name, e.g. Wall products"));
    m_assign->setObjectName(QStringLiteral("classificationAssign"));
    m_unassign->setObjectName(QStringLiteral("classificationUnassign"));
    m_remove->setObjectName(QStringLiteral("classificationRemove"));

    auto* addSystem = new QPushButton(tr("New system..."), this);
    addSystem->setObjectName(QStringLiteral("classificationNewSystem"));
    auto* addCode = new QPushButton(tr("Add code"), this);
    addCode->setObjectName(QStringLiteral("classificationAddCode"));
    connect(addSystem, &QPushButton::clicked, this, &ClassificationsDialog::addSystem);
    connect(addCode, &QPushButton::clicked, this, [this, addCode] {
        const QString system = currentSystem();
        if (system.isEmpty())
            return;
        const QJsonObject r = PythonEngine::instance().callJson("add_reference",
            {system, m_identification->text(), m_name->text()}).object();
        if (r.value("ok").toBool()) {
            m_identification->clear();
            m_name->clear();
            refresh();
            emit changed();
        } else {
            addCode->setToolTip(r.value("error").toString());
        }
    });
    connect(m_assign, &QPushButton::clicked, this, &ClassificationsDialog::assign);
    connect(m_unassign, &QPushButton::clicked, this, &ClassificationsDialog::unassign);
    connect(m_remove, &QPushButton::clicked, this, &ClassificationsDialog::removeReference);

    auto* info = new QLabel(tr("%n selected element(s). A code can be assigned from several systems.",
                               nullptr, int(m_selection.size())), this);
    info->setWordWrap(true);
    auto* form = new QFormLayout;
    form->addRow(tr("System:"), m_systems);
    form->addRow(tr("Code:"), m_identification);
    form->addRow(tr("Name:"), m_name);
    auto* row = new QHBoxLayout;
    row->addWidget(addSystem);
    row->addWidget(addCode);
    row->addStretch(1);
    auto* actions = new QHBoxLayout;
    actions->addWidget(m_assign);
    actions->addWidget(m_unassign);
    actions->addWidget(m_remove);
    actions->addStretch(1);
    auto* close = new QDialogButtonBox(QDialogButtonBox::Close, this);
    connect(close, &QDialogButtonBox::rejected, this, &QDialog::reject);

    auto* layout = new QVBoxLayout(this);
    layout->addWidget(info);
    layout->addLayout(form);
    layout->addLayout(row);
    layout->addWidget(m_references, 1);
    layout->addLayout(actions);
    layout->addWidget(close);

    connect(m_systems, &QComboBox::currentIndexChanged, this, [this] { refresh(); });
    connect(m_references, &QListWidget::itemSelectionChanged, this, [this] {
        const bool has = !m_references->selectedItems().isEmpty();
        m_assign->setEnabled(has && !m_selection.isEmpty());
        m_unassign->setEnabled(has && !m_selection.isEmpty());
        m_remove->setEnabled(has);
    });
    refresh();
}

QString ClassificationsDialog::selectionJson() const
{
    QJsonArray array;
    for (const QString& guid : m_selection)
        array.append(guid);
    return QString::fromUtf8(QJsonDocument(array).toJson(QJsonDocument::Compact));
}

QString ClassificationsDialog::currentSystem() const
{
    return m_systems->currentData().toString();
}

void ClassificationsDialog::setSystem(const QString& name)
{
    const int index = m_systems->findText(name);
    if (index >= 0)
        m_systems->setCurrentIndex(index);
}

void ClassificationsDialog::refresh()
{
    const QString keep = currentSystem();
    const QJsonObject all = PythonEngine::instance().callJson("systems", {}).object();
    m_systems->blockSignals(true);
    m_systems->clear();
    for (const auto& value : all.value("systems").toArray()) {
        const QJsonObject s = value.toObject();
        m_systems->addItem(s.value("name").toString(), s.value("id").toVariant().toString());
    }
    if (!keep.isEmpty()) {
        const int index = m_systems->findData(keep);
        if (index >= 0)
            m_systems->setCurrentIndex(index);
    }
    m_systems->blockSignals(false);

    m_references->clear();
    const QString system = currentSystem();
    for (const auto& value : all.value("systems").toArray()) {
        const QJsonObject s = value.toObject();
        if (s.value("id").toVariant().toString() != system)
            continue;
        for (const auto& refValue : s.value("references").toArray()) {
            const QJsonObject ref = refValue.toObject();
            auto* item = new QListWidgetItem(QStringLiteral("%1 — %2")
                    .arg(ref.value("identification").toString(), ref.value("name").toString()),
                m_references);
            item->setData(Qt::UserRole, ref);
        }
    }
    const bool has = m_references->count() > 0;
    m_assign->setEnabled(has && !m_selection.isEmpty());
    m_unassign->setEnabled(has && !m_selection.isEmpty());
    m_remove->setEnabled(has);
}

void ClassificationsDialog::addSystem()
{
    bool ok = false;
    const QString name = QInputDialog::getText(this, tr("New classification system"), tr("Name:"),
                                               QLineEdit::Normal, QString(), &ok);
    if (!ok || name.trimmed().isEmpty())
        return;
    const QString source = QInputDialog::getText(this, tr("New classification system"),
        tr("Source (e.g. NBS):"), QLineEdit::Normal, QString(), &ok);
    if (!ok)
        return;
    const QString edition = QInputDialog::getText(this, tr("New classification system"),
        tr("Edition:"), QLineEdit::Normal, QString(), &ok);
    if (!ok)
        return;
    const QJsonObject r = PythonEngine::instance().callJson("create_system",
        {name, source, edition, QString()}).object();
    if (r.value("ok").toBool()) {
        refresh();
        setSystem(name);
        emit changed();
    }
}

void ClassificationsDialog::assign()
{
    QJsonArray keys;
    for (QListWidgetItem* item : m_references->selectedItems())
        keys.append(item->data(Qt::UserRole).toJsonObject().value("key").toString());
    if (keys.isEmpty() || m_selection.isEmpty())
        return;
    const QString json = QString::fromUtf8(QJsonDocument(keys).toJson(QJsonDocument::Compact));
    const QJsonObject r = PythonEngine::instance().callJson("assign_classification",
        {selectionJson(), json}).object();
    if (r.value("ok").toBool())
        emit changed();
}

void ClassificationsDialog::unassign()
{
    QJsonArray keys;
    for (QListWidgetItem* item : m_references->selectedItems())
        keys.append(item->data(Qt::UserRole).toJsonObject().value("key").toString());
    if (keys.isEmpty() || m_selection.isEmpty())
        return;
    const QString json = QString::fromUtf8(QJsonDocument(keys).toJson(QJsonDocument::Compact));
    const QJsonObject r = PythonEngine::instance().callJson("unassign_classification",
        {selectionJson(), json}).object();
    if (r.value("ok").toBool())
        emit changed();
}

void ClassificationsDialog::removeReference()
{
    QListWidgetItem* item = m_references->currentItem();
    if (!item)
        return;
    const QJsonObject ref = item->data(Qt::UserRole).toJsonObject();
    const QJsonObject r = PythonEngine::instance().callJson("remove_reference",
        {ref.value("key").toString()}).object();
    if (r.value("ok").toBool()) {
        refresh();
        emit changed();
    }
}

} // namespace kimbim
