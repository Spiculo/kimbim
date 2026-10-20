// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QColor>
#include <QHash>
#include <QJsonObject>
#include <QSet>
#include <QString>
#include <QVector>

#include <cstdint>
#include <optional>

// The resolved purpose (D73): what graphics_state returns, parsed for the views. Python decides every
// element's pens, line types and visibility; the views only draw what this says.
namespace kimbim {
struct LineStyle {
    QColor color = Qt::black;
    double weight = 0.18;          // mm on paper
    QVector<double> dash;          // mm on paper; empty = solid
    bool operator==(const LineStyle& o) const { return color == o.color && weight == o.weight && dash == o.dash; }
};
struct ElementStyle {
    LineStyle cut, projection;
    QColor fill; // the cut fill; invalid = none (doors, windows, rooms)
    std::optional<QColor> surface;
    std::optional<double> transparency;
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
    const QSet<QString>& hidden() const { return m_hidden; }
    const QHash<int, LineStyle>& pens() const { return m_pens; }
    const QHash<int, QString>& penNames() const { return m_penNames; }
    LineStyle pen(int n) const;                    // fallback black 0.18
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
    QHash<int, LineStyle> m_pens;
    QHash<int, QString> m_penNames;
    int m_currentPen = 23, m_annotationPen = 23;
    QString m_purpose;
    QStringList m_purposes;
    QVector<LegendEntry> m_legend;
};
}
