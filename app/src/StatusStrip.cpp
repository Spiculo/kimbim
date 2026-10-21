// SPDX-License-Identifier: GPL-3.0-or-later
#include "StatusStrip.h"

#include "PropertiesPanel.h" // renovationKeys, renovationLabel

#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QTimer>
#include <QIcon>
#include <QLocale>
#include <QPixmap>
#include <QToolButton>

#include <algorithm>

namespace kimbim {

StatusStrip::StatusStrip(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("statusStrip"));
    auto* row = new QHBoxLayout(this);
    row->setContentsMargins(6, 2, 6, 2);
    row->setSpacing(10);
    m_statusForNew = new QComboBox(this);
    m_statusForNew->setObjectName(QStringLiteral("statusForNew"));
    m_statusForNew->setToolTip(tr("Renovation status for new elements"));
    m_statusForNew->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    for (const QString& k : renovationKeys())
        m_statusForNew->addItem(renovationLabel(k), k);
    m_statusForNew->setCurrentIndex(m_statusForNew->findData(QStringLiteral("new")));
    connect(m_statusForNew, &QComboBox::activated, this,
        [this](int i) { emit statusForNewRequested(m_statusForNew->itemData(i).toString()); });
    row->addWidget(m_statusForNew);
    m_purpose = new QComboBox(this);
    m_purpose->setObjectName(QStringLiteral("purpose"));
    m_purpose->setToolTip(tr("Purpose: how the views, drawings and sheets look (pen set, visibility, overrides, layers)"));
    m_purpose->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    connect(m_purpose, &QComboBox::currentTextChanged, this, [this](const QString& name) {
        if (!name.isEmpty())
            emit purposeRequested(name);
    });
    row->addWidget(m_purpose);
    auto* pieces = new QToolButton(this);
    pieces->setObjectName(QStringLiteral("graphicsButton"));
    pieces->setText(QStringLiteral("..."));
    pieces->setToolTip(tr("Change this purpose's pen set, visibility, overrides and layer combination"));
    connect(pieces, &QToolButton::clicked, this, &StatusStrip::graphicsPopupRequested);
    row->addWidget(pieces);
    m_pen = new QToolButton(this);
    m_pen->setObjectName(QStringLiteral("penButton"));
    m_pen->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    m_pen->setToolTip(tr("The current pen, for new text, dimensions and marks (and the selected ones). Click to pick another."));
    setPen(23, Qt::black, 0.18);
    connect(m_pen, &QToolButton::clicked, this, &StatusStrip::penRequested);
    row->addWidget(m_pen);
    m_layer = new QComboBox(this);
    m_layer->setObjectName(QStringLiteral("activeLayer"));
    m_layer->setToolTip(tr("Active layer: new elements go on it"));
    m_layer->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    row->addWidget(m_layer);
    m_layers = new QToolButton(this);
    m_layers->setObjectName(QStringLiteral("visibleLayers"));
    m_layers->setPopupMode(QToolButton::InstantPopup);
    m_layers->setToolTip(tr("Visible layers"));
    m_layers->setMenu(new QMenu(m_layers));
    row->addWidget(m_layers);
    m_toggles = new QHBoxLayout;
    m_toggles->setSpacing(2);
    row->addLayout(m_toggles);
    m_zoom = new QLabel(this);
    m_zoom->setObjectName(QStringLiteral("zoomLabel"));
    m_zoom->setToolTip(tr("Zoom (100% = the whole model)"));
    row->addWidget(m_zoom);
    m_selection = new QLabel(this);
    m_selection->setObjectName(QStringLiteral("selectionLabel"));
    row->addWidget(m_selection);
    m_message = new QLabel(this);
    m_message->setObjectName(QStringLiteral("statusMessage"));
    m_message->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    row->addWidget(m_message, 1);
    m_timer = new QTimer(this);
    m_timer->setSingleShot(true);
    connect(m_timer, &QTimer::timeout, this, &StatusStrip::clearMessage);
    connect(m_layer, &QComboBox::activated, this, [this](int i) { emit activeLayerRequested(m_layer->itemText(i)); });
}

