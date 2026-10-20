// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QPointF>
#include <QStringList>

#include <functional>
#include <optional>

#include "Snapper.h"
#include "Underlay.h"

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QListWidget;
class QPushButton;
class QSlider;
class QSpinBox;

namespace kimbim {

// D85: File > Place underlay..., after the file is chosen and read (app_bridge.underlay_probe): a DXF's
// unit (asked when $INSUNITS is unitless, else shown), a PDF's page, the drawing scale (1:N, and an
// image's resolution) for PDF and images, where it goes and its layer.
class PlaceUnderlayDialog : public QDialog {
    Q_OBJECT
public:
    PlaceUnderlayDialog(const QString& fileName, const QJsonObject& probe, const QStringList& layers,
        const QString& defaultLayer = QStringLiteral("Underlays"), QWidget* parent = nullptr);
    QJsonObject options() const; // for app_bridge.add_underlay (storey added by the caller)
    QComboBox* unitBox() const { return m_unit; }
    QSpinBox* pageBox() const { return m_page; }
    QSpinBox* scaleBox() const { return m_scale; }
    QDoubleSpinBox* dpiBox() const { return m_dpi; }
    QComboBox* layerBox() const { return m_layer; }
    QComboBox* placementBox() const { return m_placement; } // D92: centred or survey coordinates
    // Metres per drawing unit for a drawing scale 1:n: PDF points are 1/72 inch, image pixels 1/dpi.
    static double rasterScale(const QString& kind, int n, double dpi);

private:
    QString m_kind;
    QComboBox* m_unit = nullptr;
    QSpinBox* m_page = nullptr;
    QSpinBox* m_scale = nullptr;
    QDoubleSpinBox* m_dpi = nullptr;
    QDoubleSpinBox* m_x = nullptr;
    QDoubleSpinBox* m_y = nullptr;
    QDoubleSpinBox* m_rotation = nullptr;
    QComboBox* m_layer = nullptr;
    QComboBox* m_placement = nullptr; // D92
};

// D85: File > Underlays...: every underlay of the project (by level), its display (shown, locked, in 3D,
// opacity, greyscale, tint, layer) and placement (x, y, rotation, scale, page), changed as you edit, and
// buttons to calibrate, move, remove or place another. `bridge` runs app_bridge calls.
class UnderlaysDialog : public QDialog {
    Q_OBJECT
public:
    using Bridge = std::function<QJsonObject(const char*, const QStringList&)>;
    UnderlaysDialog(Bridge bridge, const QHash<QString, QString>& levelNames, const QStringList& layers, QWidget* parent = nullptr);
    void reload(const QString& select = {});
    QString currentId() const;
    void selectId(const QString& id);
    QListWidget* list() const { return m_list; }
    QSlider* opacitySlider() const { return m_opacity; }
    QCheckBox* visibleBox() const { return m_visible; }
    QDoubleSpinBox* rotationBox() const { return m_rotation; }

signals:
    void changed();                       // an underlay changed or went: redraw
    void calibrateRequested(const QString& id);
    void moveRequested(const QString& id);
    void placeRequested();

private:
    void fill(const Underlay& u, const QJsonObject& raw);
    void apply(const QJsonObject& changes);

    Bridge m_bridge;
    QHash<QString, QString> m_levelNames;
    QJsonObject m_current;
    bool m_filling = false;
    QListWidget* m_list = nullptr;
    QCheckBox* m_visible = nullptr;
    QCheckBox* m_locked = nullptr;
    QCheckBox* m_show3d = nullptr;
    QCheckBox* m_grey = nullptr;
    QSlider* m_opacity = nullptr;
    QPushButton* m_tint = nullptr;
    QComboBox* m_layer = nullptr;
    QDoubleSpinBox* m_x = nullptr;
    QDoubleSpinBox* m_y = nullptr;
    QDoubleSpinBox* m_rotation = nullptr;
    QDoubleSpinBox* m_scale = nullptr;
    QSpinBox* m_page = nullptr;
    QLabel* m_info = nullptr;
    QWidget* m_editor = nullptr;
};

// D85: picking two points in a plan for an underlay: Calibrate (two points of a known distance, then
// the real distance) or Move (from, to). Snaps like the drawing tools (the underlay's own linework
// included). Pure logic; MainWindow feeds it the view's points.
class UnderlayPicker {
public:
    enum Mode { Calibrate, Move };
    void start(const QString& id, Mode mode);
    void cancel();
    bool isActive() const { return !m_id.isEmpty(); }
    QString id() const { return m_id; }
    Mode mode() const { return m_mode; }
    int stage() const { return int(m_points.size()); } // points picked so far
    Snap move(QPointF p, double tolerance, bool ortho);
    // A click: true once both points are picked (then points() holds them and the picker stays
    // active until finish/cancel).
    bool click(QPointF p, double tolerance, bool ortho);
    const QVector<QPointF>& points() const { return m_points; }
    QPointF hover() const { return m_hover; }
    Snapper& snapper() { return m_snapper; }
    QString hint() const;

private:
    QString m_id;
    Mode m_mode = Calibrate;
    QVector<QPointF> m_points;
    QPointF m_hover;
    Snapper m_snapper;
};

} // namespace kimbim
