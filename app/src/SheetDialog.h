// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QColor>
#include <QDialog>
#include <QJsonArray>
#include <QJsonObject>
#include <QSet>
#include <QString>
#include <QVector>

class QComboBox;
class QDoubleSpinBox;
class QLineEdit;
class QListWidget;
class QPushButton;
class QSpinBox;
class QTableWidget;
class QTableWidgetItem;

namespace kimbim {

// The Sheets panel's Settings...: the sheet's title, number, paper and background, and the drawings
// already placed on it (scale, or remove). One undo step through the bridge's update_sheet.
class SheetSettingsDialog : public QDialog {
    Q_OBJECT
public:
    explicit SheetSettingsDialog(const QJsonObject& sheet, QWidget* parent = nullptr);

    QJsonObject changes() const;
    QTableWidget* placedTable() const { return m_placed; }

signals:
    void titleBlockRequested(); // the title block's own text fields (the existing editor)

private:
    void chooseBackground();
    void updateBackground();

    QLineEdit* m_title;
    QLineEdit* m_number;
    QComboBox* m_paper;
    QPushButton* m_background;
    QPushButton* m_titleBlock;
    QColor m_colour;
    QTableWidget* m_placed;
    struct Row {
        QString guid;
        int scale;
        QSpinBox* spin;
        QTableWidgetItem* remove;
    };
    QVector<Row> m_rows;
};

// Place drawing...: choose a drawing (the ones already on the sheet are disabled) and its scale.
class PlaceDrawingDialog : public QDialog {
    Q_OBJECT
public:
    PlaceDrawingDialog(const QJsonArray& drawings, const QSet<QString>& placed, const QString& preferred,
        int scale, QWidget* parent = nullptr);

    QString drawing() const;
    int scale() const;

private:
    void updatePlace();

    QListWidget* m_drawings;
    QSpinBox* m_scale;
    QPushButton* m_place;
};

// Drawing settings... on a placed drawing: its title (the drawing's name), scale and position.
class PlacedDrawingDialog : public QDialog {
    Q_OBJECT
public:
    PlacedDrawingDialog(const QString& title, int scale, double x, double y, QWidget* parent = nullptr);

    QString title() const;
    int scale() const;
    double x() const;
    double y() const;

public slots:
    void accept() override;

private:
    QLineEdit* m_title;
    QSpinBox* m_scale;
    QDoubleSpinBox* m_x;
    QDoubleSpinBox* m_y;
};

} // namespace kimbim
