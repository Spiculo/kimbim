// SPDX-License-Identifier: GPL-3.0-or-later
#include "SheetExport.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPageSize>
#include <QPainter>
#include <QPdfWriter>
#include <QSet>
#include <QSvgRenderer>

#include <cstdio>

#include "PythonEngine.h"

namespace kimbim {

QString sheetFileName(const QString& number)
{
    QString name = number.trimmed();
    const QString reserved = QStringLiteral("<>:\"/\\|?*");
    for (QChar& c : name) {
        if (reserved.contains(c) || c.unicode() < 0x20)
            c = QLatin1Char('-');
    }
    while (name.endsWith(QLatin1Char('.')) || name.endsWith(QLatin1Char(' ')))
        name.chop(1);
    if (name.isEmpty())
        name = QStringLiteral("sheet");
    return name.left(80);
}

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

int exportSheetsCommand(const QString& ifcPath, const QString& folder, const QStringList& numbers)
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

    const QJsonArray available = py.callJson("sheets", {}, &error).object().value("sheets").toArray();
    if (available.isEmpty())
        return report({{"ok", false}, {"error", QStringLiteral("the model has no sheets")}});

    QList<QJsonObject> chosen;
    if (numbers.isEmpty()) {
        for (const auto& value : available)
            chosen.append(value.toObject());
    } else {
        for (const QString& requested : numbers) {
            const QString number = requested.trimmed();
            bool found = false;
            for (const auto& value : available) {
                const QJsonObject sheet = value.toObject();
                if (sheet.value("number").toString() == number) {
                    chosen.append(sheet);
                    found = true;
                    break;
                }
            }
            if (!found)
                return report({{"ok", false}, {"error", QStringLiteral("no sheet %1").arg(number)}});
        }
    }

    QDir directory(folder);
    if (!directory.mkpath(QStringLiteral(".")))
        return report({{"ok", false}, {"error", QStringLiteral("cannot create %1").arg(folder)}});

    QJsonArray written;
    QSet<QString> used;
    for (const QJsonObject& sheet : chosen) {
        const QString number = sheet.value("number").toString();
        const QString base = sheetFileName(number);
        QString name = base;
        for (int suffix = 2; used.contains(name.toLower()); ++suffix)
            name = QStringLiteral("%1-%2").arg(base).arg(suffix);
        used.insert(name.toLower());
        const QString path = directory.filePath(name + QStringLiteral(".pdf"));

        const QJsonObject svg = py.callJson("sheet_svg", {number}, &error).object();
        if (!svg.value("ok").toBool())
            return report({{"ok", false}, {"sheet", number},
                {"error", error.isEmpty() ? svg.value("error").toString() : error}});
        if (!exportSvgToPdf(svg.value("svg").toString().toUtf8(), svg.value("width").toDouble(),
                svg.value("height").toDouble(), path, &error))
            return report({{"ok", false}, {"sheet", number}, {"error", error}});
        written.append(QJsonObject{{"number", number}, {"title", sheet.value("title")}, {"path", path},
            {"width_mm", svg.value("width").toDouble()}, {"height_mm", svg.value("height").toDouble()}});
    }
    return report({{"ok", true}, {"folder", directory.absolutePath()}, {"count", written.size()},
        {"sheets", written}});
}

} // namespace kimbim
