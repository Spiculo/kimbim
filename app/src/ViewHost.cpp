// SPDX-License-Identifier: GPL-3.0-or-later
#include "ViewHost.h"

#include "Viewport.h"

#include <QHBoxLayout>
#include <QVBoxLayout>

namespace kimbim {

ViewHost::ViewHost(Viewport* view, QWidget* parent)
    : QWidget(parent)
    , m_view(view)
{
    auto* column = new QVBoxLayout(this);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(0);
    m_top = new QVBoxLayout;
    m_top->setContentsMargins(0, 0, 0, 0);
    column->addLayout(m_top);
    m_row = new QHBoxLayout;
    m_row->setContentsMargins(0, 0, 0, 0);
    m_row->setSpacing(0);
    m_row->addWidget(view, 1);
    column->addLayout(m_row, 1);
}

void ViewHost::adoptChrome(QWidget* optionsStrip, QWidget* cutColumn)
{
    if (optionsStrip && optionsStrip->parentWidget() != this)
        m_top->addWidget(optionsStrip); // reparents it from the previous tab
    if (cutColumn) {
        if (cutColumn->parentWidget() != this)
            m_row->addWidget(cutColumn);
        m_cutColumn = cutColumn; // a null cutColumn means "leave it alone" (a plan tab never adopts it)
    }
}

} // namespace kimbim
