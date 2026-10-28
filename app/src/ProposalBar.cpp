// SPDX-License-Identifier: GPL-3.0-or-later
#include "ProposalBar.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QJsonObject>
#include <QLabel>
#include <QPushButton>

namespace kimbim {

ProposalBar::ProposalBar(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("proposalBar"));
    setMinimumWidth(0);
    setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    setAutoFillBackground(true);
    setStyleSheet(QStringLiteral("QWidget#proposalBar { background: palette(base); border: 1px solid palette(mid); }"));
    auto* row = new QHBoxLayout(this);
    row->setContentsMargins(6, 2, 6, 2);
    row->setSpacing(6);
    auto* title = new QLabel(tr("Agent proposal:"), this);
    title->setObjectName(QStringLiteral("proposalTitle"));
    row->addWidget(title);
    m_choice = new QComboBox(this);
    m_choice->setObjectName(QStringLiteral("proposalChoice"));
    m_choice->setMinimumWidth(0);
    m_choice->setSizeAdjustPolicy(QComboBox::AdjustToMinimumContentsLengthWithIcon);
    m_choice->setMinimumContentsLength(8);
    m_choice->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Fixed);
    row->addWidget(m_choice, 1);
    m_note = new QLabel(this);
    m_note->setObjectName(QStringLiteral("proposalNote"));
    row->addWidget(m_note);
    m_review = new QPushButton(tr("Review"), this);
    m_review->setObjectName(QStringLiteral("proposalReview"));
    m_accept = new QPushButton(tr("Accept"), this);
    m_accept->setObjectName(QStringLiteral("proposalAccept"));
    m_reject = new QPushButton(tr("Reject"), this);
    m_reject->setObjectName(QStringLiteral("proposalReject"));
    row->addWidget(m_review);
    row->addWidget(m_accept);
    row->addWidget(m_reject);
    connect(m_review, &QPushButton::clicked, this, [this] {
        if (const QString task = currentTask(); !task.isEmpty())
            emit reviewRequested(task);
    });
    connect(m_accept, &QPushButton::clicked, this, [this] {
        if (const QString task = currentTask(); !task.isEmpty())
            emit acceptRequested(task);
    });
    connect(m_reject, &QPushButton::clicked, this, [this] {
        if (const QString task = currentTask(); !task.isEmpty())
            emit rejectRequested(task);
    });
    hide();
}

void ProposalBar::setProposals(const QJsonArray& proposals)
{
    m_proposals = proposals;
    const QString keep = currentTask();
    m_choice->clear();
    for (const QJsonValue& value : proposals) {
        const QJsonObject p = value.toObject();
        const QJsonObject counts = p.value(QStringLiteral("counts")).toObject();
        const int changed = counts.value(QStringLiteral("added")).toInt()
            + counts.value(QStringLiteral("modified")).toInt()
            + counts.value(QStringLiteral("removed")).toInt();
        const QString client = p.value(QStringLiteral("client")).toString();
        const QString title = p.value(QStringLiteral("title")).toString();
        const QString text = tr("%1 (%2 changed)%3").arg(title).arg(changed)
                                 .arg(client.isEmpty() ? QString() : tr(" — %1").arg(client));
        m_choice->addItem(text, p.value(QStringLiteral("id")).toString());
    }
    if (const int i = m_choice->findData(keep); i >= 0)
        m_choice->setCurrentIndex(i);
    const bool any = !proposals.isEmpty();
    setEnabled(true); // a Qt widget action in a toolbar can arrive disabled
    m_choice->setEnabled(true);
    m_review->setEnabled(true);
    m_accept->setEnabled(true);
    m_reject->setEnabled(true);
    setVisible(any);
    if (!any)
        m_note->clear();
}

QString ProposalBar::currentTask() const
{
    return m_choice->currentData().toString();
}

} // namespace kimbim
