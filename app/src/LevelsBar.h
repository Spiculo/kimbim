// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QWidget>

class QAction;
class QComboBox;
class QToolButton;

namespace kimbim {

// The active level (IfcBuildingStorey) for drawing and plan views. D75: "Add level..." and "New
// model..." are in the drop-down beside it (and in the Model menu), not buttons of their own; D79:
// so is "Levels..." (the levels table). Levels are listed by elevation; refreshing keeps the active
// one when it still exists. Levels marked not to show in the level list are left out (D79), unless
// it is the active one.
class LevelsBar : public QWidget {
    Q_OBJECT
public:
    explicit LevelsBar(QWidget* parent = nullptr);

    // [{guid, name, elevation (m), model}] from app_bridge.storeys: building levels by elevation,
    // then the models (owner feedback: a dedicated "model" section on the levels).
    void setStoreys(const QJsonArray& storeys);
    bool activeIsModel() const;
    bool activeIsWorksheet() const; // D98
    QString activeName() const;
    void setActive(const QString& guid);
    // D98: Archicad's Go to story above/below: the next building level up (+1) or down (-1); false at the end.
    bool step(int direction);
    QString activeStorey() const;
    double activeElevation() const;
    int count() const;

    QComboBox* combo() const { return m_combo; }
    QAction* addLevelAction() const { return m_add; }
    QAction* newModelAction() const { return m_newModel; }
    QAction* newWorksheetAction() const { return m_newWorksheet; }
    QAction* levelsAction() const { return m_levels; }
    QToolButton* menuButton() const { return m_menu; }

signals:
    void activeStoreyChanged(const QString& guid, double elevation);
    void addLevelRequested();
    void newModelRequested();
    void newWorksheetRequested(); // D98
    void renameWorksheetRequested(const QString& guid);
    void deleteWorksheetRequested(const QString& guid);
    void levelsDialogRequested();

private:
    void onIndexChanged(int index);

    QComboBox* m_combo;
    QToolButton* m_menu;
    QAction* m_add;
    QAction* m_newModel;
    QAction* m_newWorksheet;
    QAction* m_renameWorksheet;
    QAction* m_deleteWorksheet;
    QAction* m_levels;
    QString m_active;
    bool m_filling = false;
};

} // namespace kimbim
