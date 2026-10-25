// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QPointer>
#include <QStringList>

class QComboBox;
class QLabel;
class QLineEdit;
class QPushButton;
class QStackedWidget;
class QTableWidget;
class QTimer;

namespace kimbim {

class JsonTreeEditor;
class MainWindow;
class ParameterForm;
class PlanSymbolView;
class Viewport;

// The Object Editor (D101, doc 16 §6): makes and edits a library object's definition, the `.kimobj` JSON
// (a draft, objedit.py). Left: the object's id, names, category and IFC class; its parameters and its
// material slots as tables. Middle: the draft drawn by the app's own 3D view in a scratch scene, or its
// plan symbol. Right: Try values, a parameter form that changes the preview, never the defaults. Any edit
// checks the draft after a short pause: the fields whose path has an error turn red (the message as their
// tooltip), the preview keeps the last good shape and both saves are disabled until it is fixed. The parts,
// components and symbol are a tree of their JSON (JsonTreeEditor); what no tab shows is kept as it came.
class ObjectEditorDialog : public QDialog {
    Q_OBJECT
public:
    // `source` as objedit.object_draft takes it: "new", a library id (a copy), "office:<id>",
    // "project:<id>" or "type:<GlobalId>" (Customise a copy).
    ObjectEditorDialog(MainWindow* window, const QString& source, QWidget* parent = nullptr);

    QJsonObject draft() const; // the definition as the fields have it
    void setDraft(const QJsonObject& draft); // fills the fields; the draft as it is now counts as unchanged
    QStringList errorPaths() const { return m_errorPaths; } // the last check's field paths
    // Saves the draft to "office" (a .kimobj file in the office folder) or "project" (one undo step). An
    // object the office library has asks to replace it, unless `replace` or it is the office object the
    // dialog opened, its id unchanged. On success the dialog accepts.
    bool saveTo(const QString& target, bool replace = false);
    // The placed objects of this object that the last office save left outdated: their GUIDs (MainWindow
    // offers to update just those) and how many.
    QStringList outdatedAfterSave() const { return m_outdated; }
    bool isDirty() const;
    void reject() override; // Cancel or Esc: asks before discarding changes

private:
    void scheduleCheck();
    void check();
    void updatePreview(const QJsonObject& draft);
    void showErrors();
    void markErrors(const QJsonArray& errors);
    void fillParams(const QJsonArray& params);
    QJsonArray params() const;
    void fillMaterials(const QJsonObject& materials);
    QJsonObject materials() const;
    void addParam();
    void moveParam(int by);
    void addMaterial();

    QPointer<MainWindow> m_window;
    QJsonObject m_base;  // the draft as loaded: the fields the dialog does not edit come from it
    QJsonObject m_clean; // draft() right after loading (isDirty)
    QString m_checked;   // the draft text checked last
    QStringList m_errorPaths;
    QStringList m_checkErrors; // "path: message" lines of the last check
    QString m_previewError;
    QJsonObject m_tried; // the Try values the user set
    QString m_lastTried;
    bool m_valid = false;
    bool m_hasPreview = false;
    bool m_office = false; // an office library folder is set
    QStringList m_outdated;
    QLineEdit* m_id;
    QLineEdit* m_name;
    QLineEdit* m_nameEs;
    QComboBox* m_category;
    QComboBox* m_ifcClass;
    QLineEdit* m_predefined;
    QTableWidget* m_params;
    QTableWidget* m_materials;
    JsonTreeEditor* m_parts;
    Viewport* m_preview;
    PlanSymbolView* m_plan;
    QStackedWidget* m_views;
    ParameterForm* m_try;
    QLabel* m_error;
    QPushButton* m_saveProject;
    QPushButton* m_saveOffice;
    QTimer* m_timer;
    QString m_source; // as object_draft took it
};

} // namespace kimbim
