// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>
#include <QStringList>

class QCheckBox;
class QComboBox;
class QCheckBox;
class QDoubleSpinBox;
class QSpinBox;

namespace kimbim {

// File > Project settings (D72): the settings kept with the project (.kim or folder) and versioned.
class ProjectSettingsDialog : public QDialog {
    Q_OBJECT
public:
    // kept: the open document keeps them (false for a plain IFC: the dialog says so).
    ProjectSettingsDialog(const QJsonObject& settings, bool kept, QWidget* parent);
    QJsonObject changes() const; // only the settings that differ from the ones passed in
    // D93: the renovation style presets to choose from (the active one is a project setting).
    void setRenovationPresets(const QStringList& presets);

private:
    QJsonObject m_settings;
    QDoubleSpinBox* m_cut;
    QDoubleSpinBox* m_viewDepth;
    QComboBox* m_scale;
    QComboBox* m_paper;
    QComboBox* m_unit;
    QComboBox* m_areaUnit; // D92
    QComboBox* m_levelReference; // D92: project zero, level or sea level
    QDoubleSpinBox* m_seaLevel; // D92: project zero above sea level
    QComboBox* m_northStyle; // D92: the north arrow and scale bar symbols
    QComboBox* m_scaleBarStyle;
    QDoubleSpinBox* m_stairRiser; // D92: stair defaults and drawing settings
    QDoubleSpinBox* m_stairTread;
    QComboBox* m_stairTreadMode;
    QComboBox* m_stairArrow;
    QCheckBox* m_stairNumbers;
    QComboBox* m_importedWalls; // D92
    QCheckBox* m_partialDups; // D92: model checks
    QSpinBox* m_decimals;
    QComboBox* m_ifcStatus;
    QComboBox* m_renovationPreset;
    QComboBox* m_legendMode;
    QCheckBox* m_planSymbols;
};

} // namespace kimbim
