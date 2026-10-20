// SPDX-License-Identifier: GPL-3.0-or-later
#include "Translations.h"

#include <QLocale>
#include <QTranslator>

namespace kimbim {

bool installTranslator(QCoreApplication& app, const QString& lang)
{
    if (lang == QLatin1String("en"))
        return true;
    auto* translator = new QTranslator(&app);
    if (!translator->load(QStringLiteral(":/i18n/kimbim_%1.qm").arg(lang))) {
        delete translator;
        return false;
    }
    app.installTranslator(translator);
    return true;
}

QString pickLanguage(const QString& requested)
{
    if (requested == QLatin1String("en") || requested == QLatin1String("es"))
        return requested;
    return QLocale::system().language() == QLocale::Spanish ? QStringLiteral("es") : QStringLiteral("en");
}

} // namespace kimbim
