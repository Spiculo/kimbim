// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QDialog>
#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QSet>
#include <QString>
#include <QStringList>

#include "Graphics.h"

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPushButton;
class QSlider;
class QSpinBox;
class QTabWidget;
class QTableWidget;

namespace kimbim {

// The Materials dialog's data (D96, Archicad's Surfaces, Building Materials and Composites), without
// widgets: working copies of app_bridge.materials_state's lists, edited in the dialog and sent back
// as one change (app_bridge.apply_materials, one undo step).
class MaterialsEdits {
public:
    enum Kind { Surfaces = 0, Materials = 1, Composites = 2 };

    explicit MaterialsEdits(const QJsonObject& state = {});
    int count(Kind k) const { return int(m_items[k].size()); }
    QJsonObject item(Kind k, int i) const { return m_items[k].at(i).toObject(); }
    int indexOf(Kind k, const QString& name) const;
    QStringList names(Kind k) const;
    // Composites of one type ("IfcWallType", ...), for the replacement choice.
    QStringList compositeNames(const QString& type) const;

    // Replaces item i's fields (the key and used_by stay).
    void setItem(Kind k, int i, const QJsonObject& fields);
    // A new item from `fields` with a name not used yet (`base`, then "base 2"...); returns its index.
    int add(Kind k, QJsonObject fields, const QString& base);
    int duplicate(Kind k, int i);
    // Deletes item i; `replace` names what takes its place where it is used (materials, composites).
    void remove(Kind k, int i, const QString& replace = QString());
    // An error for a name clash or an empty name, else "".
    QString checkName(Kind k, int i, const QString& name) const;

    bool modified() const;
    // {surfaces, materials, composites, deleted}: only what changed (app_bridge.apply_materials).
    QJsonObject changes() const;
    QStringList patterns() const { return m_patterns; }

private:
    QJsonArray m_items[3];
    QSet<int> m_dirty[3]; // indices of changed or new items
    QJsonObject m_deleted;
    QStringList m_patterns;
    bool m_removed = false;
};

class MaterialsDialog : public QDialog {
    Q_OBJECT
public:
    MaterialsDialog(const QJsonObject& state, const QHash<int, LineStyle>& pens, QWidget* parent = nullptr);
    void showTab(MaterialsEdits::Kind kind);
    const MaterialsEdits& edits() const { return m_edits; }

private:
    void buildSurfaces(QWidget* page);
    void buildMaterials(QWidget* page);
    void buildComposites(QWidget* page);
    void fillList(MaterialsEdits::Kind k, int select);
    void loadSurface(int i);
    void loadMaterial(int i);
    void loadComposite(int i);
    void storeSurface();
    void storeMaterial();
    void storeComposite();
    void rebuildLayers(const QJsonArray& layers);
    QJsonArray layersFromTable() const;
    void updateTotal();
    void newItem(MaterialsEdits::Kind k);
    void duplicateItem(MaterialsEdits::Kind k);
    void deleteItem(MaterialsEdits::Kind k);
    int current(MaterialsEdits::Kind k) const;
    void setPenButton(QPushButton* b, int pen);
    void accept() override;

    MaterialsEdits m_edits;
    QHash<int, LineStyle> m_pens;
    QTabWidget* m_tabs = nullptr;
    QListWidget* m_lists[3] = {};
    QLineEdit* m_filters[3] = {};
    bool m_loading = false;
    // surfaces
    QLineEdit* m_sName = nullptr;
    QPushButton* m_sColour = nullptr;
    QSlider* m_sTransparency = nullptr;
    QSlider* m_sShine = nullptr;
    QComboBox* m_sReflectance = nullptr;
    QLabel* m_sUsed = nullptr;
    QString m_colour;
    // building materials
    QLineEdit* m_mName = nullptr;
    QLineEdit* m_mId = nullptr;
    QLineEdit* m_mCategory = nullptr;
    QLineEdit* m_mManufacturer = nullptr;
    QLineEdit* m_mDescription = nullptr;
    QComboBox* m_mSurface = nullptr;
    QComboBox* m_mPattern = nullptr;
    QPushButton* m_mPen = nullptr;
    QPushButton* m_mBg = nullptr;
    QSpinBox* m_mPriority = nullptr;
    QDoubleSpinBox* m_mDensity = nullptr;
    QDoubleSpinBox* m_mConductivity = nullptr;
    QDoubleSpinBox* m_mHeat = nullptr;
    QLabel* m_mUsed = nullptr;
    int m_pen = 0, m_bg = 0;
    // composites
    QLineEdit* m_cName = nullptr;
    QLabel* m_cType = nullptr;
    QTableWidget* m_cLayers = nullptr;
    QLabel* m_cTotal = nullptr;
    QLabel* m_cUsed = nullptr;
};

} // namespace kimbim
