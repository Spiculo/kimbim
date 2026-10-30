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
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
    setAutoFillBackground(true);
    // A waiting proposal must be impossible to miss in a light or a dark theme: a light amber banner
    // with dark text, painted by the style sheet (WA_StyledBackground, or background is not drawn).
    setAttribute(Qt::WA_StyledBackground, true);
    setStyleSheet(QStringLiteral(
        "QWidget#proposalBar { background: #fdf1c7; border: 1px solid #c9a227; }"
        "QWidget#proposalBar QLabel { color: #2b2b2b; }"
        "QWidget#proposalBar QPushButton { color: #2b2b2b; }"
        // The selector, its arrow and its drop-down list: the app may be in a dark theme while the
        // banner is light, so every part is colored explicitly (owner: the selector had no contrast).
        "QWidget#proposalBar QComboBox { color: #1a1a1a; background: #ffffff; border: 1px solid #8a7a3a;"
        " border-radius: 3px; padding: 2px 6px; }"
        "QWidget#proposalBar QComboBox:hover { border-color: #2f6fbf; }"
        "QWidget#proposalBar QComboBox::drop-down { border: 0; width: 18px; }"
        // A drawn arrow: the style's own arrow is light on a light list in this theme, so it vanished.
        "QWidget#proposalBar QComboBox::down-arrow { image: none; width: 0; height: 0;"
        " border-left: 4px solid transparent; border-right: 4px solid transparent;"
        " border-top: 5px solid #1a1a1a; margin-right: 6px; }"
        "QWidget#proposalBar QComboBox QAbstractItemView { color: #1a1a1a; background: #ffffff;"
        " selection-color: #ffffff; selection-background-color: #2f6fbf; outline: 0; border: 1px solid #8a7a3a; }"));
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
    m_choice->setMinimumContentsLength(12);
    m_choice->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
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
    m_hide = new QPushButton(QStringLiteral("\u2715"), this); // hide, not resolve: the proposal stays
    m_hide->setObjectName(QStringLiteral("proposalHide"));
    m_hide->setToolTip(tr("Hide the proposal bar until a new proposal arrives (the proposal is kept)"));
    m_hide->setFixedWidth(26);
    row->addWidget(m_review);
    row->addWidget(m_accept);
    row->addWidget(m_reject);
    row->addWidget(m_hide);
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
    connect(m_hide, &QPushButton::clicked, this, &ProposalBar::hideUntilChanged);
    // No hide() here: inside a toolbar a QWidgetAction owns the widget's visibility. The toolbar is
    // hidden until a proposal arrives, and the owner shows/hides both together (see proposalsChanged).
}

void ProposalBar::setProposals(const QJsonArray& proposals)
{
    m_proposals = proposals;
    QStringList ids;
    for (const QJsonValue& value : proposals)
        ids << value.toObject().value(QStringLiteral("id")).toString();
    if (ids != m_ids)
        m_dismissed = false; // something changed: a hidden bar comes back on its own
    m_ids = ids;
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
    if (!any)
        m_note->clear();
    emit proposalsChanged(any && !m_dismissed); // the owner shows the toolbar and this bar together
}

void ProposalBar::hideUntilChanged()
{
    m_dismissed = true;
    emit proposalsChanged(false);
}

void ProposalBar::showAgain()
{
    m_dismissed = false;
    emit proposalsChanged(!m_proposals.isEmpty());
}

QString ProposalBar::currentTask() const
{
    return m_choice->currentData().toString();
}

} // namespace kimbim
