// SPDX-License-Identifier: GPL-3.0-or-later
// --self-test FILE --real-open: opens a file the way a person does (preferences, the saved layout and
// window geometry, the questions on the way, answered by their default button or by --answer), and
// logs the window's size and minimum at each step and whenever it changes. A window that asks for more
// than the screen fails the test (the huge-window crash: a ~4 GB backing store).
#include <QAbstractButton>
#include <QAbstractScrollArea>
#include <QApplication>
#include <QDialog>
#include <QDir>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMessageBox>
#include <QProgressDialog>
#include <QPushButton>
#include <QPointer>
#include <QScreen>
#include <QStandardPaths>
#include <QSet>
#include <QTimer>

#include <cstdio>

#include "MainWindow.h"
#include "Preferences.h"
#include "SelfTest.h"
#include "Viewport.h"

namespace kimbim {

namespace {

QString sizeText(const QSize& s)
{
    return QStringLiteral("%1x%2").arg(s.width()).arg(s.height());
}

QString describe(const QWidget* w)
{
    QString name = QString::fromLatin1(w->metaObject()->className());
    if (!w->objectName().isEmpty())
        name += QLatin1Char('/') + w->objectName();
    return name;
}

// Logs to stderr; stdout carries the one JSON result line.
void say(const QString& line)
{
    std::fprintf(stderr, "[real-open] %s\n", line.toLocal8Bit().constData());
    std::fflush(stderr);
}

// The window and every widget in it whose minimum (set or hinted) is larger than the screen.
class SizeWatch : public QObject {
public:
    SizeWatch(QWidget* window, QSize screen) : m_window(window), m_screen(screen) { window->installEventFilter(this); }

    // a maximized window's frame overhangs the screen by a few pixels
    bool tooBig(const QSize& s) const { return s.width() > m_screen.width() + 64 || s.height() > m_screen.height() + 64; }

    void log(const QString& step)
    {
        const QSize min = m_window->minimumSize(), hint = m_window->minimumSizeHint();
        say(QStringLiteral("%1: size=%2 min=%3 minHint=%4").arg(step, sizeText(m_window->size()), sizeText(min), sizeText(hint)));
        m_maxMin = m_maxMin.expandedTo(min).expandedTo(m_window->size());
        if (!tooBig(min) && !tooBig(hint) && !tooBig(m_window->size()))
            return;
        if (m_firstTooBig.isEmpty())
            m_firstTooBig = step;
        // the deepest widgets with a huge minimum are the culprits; their ancestors only inherit it
        for (QWidget* w : m_window->findChildren<QWidget*>()) {
            if (!w->isVisibleTo(m_window) || inScrollArea(w))
                continue; // a scroll area's content doesn't size the window
            const QSize wMin = w->minimumSize(), wHint = w->minimumSizeHint();
            if (!tooBig(wMin) && !tooBig(wHint))
                continue;
            bool childToo = false;
            for (QWidget* c : w->findChildren<QWidget*>(Qt::FindDirectChildrenOnly))
                childToo = childToo || (c->isVisibleTo(m_window) && (tooBig(c->minimumSize()) || tooBig(c->minimumSizeHint())));
            if (childToo)
                continue;
            QString chain;
            for (QWidget* p = w; p && p != m_window; p = p->parentWidget())
                chain = describe(p) + (chain.isEmpty() ? QString() : QStringLiteral(" > ") + chain);
            say(QStringLiteral("  huge: %1 min=%2 minHint=%3 size=%4").arg(chain, sizeText(wMin), sizeText(wHint), sizeText(w->size())));
            m_culprits.insert(chain);
        }
    }

    bool inScrollArea(const QWidget* w) const
    {
        for (const QWidget* p = w->parentWidget(); p && p != m_window; p = p->parentWidget())
            if (auto* area = qobject_cast<const QAbstractScrollArea*>(p->parentWidget()); area && area->viewport() == p)
                return true;
        return false;
    }

    QString firstTooBig() const { return m_firstTooBig; }
    QStringList culprits() const { return QStringList(m_culprits.begin(), m_culprits.end()); }
    QSize largest() const { return m_maxMin; }

protected:
    bool eventFilter(QObject* o, QEvent* e) override
    {
        if (o == m_window && (e->type() == QEvent::Resize || e->type() == QEvent::LayoutRequest))
            log(e->type() == QEvent::Resize ? QStringLiteral("  (resize)") : QStringLiteral("  (layout request)"));
        return false;
    }

private:
    QWidget* m_window;
    QSize m_screen;
    QSize m_maxMin;
    QString m_firstTooBig;
    QSet<QString> m_culprits;
};

// Answers the questions on the way: the button whose text contains one of `answers`, else the default.
class Answerer : public QObject {
public:
    explicit Answerer(QStringList answers) : m_answers(std::move(answers))
    {
        connect(&m_timer, &QTimer::timeout, this, &Answerer::poll);
        m_timer.start(150);
    }
    QStringList asked() const { return m_asked; }

private:
    void poll()
    {
        QWidget* modal = QApplication::activeModalWidget();
        if (!modal || qobject_cast<QProgressDialog*>(modal) || modal == m_last)
            return;
        auto* dialog = qobject_cast<QDialog*>(modal);
        if (!dialog)
            return;
        m_last = modal;
        QList<QAbstractButton*> buttons = dialog->findChildren<QAbstractButton*>();
        QAbstractButton* pick = nullptr;
        for (const QString& a : m_answers)
            for (QAbstractButton* b : buttons)
                if (!pick && b->isVisible() && b->text().remove(QLatin1Char('&')).contains(a, Qt::CaseInsensitive))
                    pick = b;
        if (auto* box = qobject_cast<QMessageBox*>(dialog); box && !pick)
            pick = box->defaultButton();
        QString text = modal->windowTitle();
        if (auto* box = qobject_cast<QMessageBox*>(dialog))
            text += QStringLiteral(": ") + box->text();
        m_asked << text + QStringLiteral(" -> ") + (pick ? pick->text().remove(QLatin1Char('&')) : QStringLiteral("(accept)"));
        say(QStringLiteral("asked: ") + m_asked.last());
        QTimer::singleShot(0, dialog, [dialog, pick] {
            if (pick)
                pick->click();
            else
                dialog->accept();
        });
    }

