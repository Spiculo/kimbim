// SPDX-License-Identifier: GPL-3.0-or-later
#include "Underlay.h"

#include <QJsonArray>
#include <QJsonDocument>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace kimcad {

namespace {
constexpr double kPi = 3.14159265358979323846;

double dist(QPointF a, QPointF b)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y());
}

QPointF turn(QPointF v, double degrees)
{
    const double r = degrees * kPi / 180.0, c = std::cos(r), s = std::sin(r);
    return {v.x() * c - v.y() * s, v.x() * s + v.y() * c};
}
} // namespace

// ---------------------------------------------------------------- placement

QPointF UnderlayPlacement::toWorld(QPointF d) const
{
    QPointF local((d.x() - base.x()) * scale, (yDown ? base.y() - d.y() : d.y() - base.y()) * scale);
    return at + turn(local, rotation);
}

QPointF UnderlayPlacement::toDrawing(QPointF w) const
{
    const QPointF local = turn(w - at, -rotation) / (scale > 0 ? scale : 1.0);
    return {base.x() + local.x(), yDown ? base.y() - local.y() : base.y() + local.y()};
}

UnderlayPlacement UnderlayPlacement::calibrated(QPointF a, QPointF b, double distance) const
{
    const double measured = dist(a, b);
    if (measured <= 1e-12 || distance <= 0)
        return *this;
    UnderlayPlacement out = *this;
    const double factor = distance / measured;
    out.scale = scale * factor;
    out.at = a + (at - a) * factor; // the drawing grows about a: a stays where it is
    return out;
}

UnderlayPlacement UnderlayPlacement::moved(QPointF delta) const
{
    UnderlayPlacement out = *this;
    out.at += delta;
    return out;
}

UnderlayPlacement UnderlayPlacement::rotated(QPointF centre, double degrees) const
{
    UnderlayPlacement out = *this;
    out.at = centre + turn(at - centre, degrees);
    out.rotation = std::fmod(rotation + degrees, 360.0);
    return out;
}

// ---------------------------------------------------------------- data from Python

std::shared_ptr<const UnderlayLines> UnderlayLines::fromParts(const QList<QByteArray>& parts, QString* error)
{
    if (parts.size() < 3) {
        if (error)
            *error = QStringLiteral("no linework");
        return nullptr;
    }
    const QJsonObject meta = QJsonDocument::fromJson(parts.at(0)).object();
    if (!meta.value("ok").toBool()) {
        if (error)
            *error = meta.value("error").toString();
        return nullptr;
    }
    const int n = meta.value("count").toInt();
    if (parts.at(1).size() != qsizetype(n) * 16 || parts.at(2).size() != qsizetype(n) * 3) {
        if (error)
            *error = QStringLiteral("linework of the wrong size");
        return nullptr;
    }
    auto lines = std::make_shared<UnderlayLines>();
    const QJsonArray o = meta.value("origin").toArray();
    lines->origin = QPointF(o.at(0).toDouble(), o.at(1).toDouble());
    lines->coords.resize(size_t(n) * 4);
    lines->colours.resize(size_t(n) * 3);
    if (n > 0) {
        std::memcpy(lines->coords.data(), parts.at(1).constData(), size_t(n) * 16);
        std::memcpy(lines->colours.data(), parts.at(2).constData(), size_t(n) * 3);
    }
    return lines;
}

Underlay Underlay::fromJson(const QJsonObject& o)
{
    Underlay u;
    u.id = o.value("id").toString();
    u.name = o.value("name").toString();
    u.kind = o.value("kind").toString();
    u.file = o.value("file").toString();
    u.storey = o.value("storey").toString();
    u.layer = o.value("layer").toString();
    u.tint = o.value("tint").toString();
    u.path = o.value("path").toString();
    const QJsonArray base = o.value("base").toArray();
    u.placement.base = QPointF(base.at(0).toDouble(), base.at(1).toDouble());
    u.placement.at = QPointF(o.value("x").toDouble(), o.value("y").toDouble());
    u.placement.rotation = o.value("rotation").toDouble();
    u.placement.scale = o.value("scale").toDouble(1.0);
    u.placement.yDown = u.isRaster();
    const QJsonArray size = o.value("size").toArray();
    u.size = QSizeF(size.at(0).toDouble(), size.at(1).toDouble());
    u.page = o.value("page").toInt();
    u.dpi = o.value("dpi").toInt(150);
    u.opacity = o.value("opacity").toDouble(1.0);
    u.greyscale = o.value("greyscale").toBool();
    u.visible = o.value("visible").toBool(true);
    u.locked = o.value("locked").toBool();
    u.show3d = o.value("show_3d").toBool();
    u.missing = o.value("missing").toBool();
    return u;
}

QJsonObject Underlay::placementJson() const
{
    return {{"x", placement.at.x()}, {"y", placement.at.y()}, {"rotation", placement.rotation}, {"scale", placement.scale}};
}

