// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QPointF>
#include <QWidget>

#include <optional>

class QLabel;
class QPushButton;
class QSvgRenderer;

namespace kimcad {

// One drawing in a tab (Slice 14): the generated SVG, wheel zoom at the cursor, middle-drag pan,
// fit; an "out of date" bar with Regenerate while the model has changed since it was generated.
class DrawingView : public QWidget {
    Q_OBJECT
public:
    explicit DrawingView(const QString& guid, QWidget* parent = nullptr);

    QString guid() const { return m_guid; }
    // Show this SVG (paper millimetres); the old one stays until a new one arrives.
    bool setSvg(const QByteArray& svg);
    bool hasDrawing() const;
    QSizeF paperSize() const; // millimetres
    void setStale(bool stale);
    bool isStale() const { return m_stale; }
    void setBusy(bool busy);
    void fit();
    double zoom() const { return m_scale; }

signals:
    void regenerateRequested(const QString& guid);

protected:
    void paintEvent(QPaintEvent* event) override;
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    QRectF paperRect() const; // where the drawing is painted, widget pixels
    void updateBar();

    QString m_guid;
    QSvgRenderer* m_renderer;
    QWidget* m_bar;
    QLabel* m_barText;
    QPushButton* m_regenerate;
    double m_scale = 1.0; // pixels per paper millimetre
    QPointF m_offset;     // widget position of the paper's top-left corner
    bool m_fitted = false;
    bool m_stale = false;
    bool m_busy = false;
    std::optional<QPointF> m_panFrom;
};

} // namespace kimcad
