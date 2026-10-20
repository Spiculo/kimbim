// SPDX-License-Identifier: GPL-3.0-or-later
#include "Tracker.h"

#include <cmath>

namespace kimbim {

namespace {
constexpr double kPi = 3.14159265358979323846;
} // namespace

void Tracker::setAnchor(const std::optional<QPointF>& anchor)
{
    const bool had = m_anchor.has_value();
    m_anchor = anchor;
    if (had != anchor.has_value() && !hasInput())
        m_focus = anchor ? Length : X; // the first field of what is shown
    if (!anchor && (m_focus == Length || m_focus == Angle))
        m_focus = X;
}

QVector<Tracker::Field> Tracker::fields() const
{
    if (m_anchor)
        return {Length, Angle, X, Y};
    return {X, Y};
}

void Tracker::setFocus(Field f)
{
    if (fields().contains(f))
        m_focus = f;
}

bool Tracker::hasInput() const
{
    for (const QString& t : m_text)
        if (!t.isEmpty())
            return true;
    return false;
}

void Tracker::clear()
{
    for (QString& t : m_text)
        t.clear();
    m_absolute = false;
    m_focus = m_anchor ? Length : X;
}

bool Tracker::key(int key, const QString& text, Qt::KeyboardModifiers modifiers)
{
    const QVector<Field> shown = fields();
    const int at = std::max(0, int(shown.indexOf(m_focus)));
    if (key == Qt::Key_Backtab || (key == Qt::Key_Tab && (modifiers & Qt::ShiftModifier))) {
        m_focus = shown[(at + shown.size() - 1) % shown.size()];
        return true;
    }
    if (key == Qt::Key_Tab) {
        m_focus = shown[(at + 1) % shown.size()];
        return true;
    }
    if (key == Qt::Key_Backspace) {
        if (m_text[m_focus].isEmpty())
            return hasInput();
        m_text[m_focus].chop(1);
        return true;
    }
    if (text.size() != 1)
        return false;
    const QChar c = text.at(0);
    if (c.isDigit() || c == QLatin1Char('.') || c == QLatin1Char(',')) {
        m_text[m_focus] += c;
        return true;
    }
    if (c == QLatin1Char('-')) {
        if (!m_text[m_focus].isEmpty())
            return true; // only as a sign
        m_text[m_focus] = c;
        return true;
    }
    if (c == QLatin1Char('<') && m_anchor) {
        m_focus = Angle;
        return true;
    }
    if (c == QLatin1Char(';')) {
        m_focus = shown[(at + 1) % shown.size()];
        return true;
    }
    if (c == QLatin1Char('#') || c == QLatin1Char('a') || c == QLatin1Char('A')) {
        m_absolute = !m_absolute || c == QLatin1Char('#');
        m_focus = X;
        return true;
    }
    if (c == QLatin1Char('@')) {
        m_absolute = false;
        m_focus = X;
        return true;
    }
    return false;
}

void Tracker::type(const QString& text)
{
    for (const QChar c : text) {
        if (c == QLatin1Char('\t'))
            key(Qt::Key_Tab, QString());
        else
            key(0, QString(c));
    }
}

std::optional<double> Tracker::value(Field f) const
{
    QString t = m_text[f];
    t.replace(QLatin1Char(','), QLatin1Char('.'));
    bool ok = false;
    const double v = t.toDouble(&ok);
    if (!ok || !std::isfinite(v))
        return std::nullopt;
    return v;
}

double Tracker::live(Field f) const
{
    const QPointF a = m_anchor.value_or(QPointF());
    const QPointF d = m_cursor - a;
    switch (f) {
    case Length:
        return std::hypot(d.x(), d.y());
    case Angle: {
        double deg = std::atan2(d.y(), d.x()) * 180.0 / kPi;
        if (deg < 0)
            deg += 360.0;
        return std::abs(deg - 360.0) < 1e-9 ? 0.0 : deg;
    }
    case X:
        return absolute() ? m_cursor.x() : d.x();
    case Y:
        return absolute() ? m_cursor.y() : d.y();
    }
    return 0.0;
}

bool Tracker::lengthOnly() const
{
    return value(Length) && m_text[Angle].isEmpty() && m_text[X].isEmpty() && m_text[Y].isEmpty();
}

InputAids::Locks Tracker::locks() const
{
    InputAids::Locks l;
    const QPointF a = m_anchor.value_or(QPointF());
    if (const auto x = value(X))
        l.x = absolute() ? *x : a.x() + *x;
    if (const auto y = value(Y))
        l.y = absolute() ? *y : a.y() + *y;
    if (m_anchor) {
        if (const auto deg = value(Angle))
            l.angle = *deg * kPi / 180.0;
        l.length = value(Length);
    }
    return l;
}

std::optional<QPointF> Tracker::target() const
{
    const InputAids::Locks l = locks();
    if (l.x || l.y)
        return QPointF(l.x.value_or(m_cursor.x()), l.y.value_or(m_cursor.y()));
    if (!m_anchor || (!l.angle && !l.length))
        return std::nullopt;
    const QPointF v = m_cursor - *m_anchor;
    const double angle = l.angle.value_or(std::atan2(v.y(), v.x()));
    const QPointF d(std::cos(angle), std::sin(angle));
    const double length = l.length.value_or(l.angle ? v.x() * d.x() + v.y() * d.y() : std::hypot(v.x(), v.y()));
    return *m_anchor + d * length;
}

} // namespace kimbim