void StatusStrip::setLayers(const QStringList& all, const QString& active, const QSet<QString>& hidden)
{
    {
        const QSignalBlocker block(m_layer);
        // Rebuild the combo only when the layer set changed: a rebuild steals the current selection.
        bool same = m_layer->count() == all.size();
        for (int i = 0; same && i < all.size(); ++i)
            same = m_layer->itemText(i) == all[i];
        if (!same) {
            m_layer->clear();
            m_layer->addItems(all);
        }
        m_layer->setCurrentText(active);
    }
    QMenu* menu = m_layers->menu();
    // The menu stays open while the user ticks layers one by one (owner feedback): update the existing
    // actions in place instead of clearing and rebuilding them (which closes the popup).
    const QList<QAction*> acts = menu->actions();
    bool same = acts.size() == all.size();
    for (int i = 0; same && i < all.size(); ++i)
        same = acts[i]->text() == all[i];
    if (!same) {
        menu->clear();
        for (const QString& name : all) {
            QAction* a = menu->addAction(name);
            a->setCheckable(true);
            connect(a, &QAction::toggled, this, [this, name](bool on) { emit layerVisibilityToggled(name, on); });
        }
    }
    const QList<QAction*> current = menu->actions();
    for (int i = 0; i < all.size() && i < current.size(); ++i) {
        const QSignalBlocker block(current[i]); // reflect the state without re-emitting toggled
        current[i]->setChecked(!hidden.contains(all[i]));
    }
    const auto shown = std::count_if(all.begin(), all.end(), [&](const QString& n) { return !hidden.contains(n); });
    m_layersText = QStringLiteral("%1/%2").arg(shown).arg(all.size());
    m_layers->setText(tr("Layers %1").arg(m_layersText));
}

void StatusStrip::setStatusForNew(const QString& status)
{
    const QSignalBlocker block(m_statusForNew);
    m_statusForNew->setCurrentIndex(std::max(0, m_statusForNew->findData(status)));
}

void StatusStrip::setZoom(double percent)
{
    m_zoomText = percent < 0 ? QString() : QStringLiteral("%1%").arg(qRound(percent));
    m_zoom->setText(m_zoomText);
}

void StatusStrip::setSelection(const QString& summary)
{
    m_selection->setText(summary);
}

void StatusStrip::showMessage(const QString& text, int timeoutMs)
{
    m_message->setText(text);
    if (timeoutMs > 0)
        m_timer->start(timeoutMs);
    else
        m_timer->stop();
}

void StatusStrip::clearMessage()
{
    m_message->clear();
}

QString StatusStrip::message() const
{
    return m_message->text();
}

QString StatusStrip::selectionText() const
{
    return m_selection->text();
}

void StatusStrip::setPen(int number, const QColor& color, double weight)
{
    QPixmap swatch(12, 12);
    swatch.fill(color);
    m_pen->setIcon(QIcon(swatch));
    m_pen->setText(QStringLiteral("%1 · %2").arg(number).arg(QLocale().toString(weight, 'f', 2)));
}

void StatusStrip::setPurposes(const QStringList& names, const QString& current)
{
    QSignalBlocker block(m_purpose); // showing the state isn't a request
    if (m_purpose->count() != names.size() || [&] {
            for (int i = 0; i < names.size(); ++i)
                if (m_purpose->itemText(i) != names[i])
                    return true;
            return false;
        }()) {
        m_purpose->clear();
        m_purpose->addItems(names);
    }
    m_purpose->setCurrentText(current);
}

void StatusStrip::addToggle(QAction* action)
{
    if (findChild<QToolButton*>(action->objectName() + QStringLiteral("Button")))
        return; // already here
    auto* b = new QToolButton(this);
    b->setDefaultAction(action);
    b->setAutoRaise(true);
    b->setToolButtonStyle(Qt::ToolButtonTextOnly);
    b->setObjectName(action->objectName() + QStringLiteral("Button"));
    m_toggles->addWidget(b);
}

} // namespace kimbim
