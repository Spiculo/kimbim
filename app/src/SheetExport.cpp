// SPDX-License-Identifier: GPL-3.0-or-later
#include "SheetExport.h"

#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPageSize>
#include <QPainter>
#include <QPdfWriter>
#include <QSvgRenderer>

#include <cstdio>

#include "PythonEngine.h"

namespace kimbim {

bool exportSvgToPdf(const QByteArray& svg, double widthMm, double heightMm, const QString& path, QString* error)
{
    QSvgRenderer renderer(svg);
    if (!renderer.isValid()) {
        if (error)
            *error = QStringLiteral("the sheet's SVG could not be read");
        return false;
    }
    QPdfWriter pdf(path);
    pdf.setCreator(QStringLiteral("KimBim"));
    pdf.setResolution(600); // QPdfWriter is vector; this only sets the painter's unit
    const QPageSize size(QSizeF(widthMm, heightMm), QPageSize::Millimeter);
    if (!pdf.setPageSize(size) || !pdf.setPageMargins(QMarginsF(0, 0, 0, 0))) {
        if (error)
            *error = QStringLiteral("unsupported page size");
        return false;
    }
    QPainter painter;
    if (!painter.begin(&pdf)) {
        if (error)
            *error = QStringLiteral("cannot write %1").arg(path);
        return false;
    }
    renderer.render(&painter, QRectF(0, 0, pdf.width(), pdf.height()));
    painter.end();
    return true;
}

int exportSheetCommand(const QString& ifcPath, const QString& number, const QString& path)
{
    auto report = [](const QJsonObject& o) {
        std::printf("%s\n", QJsonDocument(o).toJson(QJsonDocument::Compact).constData());
        std::fflush(stdout);
        return o.value("ok").toBool() ? 0 : 1;
    };
    QString error;
    PythonEngine& py = PythonEngine::instance();
    if (!py.start(&error))
        return report({{"ok", false}, {"error", error}});
    const QJsonObject opened = py.callJson("open_model", {ifcPath}, &error).object();
    if (!opened.value("ok").toBool())
        return report({{"ok", false}, {"error", error.isEmpty() ? opened.value("error").toString() : error}});
    if (path.endsWith(QLatin1String(".dxf"), Qt::CaseInsensitive)) { // D83: a paper-space layout
        const QJsonObject r = py.callJson("export_sheet_dxf", {number, path, QString()}, &error).object();
        if (!r.value("ok").toBool())
            return report({{"ok", false}, {"error", error.isEmpty() ? r.value("error").toString() : error}});
        return report({{"ok", true}, {"path", path}, {"sheet", number}, {"layout", r.value("layout")},
            {"entities", r.value("entities")}});
    }
    const QJsonObject sheet = py.callJson("sheet_svg", {number}, &error).object();
    if (!sheet.value("ok").toBool())
        return report({{"ok", false}, {"error", error.isEmpty() ? sheet.value("error").toString() : error}});
    const QByteArray svg = sheet.value("svg").toString().toUtf8();
    if (path.endsWith(QLatin1String(".svg"), Qt::CaseInsensitive)) {
        QFile out(path);
        if (!out.open(QIODevice::WriteOnly) || out.write(svg) != svg.size())
            return report({{"ok", false}, {"error", QStringLiteral("cannot write %1").arg(path)}});
    } else if (!exportSvgToPdf(svg, sheet.value("width").toDouble(), sheet.value("height").toDouble(), path, &error)) {
        return report({{"ok", false}, {"error", error}});
    }
    return report({{"ok", true}, {"path", path}, {"sheet", number},
        {"width_mm", sheet.value("width").toDouble()}, {"height_mm", sheet.value("height").toDouble()}});
}

} // namespace kimbim
