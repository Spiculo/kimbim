// SPDX-License-Identifier: GPL-3.0-or-later
#include "DrawingView.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPushButton>
#include <QSvgRenderer>
#include <QVBoxLayout>
#include <QWheelEvent>

#include <algorithm>
#include <cmath>

namespace kimcad {

DrawingView::DrawingView(const QString& guid, QWidget* parent)
    : QWidget(parent)
    , m_guid(guid)
    , m_renderer(new QSvgRenderer(this))
    , m_bar(new QWidget(this))
    , m_barText(new QLabel(m_bar))
    , m_regenerate(new QPushButton(tr("Regenerate"), m_bar))
{
    setObjectName(QStringLiteral("drawingView"));
    setAutoFillBackground(true);
    QPalette pal = palette();
    pal.setColor(QPalette::Window, QColor(0x8a, 0x8f, 0x96)); // the desk around the paper
    setPalette(pal);
    m_bar->setAutoFillBackground(true);
    QPalette barPal = m_bar->palette();
    barPal.setColor(QPalette::Window, QColor(0xff, 0xf3, 0xc4));
    m_bar->setPalette(barPal);
    auto* row = new QHBoxLayout(m_bar);
    row->setContentsMargins(8, 4, 8, 4);
    row->addWidget(m_barText, 1);
    row->addWidget(m_regenerate);
    auto* column = new QVBoxLayout(this);
    column->setContentsMargins(0, 0, 0, 0);
    column->addWidget(m_bar);
    column->addStretch(1);
    connect(m_regenerate, &QPushButton::clicked, this, [this] { emit regenerateRequested(m_guid); });
    updateBar();
}

bool DrawingView::setSvg(const QByteArray& svg)
{
    if (!m_renderer->load(svg))
        return false;
    if (!m_fitted)
        fit();
    update();
    return true;
}

bool DrawingView::hasDrawing() const
{
    return m_renderer->isValid();
}

QSizeF DrawingView::paperSize() const
{
    return m_renderer->isValid() ? m_renderer->viewBoxF().size() : QSizeF();
}

void DrawingView::setStale(bool stale)
{
    m_stale = stale;
    updateBar();
}

void DrawingView::setBusy(bool busy)
{
    m_busy = busy;
    updateBar();
}

void DrawingView::updateBar()
{
    m_barText->setText(m_busy ? tr("Generating the drawing...")
                              : tr("The model has changed since this drawing was generated."));
    m_regenerate->setEnabled(!m_busy);
    m_bar->setVisible(m_busy || m_stale);
}

void DrawingView::fit()
{
    const QSizeF paper = paperSize();
    if (paper.isEmpty() || width() < 10 || height() < 10)
        return;
    m_scale = std::min(width() * 0.9 / paper.width(), height() * 0.9 / paper.height());
    m_offset = QPointF((width() - paper.width() * m_scale) / 2, (height() - paper.height() * m_scale) / 2);
    m_fitted = true;
    update();
}

QRectF DrawingView::paperRect() const
{
    return QRectF(m_offset, paperSize() * m_scale);
}

void DrawingView::paintEvent(QPaintEvent*)
{
    QPainter p(this);
    if (!m_renderer->isValid()) {
        p.drawText(rect(), Qt::AlignCenter, m_busy ? tr("Generating the drawing...") : tr("No drawing yet"));
        return;
    }
    const QRectF paper = paperRect();
    p.fillRect(paper, Qt::white);
    p.setRenderHint(QPainter::Antialiasing);
    m_renderer->render(&p, paper);
    if (m_dragging && m_panFrom) { // where the dragged drawing goes
        const QRectF r = m_dragging->rect;
        const QPointF delta = (*m_panFrom - m_dragStart) / m_scale;
        p.setPen(QPen(QColor(0x1a, 0x4d, 0xc0), 1.5, Qt::DashLine));
        p.drawRect(QRectF(m_offset + (r.topLeft() + delta) * m_scale, r.size() * m_scale));
    }
}

void DrawingView::wheelEvent(QWheelEvent* event)
{
    if (!m_renderer->isValid())
        return;
    const double factor = std::pow(1.0015, event->angleDelta().y());
    const QPointF at = event->position();
    const double scale = std::clamp(m_scale * factor, 0.05, 200.0);
    m_offset = at - (at - m_offset) * (scale / m_scale); // the point under the cursor stays put
    m_scale = scale;
    update();
}

void DrawingView::mousePressEvent(QMouseEvent* event)
{
    if (event->button() == Qt::LeftButton) {
        const QPointF mm = toPaper(event->position());
        for (int i = int(m_placed.size()) - 1; i >= 0; --i)
            if (m_placed[i].rect.contains(mm)) { // drag a placed drawing (sheet mode)
                m_dragging = m_placed[i];
                m_dragStart = event->position();
                return;
            }
    }
    if (event->button() == Qt::MiddleButton || event->button() == Qt::LeftButton)
        m_panFrom = event->position();
}

void DrawingView::mouseMoveEvent(QMouseEvent* event)
{
    if (m_dragging) {
        update(); // the outline follows in paintEvent
        m_panFrom = event->position();
        return;
    }
    if (!m_panFrom)
        return;
    m_offset += event->position() - *m_panFrom;
    m_panFrom = event->position();
    update();
}

void DrawingView::mouseReleaseEvent(QMouseEvent* event)
{
    if (m_dragging) {
        const QPointF delta = (event->position() - m_dragStart) / m_scale;
        const Placed p = *m_dragging;
        m_dragging.reset();
        m_panFrom.reset();
        if (delta.manhattanLength() > 0.5) {
            m_placed.clear(); // stale until the sheet comes back
            emit placedMoved(p.guid, p.rect.topLeft() + delta);
        }
        update();
        return;
    }
    m_panFrom.reset();
}

void DrawingView::resizeEvent(QResizeEvent*)
{
    if (!m_fitted)
        fit();
}

} // namespace kimcad
