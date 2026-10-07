// SPDX-License-Identifier: GPL-3.0-or-later
#include "ToolOptionsBar.h"

#include <QHBoxLayout>

namespace kimcad {

ToolOptionsBar::ToolOptionsBar(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("toolOptions"));
    m_row = new QHBoxLayout(this);
    m_row->setContentsMargins(6, 3, 6, 3);
    m_row->setSpacing(8);
    m_row->addStretch(1);
    setAutoFillBackground(true);
    hide();
}

void ToolOptionsBar::addField(QWidget* field)
{
    field->setParent(this);
    m_row->insertWidget(m_row->count() - 1, field);
    m_fields << field;
}

void ToolOptionsBar::setActive(bool toolActive)
{
    bool any = false;
    for (QWidget* f : std::as_const(m_fields))
        any = any || !f->isHidden();
    setVisible(toolActive && any);
}

} // namespace kimcad
