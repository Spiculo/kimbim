// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QSet>
#include <QStringList>
#include <QWidget>

class QComboBox;
class QLabel;
class QTimer;
class QToolButton;

namespace kimcad {

// The bottom bar (D71), left to right: the current pen (pen sets come in step 3), the active layer,
// the visible layers, the zoom, the selection and the status messages.
class StatusStrip : public QWidget {
    Q_OBJECT
public:
    explicit StatusStrip(QWidget* parent = nullptr);
    void setLayers(const QStringList& all, const QString& active, const QSet<QString>& hidden);
    void setZoom(double percent);              // < 0: not shown (drawing tabs)
    void setSelection(const QString& summary); // "" when nothing is selected
    void showMessage(const QString& text, int timeoutMs = 0);
    void clearMessage();
    QString message() const;
    QString zoomText() const { return m_zoomText; }
    QString selectionText() const;
    QString layersText() const { return m_layersText; } // "visible/all"

signals:
    void activeLayerRequested(const QString& layer);
    void layerVisibilityToggled(const QString& layer, bool visible);

private:
    QComboBox* m_layer;
    QToolButton* m_layers;
    QLabel* m_zoom;
    QLabel* m_selection;
    QLabel* m_message;
    QTimer* m_timer;
    QString m_zoomText, m_layersText;
};

} // namespace kimcad
