// SPDX-License-Identifier: GPL-3.0-or-later
#include "TypeManagerDialog.h"

#include "PythonEngine.h"

#include <QDialogButtonBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QTreeWidget>
#include <QVBoxLayout>

namespace kimbim {

namespace {

QString compact(const QJsonObject& o)
{
    return QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact));
}

QString text(const QJsonObject& o, const char* key)
{
    return o.value(QLatin1String(key)).toString();
}

} // namespace

TypeManagerDialog::TypeManagerDialog(const QStringList& selection, QWidget* parent)
    : QDialog(parent)
    , m_selection(selection)
    , m_types(new QTreeWidget(this))
    , m_name(new QLineEdit(this))
    , m_description(new QLineEdit(this))
    , m_tag(new QLineEdit(this))
    , m_create(new QPushButton(tr("From selection..."), this))
    , m_assign(new QPushButton(tr("Assign to selection"), this))
    , m_updateAll(new QPushButton(tr("Update all occurrences"), this))
    , m_apply(new QPushButton(tr("Apply edits"), this))
{
    setObjectName(QStringLiteral("typeManagerDialog"));
    setWindowTitle(tr("Type manager"));
    m_types->setObjectName(QStringLiteral("typeManagerTypes"));
    m_types->setColumnCount(3);
    m_types->setHeaderLabels({tr("Type"), tr("IFC class"), tr("Elements")});
    m_types->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_types->header()->setSectionResizeMode(1, QHeaderView::ResizeToContents);
    m_types->header()->setSectionResizeMode(2, QHeaderView::ResizeToContents);
    m_types->setSelectionMode(QAbstractItemView::SingleSelection);
    m_name->setObjectName(QStringLiteral("typeManagerName"));
    m_description->setObjectName(QStringLiteral("typeManagerDescription"));
    m_tag->setObjectName(QStringLiteral("typeManagerTag"));
    m_create->setObjectName(QStringLiteral("typeManagerCreate"));
    m_assign->setObjectName(QStringLiteral("typeManagerAssign"));
    m_updateAll->setObjectName(QStringLiteral("typeManagerUpdateAll"));
    m_apply->setObjectName(QStringLiteral("typeManagerApply"));

    auto* info = new QLabel(tr("%n selected element(s). A type's values are inherited by its elements; "
                                "update all removes their overrides.",
                               nullptr, int(m_selection.size())),
                            this);
    info->setWordWrap(true);
    auto* form = new QFormLayout;
    form->addRow(tr("Name:"), m_name);
    form->addRow(tr("Description:"), m_description);
    form->addRow(tr("Tag:"), m_tag);
    auto* buttons = new QHBoxLayout;
    buttons->addWidget(m_create);
    buttons->addWidget(m_assign);
    buttons->addWidget(m_updateAll);
    buttons->addStretch(1);
    buttons->addWidget(m_apply);
    auto* close = new QDialogButtonBox(QDialogButtonBox::Close, this);
    connect(close, &QDialogButtonBox::rejected, this, &QDialog::reject);

    auto* layout = new QVBoxLayout(this);
    layout->addWidget(info);
    layout->addWidget(m_types, 1);
    layout->addLayout(form);
    layout->addLayout(buttons);
    layout->addWidget(close);

    connect(m_types, &QTreeWidget::itemSelectionChanged, this, [this] {
        const QJsonObject t = m_types->currentItem() ? m_types->currentItem()->data(0, Qt::UserRole).toJsonObject()
                                                     : QJsonObject{};
        m_name->setText(t.value("name").toString());
        m_description->setText(t.value("description").toString());
        m_tag->setText(t.value("tag").toString());
        m_assign->setEnabled(!t.isEmpty() && !m_selection.isEmpty());
        m_updateAll->setEnabled(!t.isEmpty());
        m_apply->setEnabled(!t.isEmpty());
    });
    connect(m_create, &QPushButton::clicked, this, [this] {
        bool ok = false;
        const QString name = QInputDialog::getText(this, tr("Make a type"),
            tr("Type name (from the first selected element):"), QLineEdit::Normal, QString(), &ok);
        if (!ok)
            return;
        const QJsonObject r = PythonEngine::instance().callJson("create_type", {selectionJson(), name}).object();
        if (!r.value("ok").toBool())
            m_create->setToolTip(r.value("error").toString());
        else {
            refresh();
            emit changed();
        }
    });
    connect(m_assign, &QPushButton::clicked, this, [this] {
        const QString guid = selectedType();
        if (guid.isEmpty())
            return;
        const QJsonObject r = PythonEngine::instance().callJson("assign_type", {selectionJson(), guid}).object();
        if (r.value("ok").toBool()) {
            refresh();
            emit changed();
        }
    });
    connect(m_updateAll, &QPushButton::clicked, this, [this] {
        const QString guid = selectedType();
        if (!guid.isEmpty() && PythonEngine::instance().callJson("update_type_all", {guid}).object()
                                    .value("ok").toBool()) {
            refresh();
            emit changed();
        }
    });
    connect(m_apply, &QPushButton::clicked, this, &TypeManagerDialog::applyEdits);
    refresh();
}

QString TypeManagerDialog::selectionJson() const
{
    QJsonArray array;
    for (const QString& guid : m_selection)
        array.append(guid);
    return QString::fromUtf8(QJsonDocument(array).toJson(QJsonDocument::Compact));
}

QString TypeManagerDialog::selectedType() const
{
    return m_types->currentItem() ? m_types->currentItem()->data(0, Qt::UserRole).toJsonObject()
                                        .value("guid").toString()
                                  : QString();
}

void TypeManagerDialog::setSelectedType(const QString& guid)
{
    for (int i = 0; i < m_types->topLevelItemCount(); ++i)
        if (m_types->topLevelItem(i)->data(0, Qt::UserRole).toJsonObject().value("guid").toString() == guid) {
            m_types->setCurrentItem(m_types->topLevelItem(i));
            return;
        }
}

void TypeManagerDialog::refresh()
{
    const QString current = selectedType();
    m_types->clear();
    const QJsonObject r = PythonEngine::instance().callJson("list_types", {}).object();
    for (const auto& value : r.value("types").toArray()) {
        const QJsonObject t = value.toObject();
        auto* item = new QTreeWidgetItem(m_types, {t.value("name").toString(), t.value("class").toString(),
            QString::number(t.value("count").toInt())});
        item->setData(0, Qt::UserRole, t);
    }
    if (!current.isEmpty())
        setSelectedType(current);
    else if (m_types->topLevelItemCount() > 0)
        m_types->setCurrentItem(m_types->topLevelItem(0));
    const QJsonObject t = m_types->currentItem() ? m_types->currentItem()->data(0, Qt::UserRole).toJsonObject()
                                                 : QJsonObject{};
    m_name->setText(t.value("name").toString());
    m_description->setText(t.value("description").toString());
    m_tag->setText(t.value("tag").toString());
    m_assign->setEnabled(!t.isEmpty() && !m_selection.isEmpty());
    m_updateAll->setEnabled(!t.isEmpty());
    m_apply->setEnabled(!t.isEmpty());
}

void TypeManagerDialog::applyEdits()
{
    const QString guid = selectedType();
    if (guid.isEmpty())
        return;
    QJsonObject changes{{"Name", m_name->text()}, {"Description", m_description->text()},
                        {"Tag", m_tag->text()}};
    const QJsonObject r = PythonEngine::instance().callJson("edit_type", {guid, compact(changes)}).object();
    if (r.value("ok").toBool()) {
        refresh();
        emit changed();
    }
}

} // namespace kimbim
