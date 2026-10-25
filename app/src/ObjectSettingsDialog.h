// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QPointer>
#include <QWidget>

class QFormLayout;
class QLabel;
class QListWidget;
class QListWidgetItem;
class QMenu;
class QPushButton;
class QStackedWidget;
class QTimer;

namespace kimbim {

class MainWindow;
class Viewport;

// One control per parameter of a library object (D99): lengths, angles, counts, on/off, choices and
// building materials, under the definition's group headings, each named `param_<key>`. Python makes
// the form (object_form): limits that are formulas and show_when depend on the current values, so a
// choice or an on/off rebuilds it (queued). Used by the Object settings dialog.
class ParameterForm : public QWidget {
    Q_OBJECT
public:
    explicit ParameterForm(QWidget* parent = nullptr);
    // Show `key`'s parameters with these values (missing ones: the definition's defaults). With
    // `version` (D100), the parameters of that saved version's own stored definition.
    void setObject(const QString& key, const QJsonObject& values = {}, const QString& version = {});
    void setValues(const QJsonObject& values); // merged into the current ones; rebuilds
    QJsonObject values() const { return m_values; }
    bool isEmpty() const { return m_rows == 0; } // no parameters (an office IFC type)
    // Marks the field of `key` red with `reason` as its tooltip ("" clears every mark).
    void markInvalid(const QString& key, const QString& reason);

signals:
    void changed(const QString& key); // the user edited a value

private:
    void build();
    void edited(const QString& key, const QJsonValue& value, bool rebuild);
    QFormLayout* m_form;
    QString m_key;
    QString m_version;
    QJsonObject m_values;
    int m_rows = 0;
};

// The plan symbol of an object, drawn to fit (the dialog's Plan view). Property "symbolCurves": how
// many polylines it draws.
class PlanSymbolView : public QWidget {
    Q_OBJECT
public:
    explicit PlanSymbolView(QWidget* parent = nullptr);
    void setSymbol(const QJsonArray& symbol, double width, double depth);

protected:
    void paintEvent(QPaintEvent* event) override;

private:
    QJsonArray m_symbol;
    double m_width = 1.0, m_depth = 1.0;
};

// Object settings (D100, Archicad's Object settings): a modal dialog to customise a library object
// before placing it, or placed objects. Left: the saved versions (Default, the project's, then the
// office library's), Save as... and a right-click menu (Rename, Delete, Move to library). Middle: the
// object drawn by the app's own 3D view in a scratch scene (orbit with the mouse), or its plan symbol.
// Right: the parameters. The preview follows the values after a short pause; values that don't build
// keep the last good shape, show the reason and disable Place / Apply. Office IFC types (`ifc:` keys,
// fixed geometry) show the preview only.
class ObjectSettingsDialog : public QDialog {
    Q_OBJECT
public:
    enum class Mode { Place, Edit }; // the accept button: Place, or Apply (placed objects)
    ObjectSettingsDialog(MainWindow* window, const QString& key, Mode mode, QWidget* parent = nullptr);

    void selectVersion(const QString& id); // "" is Default; its values go to the controls and the preview
    void setValues(const QJsonObject& values); // unsaved values (merged over the current ones)
    QJsonObject values() const;
    // The chosen saved (or office) version's id; "" for Default, or values edited since it was picked.
    QString versionId() const { return m_versionId; }
    bool valid() const { return m_valid; } // the current values build
    QString objectKey() const { return m_key; }

    // Save as...: the current values as a new project version called `name` (a name the object has
    // asks to replace it, unless `replace`). False when it was not saved.
    bool saveAs(const QString& name, bool replace = false);
    bool renameVersion(const QString& id, const QString& name);
    bool deleteVersion(const QString& id);
    bool moveToLibrary(const QString& id, bool replace = false);
    // The right-click menu of a project version: Rename..., Delete, Move to library (disabled, with
    // the reason as its tooltip, without an office library folder).
    void fillVersionMenu(QMenu* menu, const QString& id);

private:
    void loadVersions(const QString& select);
    void schedulePreview();
    void updatePreview();
    void showPlan(bool plan);
    void onAccept();
    void saveAsDialog();
    QJsonObject versionById(const QString& id) const;
    bool editDone(const QJsonObject& result, const QString& failure);

    QPointer<MainWindow> m_window;
    QString m_key;
    Mode m_mode;
    bool m_fixed = false; // an office IFC type: preview only
    QJsonObject m_default;
    QJsonArray m_versions;
    QString m_versionId;
    // The version whose stored definition the form and previews use: the one picked last, kept while
    // its values are edited ("" for Default: the object's definition).
    QString m_source;
    QString m_lastEdited; // the parameter the user changed last (marked when the values fail)
    bool m_valid = true;
    bool m_hasPreview = false;
    QListWidget* m_list;
    Viewport* m_preview;
    PlanSymbolView* m_plan;
    QStackedWidget* m_views;
    ParameterForm* m_form;
    QLabel* m_error;
    QPushButton* m_accept;
    QPushButton* m_saveAs;
    QTimer* m_timer;
};

} // namespace kimbim
