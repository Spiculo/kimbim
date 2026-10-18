// SPDX-License-Identifier: GPL-3.0-or-later
#include "Icons.h"

#include <QFile>
#include <QGuiApplication>
#include <QHash>
#include <QIconEngine>
#include <QPainter>
#include <QPalette>
#include <QPixmap>
#include <QSvgRenderer>

namespace kimcad {

QIcon iconFor(const QString& ifcClass)
{
    static const QHash<QString, QString> kinds{
        {"IfcWall", "wall"}, {"IfcWallStandardCase", "wall"}, {"IfcCurtainWall", "wall"},
        {"IfcSlab", "slab"}, {"IfcRoof", "slab"}, {"IfcCovering", "slab"}, {"IfcPlate", "slab"},
        {"IfcDoor", "door"}, {"IfcWindow", "window"},
        {"IfcColumn", "column"}, {"IfcPile", "column"},
        {"IfcBeam", "beam"}, {"IfcMember", "beam"}, {"IfcFooting", "beam"},
        {"IfcStair", "stair"}, {"IfcStairFlight", "stair"}, {"IfcRamp", "stair"}, {"IfcRampFlight", "stair"},
        {"IfcRailing", "stair"},
        {"IfcBuildingStorey", "storey"}, {"IfcBuilding", "building"}, {"IfcSite", "site"},
        {"IfcProject", "project"}, {"IfcSpace", "space"}, {"IfcGrid", "grid"},
        {"IfcFurniture", "object"}, {"IfcFurnishingElement", "object"}, {"IfcSanitaryTerminal", "object"}, // D86
        {"IfcElectricAppliance", "object"}, {"IfcGeographicElement", "object"},
    };
    static QHash<QString, QIcon> cache;
    const QString kind = kinds.value(ifcClass, QStringLiteral("element"));
    auto it = cache.find(kind);
    if (it == cache.end())
        it = cache.insert(kind, QIcon(QStringLiteral(":/icons/%1.svg").arg(kind)));
    return *it;
}

namespace {

// Renders an SVG whose "currentColor" is the application palette's colour for the icon mode, at paint
// time: a theme change (Windows light/dark) recolours every icon without rebuilding anything.
class TintedSvgEngine : public QIconEngine {
public:
    explicit TintedSvgEngine(QByteArray svg) : m_svg(std::move(svg)) {}

    void paint(QPainter* painter, const QRect& rect, QIcon::Mode mode, QIcon::State) override
    {
        QByteArray data = m_svg;
        data.replace("currentColor", colorFor(mode).name().toLatin1());
        QSvgRenderer renderer(data);
        renderer.render(painter, rect);
    }

    QPixmap pixmap(const QSize& size, QIcon::Mode mode, QIcon::State state) override
    {
        return scaledPixmap(size, mode, state, 1.0);
    }

    QPixmap scaledPixmap(const QSize& size, QIcon::Mode mode, QIcon::State state, qreal scale) override
    {
        const QSize px = size * scale;
        const QString key = QStringLiteral("%1x%2/%3/%4").arg(px.width()).arg(px.height()).arg(int(mode))
            .arg(colorFor(mode).rgba());
        auto it = m_cache.constFind(key);
        if (it != m_cache.constEnd())
            return *it;
        QPixmap pm(px);
        pm.fill(Qt::transparent);
        {
            QPainter p(&pm);
            p.setRenderHint(QPainter::Antialiasing);
            paint(&p, QRect(QPoint(0, 0), px), mode, state);
        }
        pm.setDevicePixelRatio(scale);
        if (m_cache.size() > 64)
            m_cache.clear();
        m_cache.insert(key, pm);
        return pm;
    }

    QSize actualSize(const QSize& size, QIcon::Mode, QIcon::State) override { return size; }
    QIconEngine* clone() const override { return new TintedSvgEngine(m_svg); }
    QString key() const override { return QStringLiteral("kimcadTintedSvg"); }
    bool isNull() override { return m_svg.isEmpty(); }

private:
    static QColor colorFor(QIcon::Mode mode)
    {
        const QPalette pal = QGuiApplication::palette();
        switch (mode) {
        case QIcon::Disabled: {
            QColor c = pal.color(QPalette::Disabled, QPalette::WindowText);
            if (c == pal.color(QPalette::Active, QPalette::WindowText))
                c.setAlphaF(0.4);
            return c;
        }
        case QIcon::Selected:
            return pal.color(QPalette::HighlightedText);
        default:
            return pal.color(QPalette::WindowText);
        }
    }

    QByteArray m_svg;
    QHash<QString, QPixmap> m_cache;
};

} // namespace

QIcon themedIcon(const QString& name)
{
    static QHash<QString, QIcon> cache;
    auto it = cache.find(name);
    if (it == cache.end()) {
        QFile f(QStringLiteral(":/icons/%1.svg").arg(name));
        const QByteArray svg = f.open(QIODevice::ReadOnly) ? f.readAll() : QByteArray();
        it = cache.insert(name, svg.isEmpty() ? QIcon() : QIcon(new TintedSvgEngine(svg)));
    }
    return *it;
}

QIcon letterIcon(const QString& label)
{
    QString letter;
    for (const QChar c : label)
        if (c.isLetterOrNumber()) {
            letter = c.toUpper();
            break;
        }
    static QHash<QString, QIcon> cache;
    auto it = cache.find(letter);
    if (it == cache.end()) {
        const QString svg = QStringLiteral(
            "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 16 16\" width=\"16\" height=\"16\">"
            "<rect x=\"1.5\" y=\"1.5\" width=\"13\" height=\"13\" rx=\"2.5\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.2\"/>"
            "<text x=\"8\" y=\"11.6\" font-family=\"Segoe UI, Arial, sans-serif\" font-size=\"9.5\" font-weight=\"bold\" "
            "text-anchor=\"middle\" fill=\"currentColor\">%1</text></svg>").arg(letter.toHtmlEscaped());
        it = cache.insert(letter, QIcon(new TintedSvgEngine(svg.toUtf8())));
    }
    return *it;
}

} // namespace kimcad
