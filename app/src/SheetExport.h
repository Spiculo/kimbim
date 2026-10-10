// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QString>

namespace kimcad {

// A sheet's SVG (millimetres) to a one-page PDF of the same paper size, through Qt (doc 05: QPdfWriter
// with QSvgRenderer). Vector output: lines and text stay sharp at any zoom.
bool exportSvgToPdf(const QByteArray& svg, double widthMm, double heightMm, const QString& path, QString* error);

// Headless export for CI and scripts: open the IFC, compose sheet `number`, write the PDF (or SVG
// when `path` ends in .svg, a DXF layout when it ends in .dxf). Prints one JSON line; returns the exit code.
int exportSheetCommand(const QString& ifcPath, const QString& number, const QString& path);

} // namespace kimcad
