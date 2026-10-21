// SPDX-License-Identifier: GPL-3.0-or-later
#include "Graphics.h"

#include <QJsonArray>

#include <algorithm>
#include <cmath>

namespace kimbim {

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
    for (const auto& p : state.value("purposes").toArray())
        g.m_purposes << p.toString();
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
        s.pattern = o.value("pattern").toString();
        s.background = QColor(o.value("background").toString());
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
    const QJsonObject layers = state.value("layers").toObject();
    for (auto it = layers.constBegin(); it != layers.constEnd(); ++it) {
        const QJsonObject o = it.value().toObject();
        const QJsonArray origin = o.value("origin").toArray(), axis = o.value("axis").toArray();
        const QJsonArray bounds = o.value("bounds").toArray(), fills = o.value("fills").toArray();
        if (origin.size() != 3 || axis.size() != 3 || bounds.size() < 3 || fills.size() != bounds.size() - 1)
            continue;
        LayerBands b;
        for (int k = 0; k < 3; ++k) {
            b.origin[k] = origin[k].toDouble();
            b.axis[k] = axis[k].toDouble();
        }
        for (const auto& v : bounds)
            b.bounds << v.toDouble();
        for (const auto& v : fills)
            b.fills << QColor(v.toString()); // null: invalid = no fill
        const QJsonArray patterns = o.value("patterns").toArray(), backgrounds = o.value("backgrounds").toArray();
        for (int k = 0; k < fills.size(); ++k) {
            b.patterns << (k < patterns.size() ? patterns[k].toString() : QString());
            b.backgrounds << QColor(k < backgrounds.size() ? backgrounds[k].toString() : QString());
        }
        g.m_layers.insert(it.key(), b);
    }
    for (const auto& v : state.value("legend").toArray()) {
        const QJsonObject e = v.toObject();
        g.m_legend.push_back({e.value("label").toString(), e.value("source").toString(), e.value("key").toString(),
            e.value("style").toInt(-1)});
    }
    const QJsonObject patterns = state.value("fill_patterns").toObject();
    for (auto it = patterns.constBegin(); it != patterns.constEnd(); ++it) {
        const QJsonObject o = it.value().toObject();
        FillPattern p;
        p.solid = o.value("solid").toBool();
        p.loops = o.value("loops").toBool();
        p.radius = o.value("radius").toDouble(1.0);
        p.spacing = o.value("spacing").toDouble(3.0);
        for (const auto& fv : o.value("lines").toArray()) {
            const QJsonObject f = fv.toObject();
            HatchFamily h;
            h.angle = f.value("angle").toDouble();
            h.spacing = f.value("spacing").toDouble();
            h.shift = f.value("shift").toDouble();
            const QJsonArray origin = f.value("origin").toArray();
            h.ox = origin.size() == 2 ? origin[0].toDouble() : 0.0;
            h.oy = origin.size() == 2 ? origin[1].toDouble() : 0.0;
            for (const auto& d : f.value("dash").toArray())
                h.dash << d.toDouble();
            p.lines << h;
        }
        g.m_patterns.insert(it.key(), p);
    }
    const QJsonObject pens = state.value("pens").toObject();
    for (auto it = pens.constBegin(); it != pens.constEnd(); ++it)
        g.m_pens.insert(it.key().toInt(), line(it.value().toObject()));
    const QJsonObject names = state.value("pen_names").toObject();
    for (auto it = names.constBegin(); it != names.constEnd(); ++it)
        g.m_penNames.insert(it.key().toInt(), it.value().toString());
    return g;
}

const FillPattern* Graphics::fillPattern(const QString& name) const
{
    if (name.isEmpty() || name == QLatin1String("Solid"))
        return nullptr;
    const auto it = m_patterns.constFind(name);
    return it == m_patterns.constEnd() || it->solid ? nullptr : &*it;
}

namespace {

bool insideLoops(const std::vector<std::vector<QPointF>>& loops, double x, double y)
{
    bool inside = false;
    for (const auto& loop : loops)
        for (size_t i = 0; i < loop.size(); ++i) {
            const QPointF a = loop[i], b = loop[(i + 1) % loop.size()];
            if ((a.y() > y) != (b.y() > y) && x < (b.x() - a.x()) * (y - a.y()) / (b.y() - a.y()) + a.x())
                inside = !inside;
        }
    return inside;
}

} // namespace

