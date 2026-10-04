// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QCoreApplication>
#include <QString>

namespace kimcad {

// Installs the translator for `lang` ("en" is the source language and needs none).
// Returns false for languages KIMCAD does not ship (docs/04 §12: English and Spanish).
bool installTranslator(QCoreApplication& app, const QString& lang);

// The language to use: an explicit "en"/"es" wins, otherwise the system locale, otherwise English.
QString pickLanguage(const QString& requested);

} // namespace kimcad
