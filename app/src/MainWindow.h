// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QMainWindow>

namespace kimcad {

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);

private:
    void buildMenus();
    void showAbout();
};

} // namespace kimcad
