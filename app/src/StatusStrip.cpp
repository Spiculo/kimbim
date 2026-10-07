// SPDX-License-Identifier: GPL-3.0-or-later
#include "StatusStrip.h"

#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QTimer>
#include <QToolButton>

#include <algorithm>

namespace kimcad {

StatusStrip::StatusStrip(QWidget* parent)
    : QWidget(parent)
{
    setObjectName(QStringLiteral("statusStrip"));
    auto* row = new QHBoxLayout(this);
    row->setContentsMargins(6, 2, 6, 2);
    row->setSpacing(10);
    auto* pen = new QToolButton(this);
    pen->setObjectName(QStringLiteral("penButton"));
    pen->setText(tr("Pen"));
    pen->setEnabled(false);
    pen->setToolTip(tr("Pen sets come in a later version"));
    row->addWidget(pen);
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
        m_layer->clear();
        m_layer->addItems(all);
        m_layer->setCurrentText(active);
    }
    QMenu* menu = m_layers->menu();
    menu->clear();
    for (const QString& name : all) {
        QAction* a = menu->addAction(name);
        a->setCheckable(true);
        a->setChecked(!hidden.contains(name));
        connect(a, &QAction::toggled, this, [this, name](bool on) { emit layerVisibilityToggled(name, on); });
    }
    const auto shown = std::count_if(all.begin(), all.end(), [&](const QString& n) { return !hidden.contains(n); });
    m_layersText = QStringLiteral("%1/%2").arg(shown).arg(all.size());
    m_layers->setText(tr("Layers %1").arg(m_layersText));
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

} // namespace kimcad
