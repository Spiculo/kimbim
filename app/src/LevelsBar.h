// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QWidget>

class QComboBox;
class QToolButton;

namespace kimcad {

// The active level (IfcBuildingStorey) for drawing and plan views, plus "Add level...".
// Levels are listed by elevation; refreshing keeps the active one when it still exists.
class LevelsBar : public QWidget {
    Q_OBJECT
public:
    explicit LevelsBar(QWidget* parent = nullptr);

    void setStoreys(const QJsonArray& storeys); // [{guid, name, elevation (m)}] from app_bridge.storeys
    void setActive(const QString& guid);
    QString activeStorey() const;
    double activeElevation() const;
    int count() const;

    QComboBox* combo() const { return m_combo; }
    QToolButton* addButton() const { return m_add; }

signals:
    void activeStoreyChanged(const QString& guid, double elevation);
    void addLevelRequested();

private:
    void onIndexChanged(int index);

    QComboBox* m_combo;
    QToolButton* m_add;
    QString m_active;
    bool m_filling = false;
};

} // namespace kimcad
