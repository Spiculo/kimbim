// SPDX-License-Identifier: GPL-3.0-or-later
// Help > Keyboard shortcuts: the reference lists the real menus and tools, and its search filters.
#include <QAction>
#include <QApplication>
#include <QLineEdit>
#include <QMenu>
#include <QMenuBar>
#include <QSettings>
#include <QTemporaryDir>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QtTest>

#include "ShortcutsDialog.h"
#include "Translations.h"

namespace {

bool hasEntry(const QList<kimbim::ShortcutEntry>& entries, const QString& group, const QString& command,
    const QString& keys)
{
    for (const kimbim::ShortcutEntry& e : entries) {
        if (e.group == group && e.command == command && e.keys == keys)
            return true;
    }
    return false;
}

QTreeWidgetItem* findItem(QTreeWidget* table, const QString& text)
{
    for (int i = 0; i < table->topLevelItemCount(); ++i) {
        QTreeWidgetItem* group = table->topLevelItem(i);
        for (int j = 0; j < group->childCount(); ++j) {
            if (group->child(j)->text(0) == text)
                return group->child(j);
        }
    }
    return nullptr;
}

} // namespace

class TestShortcuts : public QObject {
    Q_OBJECT
private slots:
    void initTestCase()
    {
        QVERIFY(m_settings.isValid());
        QSettings::setDefaultFormat(QSettings::IniFormat);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, m_settings.path());
    }

    void collectsMenuAndToolCommands()
    {
        QWidget window;
        auto* bar = new QMenuBar(&window);
        bar->setObjectName(QStringLiteral("menuBar"));
        QMenu* file = bar->addMenu(QStringLiteral("&File"));
        QAction* save = file->addAction(QStringLiteral("&Save"));
        save->setShortcut(QKeySequence::Save);
        QMenu* model = bar->addMenu(QStringLiteral("&Model"));
        auto* wall = new QAction(QStringLiteral("&Wall"), &window);
        wall->setObjectName(QStringLiteral("actionWallTool"));
        wall->setShortcut(Qt::Key_W);
        model->addAction(wall);
        auto* plain = new QAction(QStringLiteral("No keys"), &window);
        model->addAction(plain);

        const QList<kimbim::ShortcutEntry> entries = kimbim::collectShortcuts(&window);
        QVERIFY(hasEntry(entries, QStringLiteral("File"), QStringLiteral("Save"),
            QKeySequence(QKeySequence::Save).toString(QKeySequence::NativeText)));
        QVERIFY(hasEntry(entries, QStringLiteral("Tools"), QStringLiteral("Wall"), QStringLiteral("W")));
        for (const kimbim::ShortcutEntry& e : entries)
            QVERIFY2(e.command != QStringLiteral("No keys"), "commands without a shortcut are not listed");
    }

    void searchFiltersCommandsAndKeys()
    {
        QWidget window;
        auto* bar = new QMenuBar(&window);
        bar->setObjectName(QStringLiteral("menuBar"));
        QMenu* model = bar->addMenu(QStringLiteral("&Model"));
        auto* wall = new QAction(QStringLiteral("&Wall"), &window);
        wall->setObjectName(QStringLiteral("actionWallTool"));
        wall->setShortcut(Qt::Key_W);
        model->addAction(wall);
        auto* slab = new QAction(QStringLiteral("&Slab"), &window);
        slab->setObjectName(QStringLiteral("actionSlabTool"));
        slab->setShortcut(Qt::Key_S);
        model->addAction(slab);

        kimbim::ShortcutsDialog dialog(&window);
        QVERIFY(dialog.table()->topLevelItemCount() > 0);
        QTreeWidgetItem* wallItem = findItem(dialog.table(), QStringLiteral("Wall"));
        QTreeWidgetItem* slabItem = findItem(dialog.table(), QStringLiteral("Slab"));
        QVERIFY(wallItem);
        QVERIFY(slabItem);

        dialog.search()->setText(QStringLiteral("wall"));
        QVERIFY(!wallItem->isHidden());
        QVERIFY(slabItem->isHidden());

        dialog.search()->setText(QStringLiteral("S"));
        QVERIFY(!slabItem->isHidden());

        dialog.search()->setText(QStringLiteral("nothing matches this"));
        for (int i = 0; i < dialog.table()->topLevelItemCount(); ++i)
            QVERIFY(dialog.table()->topLevelItem(i)->isHidden());
    }

    void rebindsAndResetsAShortcut()
    {
        QWidget window;
        auto* action = new QAction(QStringLiteral("Wall"), &window);
        action->setObjectName(QStringLiteral("actionWallTool"));
        action->setShortcut(Qt::Key_W);
        kimbim::applyShortcutOverrides(&window);
        kimbim::setShortcutOverride(action, QKeySequence(Qt::Key_X));
        QCOMPARE(action->shortcuts().value(0), QKeySequence(Qt::Key_X));

        // A new window applies the saved value; Reset restores the built-in sequence.
        QWidget again;
        auto* copy = new QAction(QStringLiteral("Wall"), &again);
        copy->setObjectName(QStringLiteral("actionWallTool"));
        copy->setShortcut(Qt::Key_W);
        kimbim::applyShortcutOverrides(&again);
        QCOMPARE(copy->shortcuts().value(0), QKeySequence(Qt::Key_X));
        kimbim::resetShortcutOverride(copy);
        QCOMPARE(copy->shortcuts().value(0), QKeySequence(Qt::Key_W));
    }

    void translatesToSpanish()
    {
        QVERIFY(kimbim::installTranslator(*qApp, QStringLiteral("es")));
        kimbim::ShortcutsDialog dialog(nullptr);
        QCOMPARE(dialog.windowTitle(), QStringLiteral("Atajos de teclado"));
        QCOMPARE(dialog.search()->placeholderText(), QStringLiteral("Buscar comandos o teclas"));
    }

private:
    QTemporaryDir m_settings;
};

QTEST_MAIN(TestShortcuts)
#include "test_shortcuts.moc"
