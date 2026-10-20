// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QHash>
#include <QString>
#include <QWidget>

#include "Graphics.h"

namespace kimbim {

// The pens as Archicad shows them (D73): a 16 x 16 grid of swatches, pen n at row n / 16, column n % 16
// (cell 0 is empty). Used by the pen button's popup, the pen-set editor and the pen pickers.
class PenGrid : public QWidget {
    Q_OBJECT
public:
    explicit PenGrid(QWidget* parent = nullptr);
    void setPens(const QHash<int, LineStyle>& pens);
    void setNames(const QHash<int, QString>& names);
    void setCurrent(int pen);
    int current() const { return m_current; }
    // The pen under a point of a grid this size; 0 for none.
    static int penAt(const QSize& size, const QPoint& p);
    // A popup grid below `anchor`; the pen picked, or 0 if dismissed.
    static int pick(QWidget* anchor, const QHash<int, LineStyle>& pens, const QHash<int, QString>& names, int current);
    QSize sizeHint() const override { return QSize(16 * 20, 16 * 20); }

signals:
    void penClicked(int pen);

protected:
    void paintEvent(QPaintEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    bool event(QEvent* event) override;

private:
    QHash<int, LineStyle> m_pens;
    QHash<int, QString> m_names;
    int m_current = 0;
};

} // namespace kimbim
