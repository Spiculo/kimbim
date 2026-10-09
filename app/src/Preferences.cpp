// SPDX-License-Identifier: GPL-3.0-or-later
#include "Preferences.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QStandardPaths>

namespace kimcad {

namespace {
const QStringList kViews{QStringLiteral("tab"), QStringLiteral("window")};
const QStringList kOpenIfc{QStringLiteral("make_kim"), QStringLiteral("edit_ifc")};
const QStringList kAutoVersion{QStringLiteral("off"), QStringLiteral("saves"), QStringLiteral("minutes")};
const QStringList kLanguages{QStringLiteral("auto"), QStringLiteral("en"), QStringLiteral("es")};

QString oneOf(const QJsonValue& v, const QStringList& allowed)
{
    const QString s = v.toString();
    return allowed.contains(s) ? s : allowed.first();
}
} // namespace

Preferences::Preferences(const QString& path)
    : m_path(path)
{
}

QString Preferences::defaultPath()
{
    return QDir(QStandardPaths::writableLocation(QStandardPaths::AppConfigLocation)).filePath(QStringLiteral("preferences.json"));
}

QJsonObject Preferences::defaults()
{
    const QString docs = QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation);
    return {
        {"language", "auto"},
        {"templates_folder", QDir(docs).filePath(QStringLiteral("KIMCAD Templates"))},
        {"author_name", ""},
        {"author_email", ""},
        {"new_views", "tab"},
        {"open_ifc", "make_kim"},
        {"auto_version", "off"},
        {"auto_version_every", 10},
        {"recovery_minutes", 5},
        {"true_line_weights", false},
        {"large_ifc_mb", 5},
        {"ask_import_status", true},
        {"recent", QJsonArray()},
    };
}

bool Preferences::load()
{
    m_data = {};
    if (m_path.isEmpty() || !QFile::exists(m_path))
        return true;
    QFile f(m_path);
    if (!f.open(QIODevice::ReadOnly))
        return false;
    QJsonParseError error;
    const QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &error);
    f.close();
    if (error.error != QJsonParseError::NoError || !doc.isObject()) {
        QFile::remove(m_path + QStringLiteral(".bad"));
        QFile::rename(m_path, m_path + QStringLiteral(".bad")); // kept for inspection
        return false;
    }
    m_data = doc.object();
    return true;
}

bool Preferences::save() const
{
    if (m_path.isEmpty())
        return false;
    QDir().mkpath(QFileInfo(m_path).absolutePath());
    QSaveFile f(m_path);
    if (!f.open(QIODevice::WriteOnly))
        return false;
    f.write(QJsonDocument(m_data).toJson(QJsonDocument::Indented));
    return f.commit();
}

QJsonValue Preferences::value(const QString& key) const
{
    return m_data.contains(key) ? m_data.value(key) : defaults().value(key);
}

void Preferences::setValue(const QString& key, const QJsonValue& value)
{
    m_data.insert(key, value);
}

QString Preferences::language() const { return oneOf(value("language"), kLanguages); }
QString Preferences::newViews() const { return oneOf(value("new_views"), kViews); }
QString Preferences::openIfc() const { return oneOf(value("open_ifc"), kOpenIfc); }
QString Preferences::autoVersion() const { return oneOf(value("auto_version"), kAutoVersion); }
QString Preferences::authorName() const { return value("author_name").toString().trimmed(); }
QString Preferences::authorEmail() const { return value("author_email").toString().trimmed(); }

QString Preferences::templatesFolder() const
{
    const QString s = value("templates_folder").toString();
    return s.isEmpty() ? defaults().value("templates_folder").toString() : s;
}

int Preferences::autoVersionEvery() const
{
    const QJsonValue v = value("auto_version_every");
    return v.isDouble() && v.toInt() >= 1 ? v.toInt() : 10;
}

double Preferences::largeIfcMb() const
{
    const QJsonValue v = value("large_ifc_mb");
    return v.isDouble() && v.toDouble() >= 0.0 ? v.toDouble() : 5.0;
}

bool Preferences::askImportStatus() const
{
    return value("ask_import_status").toBool(true);
}

bool Preferences::trueLineWeights() const
{
    return value("true_line_weights").toBool(false);
}

int Preferences::recoveryMinutes() const
{
    const QJsonValue v = value("recovery_minutes");
    return v.isDouble() && v.toInt() >= 0 ? v.toInt() : 5;
}

QStringList Preferences::recent() const
{
    QStringList out;
    for (const auto& v : value("recent").toArray())
        if (!v.toString().isEmpty())
            out << v.toString();
    return out;
}

void Preferences::addRecent(const QString& path)
{
    QStringList r = recent();
    r.removeAll(path);
    r.prepend(path);
    while (r.size() > 10)
        r.removeLast();
    setValue("recent", QJsonArray::fromStringList(r));
}

QByteArray Preferences::windowGeometry() const
{
    return QByteArray::fromBase64(value("window_geometry").toString().toLatin1());
}

void Preferences::setWindowGeometry(const QByteArray& geometry)
{
    setValue("window_geometry", QString::fromLatin1(geometry.toBase64()));
}

QByteArray Preferences::layout() const
{
    return QByteArray::fromBase64(value("layout").toString().toLatin1());
}

void Preferences::setLayout(const QByteArray& state)
{
    setValue("layout", QString::fromLatin1(state.toBase64()));
}

} // namespace kimcad
