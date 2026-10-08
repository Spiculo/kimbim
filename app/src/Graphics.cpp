// SPDX-License-Identifier: GPL-3.0-or-later
#include "Graphics.h"

#include <QJsonArray>

#include <algorithm>
#include <cmath>

namespace kimcad {

namespace {
LineStyle line(const QJsonObject& o)
{
    LineStyle l;
    const QColor c(o.value("color").toString());
    if (c.isValid())
        l.color = c;
    if (o.value("weight").isDouble())
        l.weight = o.value("weight").toDouble();
    for (const auto& d : o.value("dash").toArray())
        if (d.toDouble() > 0)
            l.dash << d.toDouble();
    if (l.dash.size() % 2)
        l.dash.clear();
    return l;
}
}

Graphics Graphics::fromJson(const QJsonObject& state)
{
    Graphics g;
    if (!state.value("ok").toBool())
        return g;
    g.m_purpose = state.value("purpose").toString();
    g.m_currentPen = state.value("current_pen").toInt(23);
    g.m_annotationPen = state.value("annotation_pen").toInt(23);
    for (const auto& v : state.value("styles").toArray()) {
        const QJsonObject o = v.toObject();
        ElementStyle s;
        s.cut = line(o.value("cut").toObject());
        s.projection = line(o.value("projection").toObject());
        s.fill = QColor(o.value("fill").toString()); // null (doors, windows, rooms...): invalid = no fill
        const QColor surface(o.value("surface").toString());
        if (surface.isValid())
            s.surface = surface;
        if (o.value("transparency").isDouble())
            s.transparency = std::clamp(o.value("transparency").toDouble(), 0.0, 1.0);
        g.m_styles << s;
    }
    const QJsonObject elements = state.value("elements").toObject();
    for (auto it = elements.constBegin(); it != elements.constEnd(); ++it) {
        const int i = it.value().toInt(-1);
        if (i >= 0 && i < g.m_styles.size())
            g.m_elements.insert(it.key(), i);
    }
    for (const auto& h : state.value("hidden").toArray())
        g.m_hidden.insert(h.toString());
    const QJsonObject pens = state.value("pens").toObject();
    for (auto it = pens.constBegin(); it != pens.constEnd(); ++it)
        g.m_pens.insert(it.key().toInt(), line(it.value().toObject()));
    return g;
}

const ElementStyle* Graphics::styleOf(const QString& guid) const
{
    const auto it = m_elements.constFind(guid);
    return it == m_elements.constEnd() ? nullptr : &m_styles[*it];
}

LineStyle Graphics::pen(int n) const
{
    return m_pens.value(n, LineStyle{});
}

float Graphics::pixels(double weightMm, bool trueWeights)
{
    return trueWeights ? float(std::clamp(int(std::lround(weightMm * 4.0)), 1, 6)) : 1.0f;
}

uint16_t Graphics::pattern(const QVector<double>& dashMm)
{
    if (dashMm.isEmpty())
        return 0xFFFF;
    // 16 bits, one bit ~ 0.5 mm of the pattern scaled to fit: dashes set, gaps clear.
    double total = 0;
    for (double d : dashMm)
        total += d;
    uint16_t bits = 0;
    int bit = 0;
    for (int i = 0; i < dashMm.size() && bit < 16; ++i) {
        const int n = std::max(1, int(std::lround(dashMm[i] / total * 16.0)));
        for (int k = 0; k < n && bit < 16; ++k, ++bit)
            if (i % 2 == 0)
                bits |= uint16_t(1u << (15 - bit));
    }
    return bits == 0 ? 0xFFFF : bits;
}

} // namespace kimcad