QString Underlay::displayKey() const
{
    return QStringLiteral("%1|%2|%3|%4|%5|%6|%7|%8|%9")
        .arg(file, QString::number(page), QString::number(dpi), QString::number(opacity, 'g', 6), greyscale ? "g" : "c", tint)
        .arg(QString::number(placement.base.x(), 'g', 17), QString::number(placement.base.y(), 'g', 17), kind);
}

QColor underlayColour(const QColor& source, bool greyscale, const QColor& tint, double opacity, const QColor& background)
{
    QColor c = source;
    if (greyscale || tint.isValid()) {
        const double luma = 0.299 * c.redF() + 0.587 * c.greenF() + 0.114 * c.blueF();
        if (tint.isValid()) // dark lines take the tint; light ones fade to white
            c = QColor::fromRgbF(float(tint.redF() + (1 - tint.redF()) * luma), float(tint.greenF() + (1 - tint.greenF()) * luma),
                float(tint.blueF() + (1 - tint.blueF()) * luma));
        else
            c = QColor::fromRgbF(float(luma), float(luma), float(luma));
    }
    const double a = std::clamp(opacity, 0.0, 1.0);
    return QColor::fromRgbF(float(c.redF() * a + background.redF() * (1 - a)), float(c.greenF() * a + background.greenF() * (1 - a)),
        float(c.blueF() * a + background.blueF() * (1 - a)));
}

QImage processUnderlayImage(const QImage& source, bool greyscale, const QColor& tint)
{
    QImage img = source.convertToFormat(QImage::Format_RGBA8888);
    if (!greyscale && !tint.isValid())
        return img;
    const int tr = tint.isValid() ? tint.red() : 0, tg = tint.isValid() ? tint.green() : 0, tb = tint.isValid() ? tint.blue() : 0;
    for (int y = 0; y < img.height(); ++y) {
        uchar* row = img.scanLine(y);
        for (int x = 0; x < img.width(); ++x) {
            uchar* p = row + x * 4;
            const int luma = (299 * p[0] + 587 * p[1] + 114 * p[2]) / 1000;
            if (tint.isValid()) {
                p[0] = uchar(tr + (255 - tr) * luma / 255);
                p[1] = uchar(tg + (255 - tg) * luma / 255);
                p[2] = uchar(tb + (255 - tb) * luma / 255);
            } else {
                p[0] = p[1] = p[2] = uchar(luma);
            }
        }
    }
    return img;
}

// ---------------------------------------------------------------- snap index

void UnderlaySnapIndex::add(const UnderlayLines& lines, const UnderlayPlacement& placement)
{
    const int n = lines.count();
    m_segments.reserve(m_segments.size() + size_t(n));
    const float* c = lines.coords.data();
    for (int i = 0; i < n; ++i, c += 4) {
        const QPointF a = placement.toWorld(lines.origin + QPointF(c[0], c[1]));
        const QPointF b = placement.toWorld(lines.origin + QPointF(c[2], c[3]));
        m_segments.push_back({a, b});
    }
}

void UnderlaySnapIndex::addSegment(QPointF a, QPointF b)
{
    m_segments.push_back({a, b});
}

void UnderlaySnapIndex::build()
{
    m_cellStart.clear();
    m_cellItems.clear();
    if (m_segments.empty())
        return;
    double minX = std::numeric_limits<double>::max(), minY = minX, maxX = -minX, maxY = -minX;
    for (const Segment& s : m_segments) {
        minX = std::min({minX, s.a.x(), s.b.x()});
        minY = std::min({minY, s.a.y(), s.b.y()});
        maxX = std::max({maxX, s.a.x(), s.b.x()});
        maxY = std::max({maxY, s.a.y(), s.b.y()});
    }
    const double w = std::max(maxX - minX, 1e-6), h = std::max(maxY - minY, 1e-6);
    // About four segments per cell, at most 1024 x 1024 cells.
    m_cell = std::max({std::sqrt(w * h * 4.0 / double(m_segments.size())), w / 1024.0, h / 1024.0, 1e-3});
    m_minX = minX;
    m_minY = minY;
    m_nx = std::max(1, int(std::ceil(w / m_cell)) + 1);
    m_ny = std::max(1, int(std::ceil(h / m_cell)) + 1);
    auto cellRange = [&](const Segment& s, int* x0, int* y0, int* x1, int* y1) {
        *x0 = std::clamp(int((std::min(s.a.x(), s.b.x()) - m_minX) / m_cell), 0, m_nx - 1);
        *x1 = std::clamp(int((std::max(s.a.x(), s.b.x()) - m_minX) / m_cell), 0, m_nx - 1);
        *y0 = std::clamp(int((std::min(s.a.y(), s.b.y()) - m_minY) / m_cell), 0, m_ny - 1);
        *y1 = std::clamp(int((std::max(s.a.y(), s.b.y()) - m_minY) / m_cell), 0, m_ny - 1);
    };
    // Counting sort into cells: a segment goes into every cell of its bounding box (long diagonals into
    // many; rare in surveys, and bounded by the grid).
    std::vector<int> counts(size_t(m_nx) * m_ny + 1, 0);
    for (const Segment& s : m_segments) {
        int x0, y0, x1, y1;
        cellRange(s, &x0, &y0, &x1, &y1);
        for (int y = y0; y <= y1; ++y)
            for (int x = x0; x <= x1; ++x)
                ++counts[size_t(y) * m_nx + x];
    }
    m_cellStart.assign(counts.size(), 0);
    for (size_t i = 1; i < counts.size(); ++i)
        m_cellStart[i] = m_cellStart[i - 1] + counts[i - 1];
    m_cellItems.assign(size_t(m_cellStart.back()), 0);
    std::vector<int> fill(m_cellStart.begin(), m_cellStart.end() - 1);
    for (int i = 0; i < int(m_segments.size()); ++i) {
        int x0, y0, x1, y1;
        cellRange(m_segments[size_t(i)], &x0, &y0, &x1, &y1);
        for (int y = y0; y <= y1; ++y)
            for (int x = x0; x <= x1; ++x)
                m_cellItems[size_t(fill[size_t(y) * m_nx + x]++)] = i;
    }
}

