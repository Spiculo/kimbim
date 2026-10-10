// SPDX-License-Identifier: GPL-3.0-or-later
// D82: the Python console in the main window: code runs on the open model, its edits are one undo step.
#include <QAction>
#include <QJsonArray>
#include <QJsonObject>
#include <QMenu>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QtTest>

#include "ConsolePanel.h"
#include "MainWindow.h"
#include "PythonEngine.h"
#include "Viewport.h"

namespace {

QAction* action(kimcad::MainWindow& w, const char* name)
{
    QAction* a = w.findChild<QAction*>(QString::fromLatin1(name));
    if (!a)
        qFatal("missing action %s", name);
    return a;
}

QString pyString(const QString& s)
{
    return QStringLiteral("r'%1'").arg(s);
}

} // namespace

class TestConsole : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QStandardPaths::setTestModeEnabled(true);
        QString error;
        QVERIFY2(kimcad::PythonEngine::instance().start(&error), qPrintable(error));
    }

    void countsTheHouseWallsAndUndoesAConsoleEdit()
    {
        // The exit-test house (tools/make_house.py), built through the engine like `pixi run house`.
        QTemporaryDir tmp;
        const QString house = tmp.filePath(QStringLiteral("house.ifc"));
        const QString tool = QDir(qEnvironmentVariable("KIMCAD_PYTHON_PATH")).absoluteFilePath(QStringLiteral("../tools/make_house.py"));
        QVERIFY(QFileInfo::exists(tool));
        const QJsonObject made = kimcad::PythonEngine::instance().callJson("console_run",
            {QStringLiteral("import runpy\nrunpy.run_path(%1)['build'](%2)['walls']").arg(pyString(tool), pyString(house)),
                QStringLiteral("[]")}).object();
        QVERIFY2(!made.value("error").toBool(), qPrintable(made.value("traceback").toString()));
        QCOMPARE(made.value("output").toString(), QStringLiteral("8\n"));

        kimcad::MainWindow w(nullptr, /*quiet=*/true);

        QSignalSpy done(&w, &kimcad::MainWindow::loadFinished);
        w.openFile(house);
        QVERIFY(done.wait(120000));
        kimcad::ConsolePanel* panel = w.consolePanel();
        QJsonObject r = w.runConsole(QStringLiteral("len(ifc.by_type(\"IfcWall\"))"));
        QVERIFY(r.value("ok").toBool());
        QCOMPARE(r.value("output").toString(), QStringLiteral("8\n"));
        QVERIFY(panel->outputText().contains(QStringLiteral("8")));
        QVERIFY(!action(w, "actionUndo")->isEnabled());

        // An edit through the console: one undo step, the views follow, Ctrl+Z takes it back.
        r = w.runConsole(QStringLiteral(
            "with edit():\n"
            "    for wall in ifc.by_type('IfcWall'):\n"
            "        wall.Name = 'Scripted'\n"
            "select(ifc.by_type('IfcWall')[:2])"));
        QVERIFY2(!r.value("error").toBool(), qPrintable(r.value("traceback").toString()));
        QVERIFY(r.value("edited").toBool());
        QCOMPARE(r.value("geometry").toObject().value("changed").toArray().size(), 8);
        QCOMPARE(w.selection().size(), 2);
        QAction* undo = action(w, "actionUndo");
        QVERIFY(undo->isEnabled());
        QCOMPARE(undo->shortcut(), QKeySequence(QKeySequence::Undo));
        QCOMPARE(w.runConsole(QStringLiteral("sorted({x.Name for x in ifc.by_type('IfcWall')})")).value("output").toString(),
            QStringLiteral("['Scripted']\n"));
        undo->trigger();
        QCOMPARE(w.runConsole(QStringLiteral("'Scripted' in {x.Name for x in ifc.by_type('IfcWall')}")).value("output").toString(),
            QStringLiteral("False\n"));
        QVERIFY(!undo->isEnabled()); // the eight renames were one step

        // A traceback reaches the panel; the console keeps working.
        r = w.runConsole(QStringLiteral("1/0"));
        QVERIFY(r.value("error").toBool());
        QVERIFY(panel->outputText().contains(QStringLiteral("ZeroDivisionError")));
    }

    void consoleIsInViewPanelsAndInputKeepsHistory()
    {
        kimcad::MainWindow w(nullptr, true);
        QAction* show = action(w, "actionConsole");
        QCOMPARE(show->shortcut(), QKeySequence(Qt::CTRL | Qt::ALT | Qt::Key_P));
        QVERIFY(w.findChild<QMenu*>(QStringLiteral("panelsMenu"))->actions().contains(show));
        QVERIFY(action(w, "actionRunScript"));
        show->trigger();
        kimcad::ConsolePanel* panel = w.consolePanel();
        kimcad::ConsoleInput* input = panel->input();
        input->setPlainText(QStringLiteral("a = 2"));
        QTest::keyClick(input, Qt::Key_Return); // Enter runs
        QVERIFY(input->toPlainText().isEmpty());
        input->setPlainText(QStringLiteral("if a:"));
        input->moveCursor(QTextCursor::End);
        QTest::keyClick(input, Qt::Key_Return, Qt::ShiftModifier); // Shift+Enter: a new, indented line
        QCOMPARE(input->toPlainText(), QStringLiteral("if a:\n    "));
        input->insertPlainText(QStringLiteral("print(a * 21)"));
        panel->run();
        QVERIFY(panel->outputText().contains(QStringLiteral("42")));
        QTest::keyClick(input, Qt::Key_Up);
        QCOMPARE(input->toPlainText(), QStringLiteral("if a:\n    print(a * 21)"));
        input->moveCursor(QTextCursor::Start);
        QTest::keyClick(input, Qt::Key_Up);
        QCOMPARE(input->toPlainText(), QStringLiteral("a = 2"));
        input->moveCursor(QTextCursor::End);
        QTest::keyClick(input, Qt::Key_Down);
        QTest::keyClick(input, Qt::Key_Down);
        QVERIFY(input->toPlainText().isEmpty()); // back to the (empty) draft
    }
};

QTEST_MAIN(TestConsole)
#include "test_console.moc"
