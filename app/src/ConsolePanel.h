// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QPlainTextEdit>
#include <QStringList>
#include <QWidget>

class QPushButton;

namespace kimbim {

// The console's input (D82): Enter runs, Shift+Enter adds a line, Up/Down on the first/last line recall
// earlier input. Python is highlighted (keywords, strings, comments, numbers).
class ConsoleInput : public QPlainTextEdit {
    Q_OBJECT
public:
    explicit ConsoleInput(QWidget* parent = nullptr);
    void addHistory(const QString& code);
    QStringList history() const { return m_history; }
    void historyUp();
    void historyDown();

signals:
    void runRequested();

protected:
    void keyPressEvent(QKeyEvent* event) override;

private:
    QStringList m_history;
    int m_index = 0;   // m_history.size() = the draft being typed
    QString m_draft;
};

// The Python console panel (D82, doc 14 section 20; pyRevit's and Bonsai's console, Archicad's Python
// palette): output above (input echoed with ">>>", stdout, tracebacks in red), input below, and Run, Run
// script..., Clear. The panel only shows and asks; the main window runs the code in the embedded Python.
class ConsolePanel : public QWidget {
    Q_OBJECT
public:
    explicit ConsolePanel(QWidget* parent = nullptr);

    ConsoleInput* input() const { return m_input; }
    QString outputText() const;
    void appendInput(const QString& code);
    void appendOutput(const QString& text, bool error);
    void clearOutput();
    void run(); // the Run button: emits runRequested with the input, keeps it in the history

signals:
    void runRequested(const QString& code);
    void runFileRequested();

private:
    void append(const QString& text, const QColor& color);
    QPlainTextEdit* m_output = nullptr;
    ConsoleInput* m_input = nullptr;
};

} // namespace kimbim
