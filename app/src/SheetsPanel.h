// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonArray>
#include <QWidget>

class QListWidget;

namespace kimcad {

// Sheets (Slice 16, Archicad's layouts): new A1/A3 sheet, open, place the drawing selected in the
// Drawings panel, delete.
class SheetsPanel : public QWidget {
    Q_OBJECT
public:
    explicit SheetsPanel(QWidget* parent = nullptr);

    void setSheets(const QJsonArray& sheets); // [{number, title, paper, ...}] from the bridge
    QString selectedSheet() const;
    int count() const;
    QListWidget* list() const { return m_list; }

signals:
    void newRequested(const QString& paper);
    void openRequested(const QString& number);
    void placeRequested(const QString& number);
    void deleteRequested(const QString& number);

private:
    QListWidget* m_list;
};

} // namespace kimcad
