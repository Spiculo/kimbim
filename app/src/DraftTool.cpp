// SPDX-License-Identifier: GPL-3.0-or-later
#include "DraftTool.h"

#include <QLocale>
#include <QRegularExpression>

#include <cmath>

#include "PolygonTool.h"

namespace kimcad {

namespace {

constexpr double kPi = 3.14159265358979323846;
constexpr double kSame = 1e-3; // metres: a second click on the same point

double dist(QPointF a, QPointF b)
{
    return std::hypot(a.x() - b.x(), a.y() - b.y());
}

std::optional<double> number(const QString& text)
{
    const QString t = text.trimmed();
    if (t.isEmpty())
        return std::nullopt;
    bool ok = false;
    double v = QLocale().toDouble(t, &ok);
    if (!ok)
        v = QLocale::c().toDouble(QString(t).replace(QLatin1Char(','), QLatin1Char('.')), &ok);
    return ok ? std::optional<double>(v) : std::nullopt;
}

} // namespace

DraftTool::DraftTool(QObject* parent)
    : QObject(parent)
{
}

void DraftTool::setMode(Mode mode)
{
    m_mode = mode;
    cancel();
}

int DraftTool::needed() const
{
    switch (m_mode) {
    case Mode::Line:
    case Mode::Rectangle:
    case Mode::Circle:
        return 2;
    case Mode::Arc3:
    case Mode::ArcCentre:
        return 3;
    case Mode::Polyline:
    case Mode::Fill:
        return 0;
    }
    return 0;
}

Snap DraftTool::snapAt(QPointF p) const
{
    if (m_points.isEmpty())
        return m_snapper.snap(p, m_tolerance);
    const bool open = m_mode == Mode::Polyline || m_mode == Mode::Fill;
    if (open && m_points.size() >= 3 && dist(p, m_points.first()) <= m_tolerance)
        return Snap{m_points.first(), Snap::Endpoint, {}}; // closing on the first point wins
    const QPointF from = m_points.last();
    return m_snapper.snap(p, m_tolerance, &from, m_ortho && m_mode != Mode::Rectangle);
}

Snap DraftTool::move(QPointF p)
{
    const Snap s = snapAt(p);
    m_hover = s.point;
    emit previewChanged();
    return s;
}

void DraftTool::click(QPointF p)
{
    const Snap s = snapAt(p);
    const bool open = m_mode == Mode::Polyline || m_mode == Mode::Fill;
    if (open && m_points.size() >= 3 && s.point == m_points.first()) {
        const QVector<QPointF> pts = m_points;
        cancel();
        emitShape(m_mode == Mode::Fill ? QStringLiteral("fill") : QStringLiteral("polyline"), pts, true);
        return;
    }
    if (!m_points.isEmpty() && dist(s.point, m_points.last()) < kSame) {
        if (m_mode == Mode::Polyline) // a double click ends the polyline (Archicad)
            finish();
        return;
    }
    add(s.point);
}

void DraftTool::add(QPointF p)
{
    m_points << p;
    if (needed() > 0 && m_points.size() >= needed()) {
        const QVector<QPointF> pts = m_points;
        cancel();
        switch (m_mode) {
        case Mode::Line:
            emitShape(QStringLiteral("line"), pts);
            break;
        case Mode::Rectangle:
            emitShape(QStringLiteral("rectangle"), pts);
            break;
        case Mode::Circle:
            emitShape(QStringLiteral("circle"), pts);
            break;
        case Mode::Arc3:
            emitShape(QStringLiteral("arc"), pts);
            break;
        case Mode::ArcCentre:
            emitShape(QStringLiteral("arc"), arcFromCentre(pts[0], pts[1], pts[2]));
            break;
        default:
            break;
        }
        return;
    }
    emit previewChanged();
}

void DraftTool::emitShape(const QString& kind, const QVector<QPointF>& points, bool closed)
{
    if (kind == QLatin1String("arc") && (points.size() != 3 || !circumcircle(points[0], points[1], points[2]))) {
        emit rejected(tr("The three points are in a line"));
        return;
    }
    if (kind == QLatin1String("fill") && !PolygonTool::isSimple(points)) {
        emit rejected(tr("The outline crosses itself"));
        return;
    }
    emit shapeFinished(kind, points, closed);
}

void DraftTool::finish()
{
    if (m_mode == Mode::Polyline && m_points.size() >= 2) {
        const QVector<QPointF> pts = m_points;
        cancel();
        emitShape(QStringLiteral("polyline"), pts, false);
    } else if (m_mode == Mode::Fill && m_points.size() >= 3) {
        const QVector<QPointF> pts = m_points;
        cancel();
        emitShape(QStringLiteral("fill"), pts, true);
    }
}

void DraftTool::escape()
{
    if (m_mode == Mode::Polyline && m_points.size() >= 2)
        finish();
    else
        cancel();
}

void DraftTool::cancel()
{
    m_points.clear();
    m_hover.reset();
    emit previewChanged();
}

bool DraftTool::typeInput(const QString& text)
{
    if (m_points.isEmpty())
        return false;
    const QPointF last = m_points.last();
    QPointF dir;
    if (m_hover && dist(*m_hover, last) > 1e-9)
        dir = (*m_hover - last) / dist(*m_hover, last);
    else
        dir = QPointF(1, 0);
    // A rectangle's width;height (signs from where the mouse is).
    if (m_mode == Mode::Rectangle) {
        const QStringList parts = text.split(QRegularExpression(QStringLiteral("[;xX*\\s]+")), Qt::SkipEmptyParts);
        if (parts.size() != 2)
            return false;
        const auto w = number(parts[0]), h = number(parts[1]);
        if (!w || !h || *w == 0 || *h == 0)
            return false;
        const double sx = m_hover && m_hover->x() < last.x() ? -1 : 1, sy = m_hover && m_hover->y() < last.y() ? -1 : 1;
        add(last + QPointF(sx * std::abs(*w), sy * std::abs(*h)));
        return true;
    }
    // "length<angle": polar, the angle in degrees from the x axis.
    const qsizetype lt = text.indexOf(QLatin1Char('<'));
    std::optional<double> value = number(lt >= 0 ? text.left(lt) : text);
    if (lt >= 0) {
        const auto angle = number(text.mid(lt + 1));
        if (!angle)
            return false;
        dir = QPointF(std::cos(*angle * kPi / 180), std::sin(*angle * kPi / 180));
    }
    if (m_mode == Mode::ArcCentre && m_points.size() == 2 && lt < 0) { // the arc's angle, degrees counter-clockwise
        if (!value || std::abs(*value) < 1e-6)
            return false;
        const QPointF c = m_points[0], v = m_points[1] - c;
        const double a = *value * kPi / 180;
        const QPointF end = c + QPointF(v.x() * std::cos(a) - v.y() * std::sin(a), v.x() * std::sin(a) + v.y() * std::cos(a));
        if (*value < 0) { // clockwise: the same arc drawn from its end
            const QPointF start = m_points[1];
            cancel();
            emitShape(QStringLiteral("arc"), arcFromCentre(c, end, start));
            return true;
        }
        add(end);
        return true;
    }
    if (!value || *value <= 0)
        return false;
    add(last + dir * *value);
    return true;
}

QVector<QPointF> DraftTool::arcFromCentre(QPointF centre, QPointF start, QPointF end)
{
    const double r = dist(start, centre);
    const double a0 = std::atan2(start.y() - centre.y(), start.x() - centre.x());
    double a1 = std::atan2(end.y() - centre.y(), end.x() - centre.x());
    double sweep = std::fmod(a1 - a0 + 4 * kPi, 2 * kPi);
    if (sweep < 1e-9)
        sweep = 2 * kPi;
    a1 = a0 + sweep;
    const double am = a0 + sweep / 2;
    return {start, centre + QPointF(std::cos(am), std::sin(am)) * r, centre + QPointF(std::cos(a1), std::sin(a1)) * r};
}

QVector<QPointF> DraftTool::circlePoints(QPointF centre, double radius, int segments)
{
    QVector<QPointF> out;
    for (int i = 0; i <= segments; ++i)
        out << centre + QPointF(std::cos(2 * kPi * i / segments), std::sin(2 * kPi * i / segments)) * radius;
    return out;
}

std::optional<std::pair<QPointF, double>> DraftTool::circumcircle(QPointF a, QPointF b, QPointF c)
{
    const double d = 2 * (a.x() * (b.y() - c.y()) + b.x() * (c.y() - a.y()) + c.x() * (a.y() - b.y()));
    if (std::abs(d) < 1e-12)
        return std::nullopt;
    const double a2 = a.x() * a.x() + a.y() * a.y(), b2 = b.x() * b.x() + b.y() * b.y(), c2 = c.x() * c.x() + c.y() * c.y();
    const QPointF u((a2 * (b.y() - c.y()) + b2 * (c.y() - a.y()) + c2 * (a.y() - b.y())) / d,
        (a2 * (c.x() - b.x()) + b2 * (a.x() - c.x()) + c2 * (b.x() - a.x())) / d);
    return std::make_pair(u, dist(a, u));
}

QVector<QPointF> DraftTool::arcPoints(QPointF a, QPointF b, QPointF c, int segments)
{
    const auto cc = circumcircle(a, b, c);
    if (!cc)
        return {a, c};
    const auto [u, r] = *cc;
    const double a0 = std::atan2(a.y() - u.y(), a.x() - u.x()), a2 = std::atan2(c.y() - u.y(), c.x() - u.x());
    const double cross = (b.x() - a.x()) * (c.y() - a.y()) - (b.y() - a.y()) * (c.x() - a.x());
    const double sweep = cross > 0 ? std::fmod(a2 - a0 + 4 * kPi, 2 * kPi) : -std::fmod(a0 - a2 + 4 * kPi, 2 * kPi);
    QVector<QPointF> out;
    for (int i = 0; i <= segments; ++i)
        out << u + QPointF(std::cos(a0 + sweep * i / segments), std::sin(a0 + sweep * i / segments)) * r;
    return out;
}

QVector<QVector<QPointF>> DraftTool::preview() const
{
    QVector<QVector<QPointF>> out;
    if (m_points.isEmpty() || !m_hover)
        return out;
    const QPointF h = *m_hover, p0 = m_points.first();
    switch (m_mode) {
    case Mode::Line:
    case Mode::Polyline:
    case Mode::Fill: {
        QVector<QPointF> pts = m_points;
        pts << h;
        if (m_mode == Mode::Fill && pts.size() >= 3)
            pts << p0;
        out << pts;
        break;
    }
    case Mode::Rectangle:
        out << QVector<QPointF>{p0, QPointF(h.x(), p0.y()), h, QPointF(p0.x(), h.y()), p0};
        break;
    case Mode::Circle:
        out << circlePoints(p0, dist(p0, h)) << QVector<QPointF>{p0, h};
        break;
    case Mode::Arc3:
        if (m_points.size() == 1)
            out << QVector<QPointF>{p0, h};
        else
            out << arcPoints(p0, m_points[1], h);
        break;
    case Mode::ArcCentre:
        if (m_points.size() == 1) {
            out << circlePoints(p0, dist(p0, h)) << QVector<QPointF>{p0, h};
        } else {
            const QVector<QPointF> arc = arcFromCentre(p0, m_points[1], h);
            out << arcPoints(arc[0], arc[1], arc[2]) << QVector<QPointF>{p0, m_points[1]};
        }
        break;
    }
    return out;
}

QString DraftTool::hint() const
{
    const int n = int(m_points.size());
    switch (m_mode) {
    case Mode::Line:
        return n == 0 ? tr("Line: click the start point") : tr("Line: click the end point, or type a length (length<angle)");
    case Mode::Polyline:
        return n == 0 ? tr("Polyline: click the first point")
                      : tr("Polyline: click the next point or type a length; click the first point to close, Enter or double click to end");
    case Mode::Rectangle:
        return n == 0 ? tr("Rectangle: click a corner") : tr("Rectangle: click the opposite corner, or type width;height");
    case Mode::Circle:
        return n == 0 ? tr("Circle: click the centre") : tr("Circle: click a point on it, or type the radius");
    case Mode::Arc3:
        return n == 0 ? tr("Arc: click where it starts") : n == 1 ? tr("Arc: click a point it passes through") : tr("Arc: click where it ends");
    case Mode::ArcCentre:
        return n == 0 ? tr("Arc: click the centre")
            : n == 1  ? tr("Arc: click where it starts, or type the radius")
                      : tr("Arc: click where it ends (counter-clockwise), or type the angle in degrees");
    case Mode::Fill:
        return n == 0 ? tr("Fill: click the outline's points (Alt+click inside a closed polyline or circle to fill it)")
                      : tr("Fill: click the next point; click the first point or press Enter to close");
    }
    return {};
}

} // namespace kimcad