    QStringList m_answers;
    QStringList m_asked;
    QTimer m_timer;
    QPointer<QWidget> m_last;
};

void settle(int ms)
{
    QEventLoop loop;
    QTimer::singleShot(ms, &loop, &QEventLoop::quit);
    loop.exec();
}

} // namespace

int runRealOpen(const SelfTestOptions& options, const QString& path)
{
    // The test's own preferences, recovery copies and caches (Qt's test locations), never the person's.
    // Each run starts from no preferences, or from a copy of the file KIMBIM_SELFTEST_PREFS names
    // (someone's preferences.json: their saved layout and window geometry, maximized or not).
    QStandardPaths::setTestModeEnabled(true);
    const QString prefs = Preferences::defaultPath();
    QDir().mkpath(QFileInfo(prefs).absolutePath());
    QFile::remove(prefs);
    if (const QString seed = qEnvironmentVariable("KIMBIM_SELFTEST_PREFS"); !seed.isEmpty() && !QFile::copy(seed, prefs))
        say(QStringLiteral("cannot copy ") + seed);
    say(QStringLiteral("preferences: ") + prefs);
    Answerer answerer(options.answers);
    MainWindow window; // not quiet: preferences, the saved layout and geometry, the questions
    QScreen* screen = window.screen();
    const QSize avail = screen ? screen->availableGeometry().size() : QSize(1920, 1080);
    SizeWatch watch(&window, avail);
    watch.log(QStringLiteral("constructed"));
    if (options.windowSize.isValid())
        window.resize(options.windowSize);
    if (options.maximized)
        window.showMaximized();
    else
        window.show();
    watch.log(QStringLiteral("shown"));

    QEventLoop loop;
    QString loadError;
    bool finished = false;
    QObject::connect(&window, &MainWindow::loadFailed, &loop, [&](const QString& e) { loadError = e; loop.quit(); });
    QObject::connect(&window, &MainWindow::loadFinished, &loop, [&] { finished = true; loop.quit(); });
    QTimer::singleShot(20 * 60 * 1000, &loop, [&] { loadError = QStringLiteral("timeout"); loop.quit(); });
    const bool opened = window.openPath(path);
    watch.log(QStringLiteral("openPath returned ") + (opened ? QStringLiteral("true") : QStringLiteral("false")));
    if (options.minimize && opened) { // the person switches away while a large model loads
        window.setWindowState(window.windowState() | Qt::WindowMinimized);
        settle(1000);
        watch.log(QStringLiteral("minimized"));
    }
    if (opened && window.isLoading())
        loop.exec();
    watch.log(QStringLiteral("loaded"));
    if (options.minimize && opened) {
        window.setWindowState(window.windowState() & ~Qt::WindowMinimized);
        settle(1000);
        watch.log(QStringLiteral("restored"));
    }
    settle(1500); // the questions asked after loading (unmarked elements), drawings restored
    watch.log(QStringLiteral("settled"));

    const QSize largest = watch.largest();
    QJsonObject result{{"ok", opened && finished && loadError.isEmpty() && watch.firstTooBig().isEmpty()},
        {"opened", opened}, {"loaded", finished}, {"error", loadError},
        {"elements", window.viewport()->elementCount()},
        {"largest_window", sizeText(largest)}, {"screen", sizeText(avail)},
        {"too_big_at", watch.firstTooBig()}, {"huge_widgets", QJsonArray::fromStringList(watch.culprits())},
        {"asked", QJsonArray::fromStringList(answerer.asked())}};
    if (!options.screenshot.isEmpty()) {
        window.viewport()->fitAll();
        settle(500);
        result.insert(QStringLiteral("screenshot"), window.screen()->grabWindow(window.winId()).save(options.screenshot)
                ? options.screenshot : QString());
        // The window grab cannot read the OpenGL view: the view's own image beside it.
        QString view = options.screenshot;
        view.replace(QStringLiteral(".png"), QStringLiteral("-viewport.png"));
        result.insert(QStringLiteral("viewport_screenshot"), window.viewport()->dumpImage(view) ? view : QString());
    }
    window.close();
    std::printf("%s\n", QJsonDocument(result).toJson(QJsonDocument::Compact).constData());
    std::fflush(stdout);
    return result.value("ok").toBool() ? 0 : 1;
}

} // namespace kimbim
