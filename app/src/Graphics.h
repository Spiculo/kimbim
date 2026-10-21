// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QColor>
#include <QHash>
#include <QJsonObject>
#include <QSet>
#include <QString>
#include <QPointF>
#include <QVector>

#include <array>
#include <cstdint>
#include <optional>
#include <vector>

// The resolved purpose (D73): what graphics_state returns, parsed for the views. Python decides every
// element's pens, line types and visibility; the views only draw what this says.
namespace kimbim {
struct LineStyle {
    QColor color = Qt::black;
    double weight = 0.18;          // mm on paper
    QVector<double> dash;          // mm on paper; empty = solid
    bool operator==(const LineStyle& o) const { return color == o.color && weight == o.weight && dash == o.dash; }
};
// D84/D96: a fill pattern from the project's table: hatch-line families in mm on paper, or loops.
struct HatchFamily {
    double angle = 0, spacing = 0, shift = 0, ox = 0, oy = 0;
    QVector<double> dash; // mm on paper; empty: continuous
};
struct FillPattern {
    bool solid = false;
    bool loops = false; // D93: insulation loops (radius, spacing)
    double radius = 1.0, spacing = 3.0;
    QVector<HatchFamily> lines;
};
struct ElementStyle {
    LineStyle cut, projection;
    QColor fill; // the cut fill; invalid = none (doors, windows, rooms)
    QString pattern;   // D96: the cut fill's pattern ("" or Solid: solid in the fill colour)
    QColor background; // D96: behind a pattern; invalid = the view's background
    std::optional<QColor> surface;
    std::optional<double> transparency;
};
// D96: a layered element's layers (Archicad's composite cut): band k lies between bounds[k] and
// bounds[k + 1] metres along `axis` from `origin`, filled with fills[k] (invalid: none).
struct LayerBands {
    double origin[3] = {0, 0, 0};
    double axis[3] = {0, 1, 0};
    QVector<double> bounds;
    QVector<QColor> fills;
    QVector<QString> patterns;   // D96: each layer's pattern ("" = solid)
    QVector<QColor> backgrounds; // D96: behind each layer's pattern
};
// D74: one legend row: what the purpose changes (a renovation status or an override rule) and its style.
struct LegendEntry {
    QString label, source, key; // source: "renovation" or "override"; key: the status or the rule name
    int style = -1;             // index into the styles
};
class Graphics {
public:
    static Graphics fromJson(const QJsonObject& state); // graphics_state's reply
    const ElementStyle* styleOf(const QString& guid) const;   // null: no style (keep defaults)
    bool isHidden(const QString& guid) const { return m_hidden.contains(guid); }
    const LayerBands* layersOf(const QString& guid) const; // null: drawn as one fill
    const QSet<QString>& hidden() const { return m_hidden; }
    const QHash<int, LineStyle>& pens() const { return m_pens; }
    const QHash<int, QString>& penNames() const { return m_penNames; }
    LineStyle pen(int n) const;                    // fallback black 0.18
    // D96: a pattern of the project's table; null for an unknown name, "" or Solid.
    const FillPattern* fillPattern(const QString& name) const;
    // Hatch segments (x1, y1, x2, y2, in the loops' units, metres) of `p` over the area the loops enclose
    // (even-odd: holes stay empty), anchored at the origin so neighbours line up; empty past `limit`.
    static std::vector<std::array<double, 4>> hatch(const std::vector<std::vector<QPointF>>& loops, const FillPattern& p,
        double metresPerMm, int limit = 20000);
    int currentPen() const { return m_currentPen; }
    int annotationPen() const { return m_annotationPen; }
    QString purpose() const { return m_purpose; }
    const QStringList& purposes() const { return m_purposes; } // every purpose, for the bottom bar
    const QVector<LegendEntry>& legend() const { return m_legend; }
    const ElementStyle* style(int i) const { return i >= 0 && i < m_styles.size() ? &m_styles[i] : nullptr; }
    bool isEmpty() const { return m_styles.isEmpty() && m_hidden.isEmpty(); }
    // Screen width in pixels: 1, or with true weights clamp(round(weight * 4), 1, 6).
    static float pixels(double weightMm, bool trueWeights);
    // OCCT 16-bit screen pattern for a dash list (empty: 0xFFFF): each mm ~ 2 bits, dash bits set.
    static uint16_t pattern(const QVector<double>& dashMm);
private:
    QVector<ElementStyle> m_styles;
    QHash<QString, int> m_elements;
    QSet<QString> m_hidden;
    QHash<QString, LayerBands> m_layers;
    QHash<QString, FillPattern> m_patterns;
    QHash<int, LineStyle> m_pens;
    QHash<int, QString> m_penNames;
    int m_currentPen = 23, m_annotationPen = 23;
    QString m_purpose;
    QStringList m_purposes;
    QVector<LegendEntry> m_legend;
};
}
