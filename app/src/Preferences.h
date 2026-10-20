// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>
#include <QStringList>

namespace kimbim {
// User preferences, per computer (D72): a readable preferences.json in the user's settings folder.
class Preferences {
public:
    explicit Preferences(const QString& path = QString()); // empty: in memory only (tests, self-test)
    static QString defaultPath();       // AppConfigLocation/preferences.json
    static QJsonObject defaults();
    bool load();                        // false if the file was garbled (kept aside as <file>.bad)
    bool save() const;                  // false if it could not be written (or in memory only)
    QString path() const { return m_path; }
    QJsonValue value(const QString& key) const;  // falls back to defaults()
    void setValue(const QString& key, const QJsonValue& value);
    QString language() const;           // "auto", "en" or "es"
    QString templatesFolder() const;
    QString authorName() const;
    QString authorEmail() const;
    QString newViews() const;           // "tab" or "window"
    QString openIfc() const;            // "make_kim" or "edit_ifc"
    QString autoVersion() const;        // "off", "saves" or "minutes"
    int autoVersionEvery() const;
    int recoveryMinutes() const;
    bool trueLineWeights() const;
    QString scrollNavigation() const;   // D89: "auto", "zoom" (mouse wheel zooms) or "pan" (touchpad scroll pans)       // D73: View > True line weights
    double fieldOfView() const;         // D92: the perspective camera's vertical field of view, degrees (default 45)
    // D92: which controls the title bar holds (all on by default).
    bool titleBarLevels() const;
    bool titleBarCut() const;
    bool titleBarVersions() const;
    // D92: selection
    QString selectSimilarScope() const; // "class_predefined", "type" or "class"
    QString boxSelection() const;       // "direction", "partial" or "entire"
    double largeIfcMb() const;
    bool askImportStatus() const;       // D74: opening an IFC offers to mark elements without a renovation status          // an IFC this large asks before making a .kim; 0: never asks
    // Drawing generation: how long to wait before giving up (seconds; 0 = no limit) and the
    // hidden-line mode ("exact" is faster on BREP-heavy models, "poly" on curved ones).
    int drawingTimeout() const;
    QString drawingHlr() const;
    QStringList recent() const;
    void addRecent(const QString& path); // most recent first, no duplicates, at most 10
    QByteArray layout() const;
    void setLayout(const QByteArray& state);
    QByteArray windowGeometry() const; // D75: the main window's size, position and maximized state
    void setWindowGeometry(const QByteArray& geometry);
private:
    QString m_path;
    QJsonObject m_data; // only what was set or loaded; unknown keys survive a save
};
}