template <typename F>
void UnderlaySnapIndex::forNearby(QPointF p, double tolerance, F&& f) const
{
    if (m_cellStart.empty())
        return;
    const int x0 = int(std::floor((p.x() - tolerance - m_minX) / m_cell)), x1 = int(std::floor((p.x() + tolerance - m_minX) / m_cell));
    const int y0 = int(std::floor((p.y() - tolerance - m_minY) / m_cell)), y1 = int(std::floor((p.y() + tolerance - m_minY) / m_cell));
    if (x1 < 0 || y1 < 0 || x0 >= m_nx || y0 >= m_ny)
        return;
    for (int y = std::max(0, y0); y <= std::min(m_ny - 1, y1); ++y)
        for (int x = std::max(0, x0); x <= std::min(m_nx - 1, x1); ++x) {
            const size_t cell = size_t(y) * m_nx + x;
            for (int k = m_cellStart[cell]; k < m_cellStart[cell + 1]; ++k)
                f(m_cellItems[size_t(k)]);
        }
}

bool UnderlaySnapIndex::endpoint(QPointF p, double tolerance, QPointF* out) const
{
    double best = tolerance;
    bool found = false;
    forNearby(p, tolerance, [&](int i) {
        for (const QPointF& q : {m_segments[size_t(i)].a, m_segments[size_t(i)].b})
            if (dist(p, q) <= best) {
                best = dist(p, q);
                *out = q;
                found = true;
            }
    });
    return found;
}

bool UnderlaySnapIndex::midpoint(QPointF p, double tolerance, QPointF* out) const
{
    double best = tolerance;
    bool found = false;
    forNearby(p, tolerance, [&](int i) {
        const QPointF q = (m_segments[size_t(i)].a + m_segments[size_t(i)].b) / 2;
        if (dist(p, q) <= best) {
            best = dist(p, q);
            *out = q;
            found = true;
        }
    });
    return found;
}

bool UnderlaySnapIndex::crossing(QPointF p, double tolerance, QPointF* out) const
{
    std::vector<int> cand;
    forNearby(p, tolerance, [&](int i) {
        if (cand.size() < 256 && std::find(cand.begin(), cand.end(), i) == cand.end())
            cand.push_back(i);
    });
    double best = tolerance;
    bool found = false;
    for (size_t i = 0; i < cand.size(); ++i)
        for (size_t j = i + 1; j < cand.size(); ++j) {
            const Segment& s = m_segments[size_t(cand[i])];
            const Segment& t = m_segments[size_t(cand[j])];
            const QPointF r = s.b - s.a, q = t.b - t.a;
            const double den = r.x() * q.y() - r.y() * q.x();
            if (std::abs(den) < 1e-12)
                continue;
            const QPointF w = t.a - s.a;
            const double u = (w.x() * q.y() - w.y() * q.x()) / den, v = (w.x() * r.y() - w.y() * r.x()) / den;
            if (u < -1e-9 || u > 1 + 1e-9 || v < -1e-9 || v > 1 + 1e-9)
                continue;
            const QPointF x = s.a + r * u;
            if (dist(p, x) <= best) {
                best = dist(p, x);
                *out = x;
                found = true;
            }
        }
    return found;
}

bool UnderlaySnapIndex::onLine(QPointF p, double tolerance, QPointF* out) const
{
    double best = tolerance;
    bool found = false;
    forNearby(p, tolerance, [&](int i) {
        const Segment& s = m_segments[size_t(i)];
        const QPointF d = s.b - s.a;
        const double len2 = d.x() * d.x() + d.y() * d.y();
        if (len2 <= 0)
            return;
        const double t = std::clamp(((p.x() - s.a.x()) * d.x() + (p.y() - s.a.y()) * d.y()) / len2, 0.0, 1.0);
        const QPointF q = s.a + d * t;
        if (dist(p, q) <= best) {
            best = dist(p, q);
            *out = q;
            found = true;
        }
    });
    return found;
}

} // namespace kimcad
