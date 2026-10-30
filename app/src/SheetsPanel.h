// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QJsonObject>
#include <QStringList>

#include <QJsonArray>
#include <QWidget>

class QListWidget;
class QMenu;

namespace kimbim {

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
    // D73: the purposes a sheet can print with, and each sheet's ({number: purpose}).
    void setPurposes(const QStringList& names, const QJsonObject& sheetPurposes);
    QMenu* purposeMenu(const QString& number); // the right-click submenu (owned by the caller)

signals:
    void newRequested(const QString& paper);
    void openRequested(const QString& number);
    void placeRequested(const QString& number);
    void settingsRequested(const QString& number); // title, number, paper, background, placed drawings
    void legendRequested(const QString& number); // D74: place a legend of the sheet's purpose
    void symbolRequested(const QString& number, const QString& kind); // D87: north, scalebar, cloud
    void deleteRequested(const QString& number);
    void purposeRequested(const QString& number, const QString& purpose); // "" = the current purpose

private:
    QListWidget* m_list;
    QStringList m_purposes;
    QJsonObject m_sheetPurposes;
};

} // namespace kimbim