std::vector<std::array<double, 4>> Graphics::hatch(const std::vector<std::vector<QPointF>>& loops, const FillPattern& p,
    double metresPerMm, int limit)
{
    // The same rules as kimbim.drafting.hatch: families of parallel lines clipped by the outline (here
    // every loop at once, even-odd), dashes along each line, or D93's loops.
    std::vector<std::array<double, 4>> out;
    double x0 = 1e300, y0 = 1e300, x1 = -1e300, y1 = -1e300;
    for (const auto& loop : loops)
        for (const QPointF& q : loop) {
            x0 = std::min(x0, q.x()), y0 = std::min(y0, q.y()), x1 = std::max(x1, q.x()), y1 = std::max(y1, q.y());
        }
    if (x0 > x1 || p.solid)
        return out;
    if (p.loops) {
        const double r = p.radius * metresPerMm, step = p.spacing * metresPerMm;
        if (r <= 0 || step <= 0)
            return out;
        const int n = 10;
        int row = 0;
        for (double y = std::floor(y0 / step) * step + step / 2; y < y1 + r; y += step, ++row)
            for (double x = std::floor(x0 / step) * step + (row % 2 ? step / 2 : 0.0); x < x1 + r; x += step)
                for (int k = 0; k < n; ++k) {
                    const double a0 = 2 * M_PI * k / n, a1 = 2 * M_PI * (k + 1) / n;
                    const double px0 = x + r * std::cos(a0), py0 = y + r * std::sin(a0);
                    const double px1 = x + r * std::cos(a1), py1 = y + r * std::sin(a1);
                    if (insideLoops(loops, (px0 + px1) / 2, (py0 + py1) / 2)) {
                        out.push_back({px0, py0, px1, py1});
                        if (int(out.size()) > limit)
                            return {};
                    }
                }
        return out;
    }
    for (const HatchFamily& f : p.lines) {
        const double spacing = f.spacing * metresPerMm;
        if (spacing <= 0)
            continue;
        const double a = f.angle * M_PI / 180.0;
        const double dx = std::cos(a), dy = std::sin(a), nx = -dy, ny = dx;
        const double ox = f.ox * metresPerMm, oy = f.oy * metresPerMm, shift = f.shift * metresPerMm;
        QVector<double> dash;
        double period = 0;
        for (double d : f.dash) {
            dash << d * metresPerMm;
            period += d * metresPerMm;
        }
        double lo = 1e300, hi = -1e300;
        for (const auto& loop : loops)
            for (const QPointF& q : loop) {
                const double o = (q.x() - ox) * nx + (q.y() - oy) * ny;
                lo = std::min(lo, o), hi = std::max(hi, o);
            }
        const long long i0 = (long long)std::ceil(lo / spacing), i1 = (long long)std::floor(hi / spacing);
        if ((i1 - i0 + 1) * (dash.isEmpty() ? 1 : 4) > limit)
            return {};
        for (long long i = i0; i <= i1; ++i) {
            const double off = i * spacing;
            if (!(lo + 1e-9 < off && off < hi - 1e-9))
                continue;
            const double bx = ox + nx * off, by = oy + ny * off;
            std::vector<double> ts;
            for (const auto& loop : loops)
                for (size_t k = 0; k < loop.size(); ++k) {
                    const QPointF pa = loop[k], pb = loop[(k + 1) % loop.size()];
                    const double s0 = (pa.x() - ox) * nx + (pa.y() - oy) * ny - off;
                    const double s1 = (pb.x() - ox) * nx + (pb.y() - oy) * ny - off;
                    if ((s0 > 0) != (s1 > 0)) {
                        const double u = s0 / (s0 - s1);
                        const double px = pa.x() + (pb.x() - pa.x()) * u, py = pa.y() + (pb.y() - pa.y()) * u;
                        ts.push_back((px - bx) * dx + (py - by) * dy);
                    }
                }
            std::sort(ts.begin(), ts.end());
            for (size_t k = 0; k + 1 < ts.size(); k += 2) {
                const double ta = ts[k], tb = ts[k + 1];
                auto push = [&](double t0, double t1) {
                    out.push_back({bx + dx * t0, by + dy * t0, bx + dx * t1, by + dy * t1});
                };
                if (dash.isEmpty() || period <= 0) {
                    push(ta, tb);
                } else {
                    const double phase = i * shift;
                    double start = phase + std::floor((ta - phase) / period) * period;
                    for (; start < tb; start += period) {
                        double pos = start;
                        for (int d = 0; d < dash.size(); ++d) {
                            if (d % 2 == 0) {
                                const double s = std::max(pos, ta), e = std::min(pos + dash[d], tb);
                                if (e > s)
                                    push(s, e);
                            }
                            pos += dash[d];
                        }
                    }
                }
                if (int(out.size()) > limit)
                    return {};
            }
        }
    }
    return out;
}

const LayerBands* Graphics::layersOf(const QString& guid) const
{
    const auto it = m_layers.constFind(guid);
    return it == m_layers.constEnd() ? nullptr : &*it;
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

} // namespace kimbim
