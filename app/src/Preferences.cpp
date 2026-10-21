// SPDX-License-Identifier: GPL-3.0-or-later
#include "Preferences.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QStandardPaths>

namespace kimbim {

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
        {"templates_folder", QDir(docs).filePath(QStringLiteral("KimBim Templates"))},
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
        {"drawing_timeout", 300},
        {"drawing_hlr", "exact"},
        {"scroll_navigation", "auto"},
        {"tracker", "always"},
        {"angle_mode", "absolute"},
        {"typed_length_unit", "metres"},
        {"tab_annotations", true},
        {"field_of_view", 45.0},
        {"north_arrow", true},
        {"mesh_vertex_snaps", false},
        {"keep_rectangles_rectangular", false},
        {"underlay_opacity", 0.5},
        {"underlay_greyscale", false},
        {"underlay_tint", ""},
        {"underlay_layer_per_file", false},
        {"title_bar_levels", true},
        {"title_bar_cut", true},
        {"title_bar_versions", true},
        {"select_similar_scope", "class_predefined"},
        {"box_selection", "direction"},
        {"split_join", true},
        {"merge_props", "keep"},
        {"object_edit_scope", "selection"},
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

int Preferences::drawingTimeout() const
{
    const QJsonValue v = value("drawing_timeout");
    return v.isDouble() && v.toInt() >= 0 ? v.toInt() : 300;
}

QString Preferences::drawingHlr() const
{
    return oneOf(value("drawing_hlr"), {QStringLiteral("exact"), QStringLiteral("poly")});
}

QString Preferences::scrollNavigation() const
{
    const QString v = value("scroll_navigation").toString();
    return v == QLatin1String("zoom") || v == QLatin1String("pan") || v == QLatin1String("precision")
        ? v : QStringLiteral("auto");
}

QString Preferences::trackerMode() const
{
    const QString v = value("tracker").toString();
    return v == QLatin1String("typing") || v == QLatin1String("off") ? v : QStringLiteral("always");
}

QString Preferences::angleMode() const
{
    const QString v = value("angle_mode").toString();
    return v == QLatin1String("relative") || v == QLatin1String("bearing") ? v : QStringLiteral("absolute");
}

QString Preferences::typedLengthUnit() const
{
    return value("typed_length_unit").toString() == QLatin1String("project") ? QStringLiteral("project")
                                                                             : QStringLiteral("metres");
}

bool Preferences::tabAnnotations() const { return value("tab_annotations").toBool(true); }

double Preferences::fieldOfView() const
{
    const QJsonValue v = value("field_of_view");
    return v.isDouble() && v.toDouble() >= 5.0 && v.toDouble() <= 120.0 ? v.toDouble() : 45.0;
}

bool Preferences::northArrowPlans() const { return value("north_arrow").toBool(true); }
bool Preferences::meshVertexSnaps() const { return value("mesh_vertex_snaps").toBool(false); }
bool Preferences::keepRectanglesRectangular() const { return value("keep_rectangles_rectangular").toBool(false); }

// D92: the defaults a new underlay gets.
double Preferences::underlayOpacity() const
{
    const QJsonValue v = value("underlay_opacity");
    return v.isDouble() && v.toDouble() >= 0.05 && v.toDouble() <= 1.0 ? v.toDouble() : 0.5;
}

bool Preferences::underlayGreyscale() const { return value("underlay_greyscale").toBool(false); }
QString Preferences::underlayTint() const { return value("underlay_tint").toString().trimmed(); }
bool Preferences::underlayLayerPerFile() const { return value("underlay_layer_per_file").toBool(false); }

bool Preferences::titleBarLevels() const { return value("title_bar_levels").toBool(true); }
bool Preferences::titleBarCut() const { return value("title_bar_cut").toBool(true); }
bool Preferences::titleBarVersions() const { return value("title_bar_versions").toBool(true); }

QString Preferences::selectSimilarScope() const
{
    const QString v = value("select_similar_scope").toString();
    return v == QLatin1String("type") || v == QLatin1String("class") ? v : QStringLiteral("class_predefined");
}

QString Preferences::boxSelection() const
{
    const QString v = value("box_selection").toString();
    return v == QLatin1String("partial") || v == QLatin1String("entire") ? v : QStringLiteral("direction");
}

bool Preferences::splitJoin() const { return value("split_join").toBool(true); }

QString Preferences::objectEditScope() const
{
    return value("object_edit_scope").toString() == QLatin1String("ask") ? QStringLiteral("ask") : QStringLiteral("selection");
}

QString Preferences::mergeProps() const
{
    // D92: merging collinear walls keeps the first's properties (default) or refuses when they differ.
    return value("merge_props").toString() == QLatin1String("refuse") ? QStringLiteral("refuse") : QStringLiteral("keep");
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

} // namespace kimbim
