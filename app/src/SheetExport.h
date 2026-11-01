// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QString>
#include <QStringList>

namespace kimbim {

// A sheet's SVG (millimetres) to a one-page PDF of the same paper size, through Qt (doc 05: QPdfWriter
// with QSvgRenderer). Vector output: lines and text stay sharp at any zoom.
bool exportSvgToPdf(const QByteArray& svg, double widthMm, double heightMm, const QString& path, QString* error);

// A sheet number as a safe, deterministic file name (no path separators or Windows-reserved characters).
QString sheetFileName(const QString& number);

// Headless export for CI and scripts: open the IFC, compose sheet `number`, write the PDF (or SVG
// when `path` ends in .svg, a DXF layout when it ends in .dxf). Prints one JSON line; returns the exit code.
int exportSheetCommand(const QString& ifcPath, const QString& number, const QString& path);

// Headless batch publishing: write every sheet, or only `numbers` when that list is not empty, as
// `<number>.pdf` in `folder`. Opens the model once. Prints one JSON line; returns the exit code.
int exportSheetsCommand(const QString& ifcPath, const QString& folder, const QStringList& numbers);

} // namespace kimbim
