// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QJsonObject>

class QCheckBox;
class QComboBox;
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

private:
    QJsonObject m_settings;
    QDoubleSpinBox* m_cut;
    QSpinBox* m_scale;
    QComboBox* m_paper;
    QComboBox* m_unit;
    QComboBox* m_areaUnit; // D92
    QComboBox* m_levelReference; // D92: project zero, level or sea level
    QDoubleSpinBox* m_seaLevel; // D92: project zero above sea level
    QComboBox* m_northStyle; // D92: the north arrow and scale bar symbols
    QComboBox* m_scaleBarStyle;
    QComboBox* m_importedWalls; // D92
    QCheckBox* m_partialDups; // D92: model checks
    QSpinBox* m_decimals;
};

} // namespace kimbim
