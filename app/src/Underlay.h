// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QColor>
#include <QImage>
#include <QJsonObject>
#include <QPointF>
#include <QSizeF>
#include <QString>
#include <QVector>

#include <memory>
#include <vector>

namespace kimcad {

// Where an underlay's drawing goes on its level (D85): drawing point `base` (drawing units: DXF units,
// PDF points or image pixels, y down for PDF/images) lands on level point `at` (metres), the drawing
// turned by `rotation` degrees and scaled by `scale` metres per drawing unit.
struct UnderlayPlacement {
    QPointF base;
    QPointF at;
    double rotation = 0.0; // degrees, anticlockwise
    double scale = 1.0;
    bool yDown = false; // PDF pages and images

    QPointF toWorld(QPointF drawing) const;
    QPointF toDrawing(QPointF world) const;
    // The placement after a two-point calibration (Archicad's "resize by two points"): the drawing is
    // scaled about world point `a` so that a..b measures `distance` metres. Unchanged if a == b.
    UnderlayPlacement calibrated(QPointF a, QPointF b, double distance) const;
    UnderlayPlacement moved(QPointF delta) const;
    // Turned by `degrees` about world point `centre`.
    UnderlayPlacement rotated(QPointF centre, double degrees) const;
};

// A DXF underlay's linework in drawing units relative to `origin` (Python keeps map coordinates in
// float64 there): x1 y1 x2 y2 per segment, and an RGB colour per segment.
struct UnderlayLines {
    QPointF origin;
    std::vector<float> coords;
    std::vector<unsigned char> colours;
    int count() const { return int(coords.size() / 4); }
    // From app_bridge.underlay_lines parts (meta JSON, coords f32, colours u8); null on a bad reply.
    static std::shared_ptr<const UnderlayLines> fromParts(const QList<QByteArray>& parts, QString* error = nullptr);
};

// One underlay as the app shows it (app_bridge.underlays entries).
struct Underlay {
    QString id, name, kind, file, storey, layer, tint, path;
    UnderlayPlacement placement;
    QSizeF size;   // PDF page (points) or image (pixels); empty for DXF
    int page = 0, dpi = 150;
    double opacity = 1.0;
    bool greyscale = false, visible = true, locked = false, show3d = false, missing = false;

    static Underlay fromJson(const QJsonObject& o);
    QJsonObject placementJson() const; // {x, y, rotation, scale} for set_underlay
    bool isRaster() const { return kind == QLatin1String("pdf") || kind == QLatin1String("image"); }
    // Display settings that change how it is drawn (a new presentation when any differs).
    QString displayKey() const;
};

// Colour of a DXF segment as drawn: greyscale, tinted, then faded towards the background by opacity.
QColor underlayColour(const QColor& source, bool greyscale, const QColor& tint, double opacity, const QColor& background);
// A raster underlay's pixels as drawn: greyscale or tinted (white stays white, dark goes to the tint).
QImage processUnderlayImage(const QImage& source, bool greyscale, const QColor& tint);

// Underlay linework on a level in world metres, bucketed for snapping (Snapper): endpoints, midpoints,
// crossings near the pointer and the nearest point on a line. Built once per refresh.
class UnderlaySnapIndex {
public:
    struct Segment {
        QPointF a, b;
    };
    void add(const UnderlayLines& lines, const UnderlayPlacement& placement);
    void addSegment(QPointF a, QPointF b);
    void build(); // after the last add
    int segmentCount() const { return int(m_segments.size()); }
    bool isEmpty() const { return m_segments.empty(); }

    // The best point of each kind within `tolerance` of p (false: none).
    bool endpoint(QPointF p, double tolerance, QPointF* out) const;
    bool midpoint(QPointF p, double tolerance, QPointF* out) const;
    bool crossing(QPointF p, double tolerance, QPointF* out) const;
    bool onLine(QPointF p, double tolerance, QPointF* out) const;

private:
    template <typename F>
    void forNearby(QPointF p, double tolerance, F&& f) const; // f(segment index) for segments in nearby cells
    std::vector<Segment> m_segments;
    double m_cell = 1.0;
    double m_minX = 0, m_minY = 0;
    int m_nx = 0, m_ny = 0;
    std::vector<int> m_cellStart, m_cellItems;
};

} // namespace kimcad
