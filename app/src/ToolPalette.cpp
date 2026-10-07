// SPDX-License-Identifier: GPL-3.0-or-later
#include "ToolPalette.h"

#include <QAction>
#include <QScrollArea>
#include <QToolButton>
#include <QVBoxLayout>

namespace kimcad {

ToolPalette::ToolPalette(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("toolPalette"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(0, 0, 0, 0);
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto* inner = new QWidget(scroll);
    m_column = new QVBoxLayout(inner);
    m_column->setContentsMargins(4, 4, 4, 4);
    m_column->setSpacing(2);
    m_column->addStretch(1);
    scroll->setWidget(inner);
    outer->addWidget(scroll);
}

void ToolPalette::addGroup(const QString& id, const QString& title, const QList<QAction*>& actions)
{
    auto* header = new QToolButton(this);
    header->setObjectName(QStringLiteral("toolGroup_") + id);
    header->setText(title);
    header->setCheckable(true);
    header->setChecked(true);
    header->setArrowType(Qt::DownArrow);
    header->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    header->setAutoRaise(true);
    header->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    auto* body = new QWidget(this);
    auto* list = new QVBoxLayout(body);
    list->setContentsMargins(8, 0, 0, 4);
    list->setSpacing(0);
    for (QAction* a : actions) {
        auto* b = new QToolButton(body);
        b->setObjectName(QStringLiteral("toolButton"));
        b->setDefaultAction(a);
        b->setAutoRaise(true);
        b->setToolButtonStyle(m_compact ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
        list->addWidget(b, 0, Qt::AlignLeft); // icon then label, read left to right; the column stays narrow
        m_buttons << b;
    }
    connect(header, &QToolButton::toggled, this, [header, body](bool open) {
        body->setVisible(open);
        header->setArrowType(open ? Qt::DownArrow : Qt::RightArrow);
    });
    const int at = m_column->count() - 1; // before the stretch
    m_column->insertWidget(at, header);
    m_column->insertWidget(at + 1, body);
    m_groups.append({id, header, body, actions});
}

QStringList ToolPalette::groups() const
{
    QStringList out;
    for (const Group& g : m_groups)
        out << g.id;
    return out;
}

QList<QAction*> ToolPalette::actions(const QString& id) const
{
    for (const Group& g : m_groups)
        if (g.id == id)
            return g.actions;
    return {};
}

void ToolPalette::setCollapsed(const QString& id, bool collapsed)
{
    for (const Group& g : m_groups)
        if (g.id == id)
            g.header->setChecked(!collapsed);
}

bool ToolPalette::isCollapsed(const QString& id) const
{
    for (const Group& g : m_groups)
        if (g.id == id)
            return !g.header->isChecked();
    return false;
}

void ToolPalette::setCompact(bool iconsOnly)
{
    m_compact = iconsOnly;
    for (QToolButton* b : std::as_const(m_buttons))
        b->setToolButtonStyle(iconsOnly ? Qt::ToolButtonIconOnly : Qt::ToolButtonTextBesideIcon);
}

} // namespace kimcad
