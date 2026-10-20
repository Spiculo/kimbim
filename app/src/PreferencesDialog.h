// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>

class QComboBox;
class QCheckBox;
class QLabel;
class QLineEdit;
class QSpinBox;

namespace kimbim {

class Preferences;

// Edit > Preferences (D72): what this computer remembers, whatever project is open.
class PreferencesDialog : public QDialog {
    Q_OBJECT
public:
    PreferencesDialog(Preferences& prefs, QWidget* parent);
    void apply(); // writes every field to the preferences (OK calls it)
    void accept() override;

private:
    Preferences& m_prefs;
    QComboBox* m_language;
    QLabel* m_restartNote;
    QLineEdit* m_templates;
    QLineEdit* m_officeLibrary;
    QLineEdit* m_authorName;
    QLineEdit* m_authorEmail;
    QComboBox* m_newViews;
    QComboBox* m_openIfc;
    QComboBox* m_autoVersion;
    QSpinBox* m_autoEvery;
    QSpinBox* m_recovery;
    QSpinBox* m_largeIfc;
    QSpinBox* m_drawingTimeout;
    QComboBox* m_drawingHlr;
    QComboBox* m_scroll; // D89
    QSpinBox* m_fieldOfView; // D92
    QCheckBox* m_northArrow; // D92: north indicator on plans
    QCheckBox* m_titleLevels; // D92: which controls the title bar holds
    QCheckBox* m_titleCut;
    QCheckBox* m_titleVersions;
    QComboBox* m_selectSimilar; // D92
    QComboBox* m_boxSelection;
    QCheckBox* m_splitJoin; // D92
    QComboBox* m_mergeProps; // D92
    QCheckBox* m_meshVertexSnaps; // D92
    QSpinBox* m_underlayOpacity; // D92: new underlay defaults
    QCheckBox* m_underlayGrey;
    QLineEdit* m_underlayTint;
    QCheckBox* m_underlayLayerPerFile;
};

} // namespace kimbim
