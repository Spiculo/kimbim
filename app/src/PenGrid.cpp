// SPDX-License-Identifier: GPL-3.0-or-later
#include "PenGrid.h"

#include <QDialog>
#include <QHelpEvent>
#include <QLocale>
#include <QMouseEvent>
#include <QPainter>
#include <QToolTip>
#include <QVBoxLayout>

namespace kimbim {

PenGrid::PenGrid(QWidget* parent)
    : QWidget(parent)
{
    setMinimumSize(16 * 14, 16 * 14);
    setMouseTracking(true);
}

void PenGrid::setPens(const QHash<int, LineStyle>& pens)
{
    m_pens = pens;
    update();
}

void PenGrid::setNames(const QHash<int, QString>& names)
{
    m_names = names;
}

void PenGrid::setCurrent(int pen)
{
    m_current = pen;
    update();
}

int PenGrid::penAt(const QSize& size, const QPoint& p)
{
    if (size.width() < 16 || size.height() < 16 || p.x() < 0 || p.y() < 0)
        return 0;
    const int col = p.x() * 16 / size.width(), row = p.y() * 16 / size.height();
    const int pen = row * 16 + col;
    return col < 16 && row < 16 && pen >= 1 && pen <= 255 ? pen : 0;
}

void PenGrid::paintEvent(QPaintEvent*)
{
    QPainter p(this);
    const double w = width() / 16.0, h = height() / 16.0;
    p.fillRect(rect(), palette().window());
    for (int pen = 1; pen <= 255; ++pen) {
        const QRectF cell(pen % 16 * w, pen / 16 * h, w, h);
        p.fillRect(cell.adjusted(1, 1, -1, -1), m_pens.value(pen, LineStyle{}).color);
        p.setPen(QPen(palette().mid().color(), 1));
        p.drawRect(cell.adjusted(1, 1, -1, -1));
        if (pen == m_current) {
            p.setPen(QPen(palette().highlight().color(), 3));
            p.drawRect(cell.adjusted(1.5, 1.5, -1.5, -1.5));
        }
    }
}

void PenGrid::mousePressEvent(QMouseEvent* event)
{
    const int pen = penAt(size(), event->position().toPoint());
    if (pen == 0)
        return;
    setCurrent(pen);
    emit penClicked(pen);
}

bool PenGrid::event(QEvent* event)
{
    if (event->type() == QEvent::ToolTip) {
        auto* help = static_cast<QHelpEvent*>(event);
        const int pen = penAt(size(), help->pos());
        if (pen == 0) {
            QToolTip::hideText();
        } else {
            const LineStyle s = m_pens.value(pen, LineStyle{});
            QString text = QStringLiteral("%1 · %2 mm").arg(pen).arg(QLocale().toString(s.weight, 'f', 2));
            if (!m_names.value(pen).isEmpty())
                text += QStringLiteral(" · ") + m_names.value(pen);
            QToolTip::showText(help->globalPos(), text, this);
        }
        return true;
    }
    return QWidget::event(event);
}

int PenGrid::pick(QWidget* anchor, const QHash<int, LineStyle>& pens, const QHash<int, QString>& names, int current)
{
    QDialog popup(anchor, Qt::Popup);
    auto* layout = new QVBoxLayout(&popup);
    layout->setContentsMargins(4, 4, 4, 4);
    auto* grid = new PenGrid(&popup);
    grid->setFixedSize(16 * 20, 16 * 20);
    grid->setPens(pens);
    grid->setNames(names);
    grid->setCurrent(current);
    layout->addWidget(grid);
    int picked = 0;
    QObject::connect(grid, &PenGrid::penClicked, &popup, [&](int pen) {
        picked = pen;
        popup.accept();
    });
    popup.adjustSize();
    QPoint at = anchor->mapToGlobal(QPoint(0, 0));
    at.ry() -= popup.height(); // the pen button sits in the bottom bar: open upwards
    popup.move(at);
    popup.exec();
    return picked;
}

} // namespace kimbim
