// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QVector>
#include <QWidget>

#include "Cuts.h"

class QTableWidget;
class QTableWidgetItem;
class QPushButton;

namespace kimbim {

// D95: the active 3D view's cut planes: on/off, kind, offset along the normal, oblique tilt, with
// flip and delete. Editing a cell applies the change live.
class CutPlanesPanel : public QWidget {
    Q_OBJECT
public:
    explicit CutPlanesPanel(QWidget* parent = nullptr);

    void setPlanes(const QVector<CutPlane>& planes, int selected);
    int selectedRow() const;
    QTableWidget* table() const { return m_table; }

signals:
    void addVerticalRequested();
    void addHorizontalRequested();
    void addObliqueRequested();
    void addFaceRequested();
    void enabledChanged(int index, bool on);
    void offsetChanged(int index, double offset);
    void angleChanged(int index, double degrees);
    void flipRequested(int index);
    void deleteRequested(int index);
    void planeSelected(int index);

private:
    void onItemChanged(QTableWidgetItem* item);
    void onSelectionChanged();

    QTableWidget* m_table = nullptr;
    QPushButton* m_flip = nullptr;
    QPushButton* m_delete = nullptr;
    bool m_filling = false;
};

} // namespace kimbim
