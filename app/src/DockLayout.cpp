// SPDX-License-Identifier: GPL-3.0-or-later
#include "DockLayout.h"

#include <AutoHideDockContainer.h>
#include <DockAreaWidget.h>
#include <DockContainerWidget.h>
#include <DockManager.h>
#include <DockWidget.h>
#include <FloatingDockContainer.h>

#include <QGuiApplication>
#include <QMainWindow>
#include <QScreen>
#include <QFile>
#include <QStandardPaths>

#include <algorithm>

namespace kimcad {

namespace {
// Temporary diagnostic (removed once the huge-window crash is fixed).
void diag(const QString& message)
{
    QFile f(QStandardPaths::writableLocation(QStandardPaths::TempLocation) + QStringLiteral("/kimcad-diag.txt"));
    if (f.open(QIODevice::WriteOnly | QIODevice::Append | QIODevice::Text))
        f.write((message + QLatin1Char('\n')).toUtf8());
}
} // namespace

DockLayout::DockLayout(QMainWindow* window)
    : QObject(window)
{
    ads::CDockManager::setConfigFlag(ads::CDockManager::FocusHighlighting, true);
    ads::CDockManager::setConfigFlag(ads::CDockManager::OpaqueSplitterResize, true);
    ads::CDockManager::setConfigFlag(ads::CDockManager::DockAreaHasUndockButton, true);
    ads::CDockManager::setAutoHideConfigFlags(ads::CDockManager::DefaultAutoHideConfig);
    m_manager = new ads::CDockManager(window); // becomes the window's central widget
    m_manager->setObjectName(QStringLiteral("dockManager"));
    // ADS draws inactive tab titles in palette(dark): unreadable on a dark palette (the owner's screen).
    m_manager->setStyleSheet(m_manager->styleSheet() + QStringLiteral(
        "ads--CDockWidgetTab QLabel, ads--CAutoHideTab { color: palette(placeholder-text); }"
        "ads--CDockWidgetTab[activeTab=\"true\"] QLabel { color: palette(window-text); }"));
    connect(m_manager, &ads::CDockManager::focusedDockWidgetChanged, this,
        [this](ads::CDockWidget*, ads::CDockWidget* now) {
            if (now && m_views.contains(now->objectName()) && m_current != now->objectName()) {
                m_current = now->objectName();
                emit currentChanged(m_current);
            }
        });
}

ads::CDockWidget* DockLayout::makeDock(const QString& key, const QString& title, QWidget* widget)
{
    auto* dock = new ads::CDockWidget(title);
    dock->setObjectName(key); // ADS saves and restores the layout by object name
    dock->setWidget(widget);
    dock->setFeature(ads::CDockWidget::CustomCloseHandling, true);
    connect(dock, &ads::CDockWidget::closeRequested, this, [this, key] { emit closeRequested(key); });
    return dock;
}

ads::CDockWidget* DockLayout::addView(const QString& key, const QString& title, QWidget* widget, bool closable,
    Placement placement)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::DockWidgetClosable, closable);
    if (!m_center) {
        m_center = m_manager->addDockWidget(ads::CenterDockWidgetArea, dock);
    } else if (placement == Placement::Floating) {
        // D72: a free window centred over the main window at 70 % of its size.
        ads::CFloatingDockContainer* f = m_manager->addDockWidgetFloating(dock);
        const QRect main = m_manager->window()->geometry();
        const QSize size(main.width() * 7 / 10, main.height() * 7 / 10);
        f->resize(size);
        f->move(main.center() - QPoint(size.width() / 2, size.height() / 2));
    } else {
        // Right after the current tab, when it is docked in the main window; else at the end of the center.
        ads::CDockWidget* current = m_current.isEmpty() ? nullptr : m_manager->findDockWidget(m_current);
        ads::CDockAreaWidget* area = current && current->dockAreaWidget()
                && !current->dockContainer()->isFloating() ? current->dockAreaWidget() : m_center.data();
        int index = -1;
        for (int i = 0; current && current->dockAreaWidget() == area && i < area->dockWidgetsCount(); ++i)
            if (area->dockWidget(i) == current)
                index = i + 1;
        m_manager->addDockWidgetTabToArea(dock, area, index);
    }
    m_views << key;
    if (m_current.isEmpty())
        m_current = key;
    return dock;
}

QWidget* DockLayout::view(const QString& key) const
{
    ads::CDockWidget* dock = m_views.contains(key) ? m_manager->findDockWidget(key) : nullptr;
    return dock ? dock->widget() : nullptr;
}

QString DockLayout::keyOf(const QWidget* widget) const
{
    for (const QString& key : m_views)
        if (view(key) == widget)
            return key;
    return {};
}

QStringList DockLayout::viewKeys() const
{
    return m_views;
}

void DockLayout::setTitle(const QString& key, const QString& title)
{
    if (ads::CDockWidget* dock = m_manager->findDockWidget(key))
        dock->setWindowTitle(title);
}

void DockLayout::removeView(const QString& key)
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    if (!dock)
        return;
    m_views.removeAll(key);
    m_manager->removeDockWidget(dock);
    // Later: a close request arrives from inside the dock's own code (its close button).
    dock->deleteLater(); // and its widget
    if (m_current == key) {
        m_current.clear();
        if (!m_views.isEmpty())
            raise(m_views.first());
    }
}

void DockLayout::raise(const QString& key)
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    if (!dock)
        return;
    dock->toggleView(true);
    dock->raise();
    m_manager->setDockWidgetFocused(dock);
    if (m_current != key) {
        m_current = key;
        emit currentChanged(key);
    }
}

QString DockLayout::current() const
{
    return m_current;
}

ads::CDockWidget* DockLayout::addPanel(const QString& key, const QString& title, QWidget* widget)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::CustomCloseHandling, false); // panels just hide
    if (m_panels)
        m_manager->addDockWidgetTabToArea(dock, m_panels);
    else
        m_panels = m_manager->addDockWidget(ads::RightDockWidgetArea, dock);
    return dock;
}

ads::CDockWidget* DockLayout::addLeft(const QString& key, const QString& title, QWidget* widget)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::CustomCloseHandling, false);
    dock->setFeature(ads::CDockWidget::DockWidgetClosable, false);
    m_left = m_manager->addDockWidget(ads::LeftDockWidgetArea, dock);
    return dock;
}

void DockLayout::raisePanel(const QString& key)
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    if (!dock)
        return;
    dock->toggleView(true);
    if (dock->isAutoHide())
        dock->autoHideDockContainer()->collapseView(false); // slides out
    else if (dock->isFloating())
        dock->dockContainer()->window()->raise();
    dock->raise();
}

bool DockLayout::isPanelShown(const QString& key) const
{
    ads::CDockWidget* dock = m_manager->findDockWidget(key);
    return dock && !dock->isClosed() && dock->isCurrentTab();
}

void DockLayout::setSideWidths(int left, int right)
{
    if (!m_center)
        return;
    // The root splitter holds [left column,] the center [, right column], in that order.
    const QList<int> now = m_manager->splitterSizes(m_center);
    int total = 0;
    for (int s : now)
        total += s;
    if (total <= 0) // not shown yet: the sizes act as proportions of a nominal 1600 px window
        total = std::max(1600, left + right + 400);
    QList<int> sizes;
    if (m_left)
        sizes << left;
    sizes << std::max(total - (m_left ? left : 0) - (m_panels ? right : 0), 200);
    if (m_panels)
        sizes << right;
    if (sizes.size() == now.size())
        m_manager->setSplitterSizes(m_center, sizes);
}

QByteArray DockLayout::saveLayout() const
{
    return m_manager->saveState();
}

void DockLayout::captureDefault()
{
    m_default = m_manager->saveState();
}

bool DockLayout::onSomeScreen() const
{
    for (ads::CFloatingDockContainer* f : m_manager->floatingWidgets()) {
        bool seen = false;
        for (QScreen* s : QGuiApplication::screens())
            seen = seen || s->availableGeometry().intersects(f->geometry());
        if (!seen)
            return false;
    }
    return true;
}

bool DockLayout::layoutIsSane() const
{
    // A corrupt layout can ask for a window of tens of thousands of pixels: Qt then fails to allocate
    // the ~4 GB backing store (createDIB) and the app dies. Anything past a few screens is not real.
    int screenW = 0, screenH = 0;
    for (QScreen* s : QGuiApplication::screens()) {
        screenW = std::max(screenW, s->availableGeometry().width());
        screenH = std::max(screenH, s->availableGeometry().height());
    }
    const int capW = std::max(screenW, 1024) * 4, capH = std::max(screenH, 768) * 4;
    for (ads::CFloatingDockContainer* f : m_manager->floatingWidgets()) {
        const QRect g = f->geometry();
        if (g.width() > capW || g.height() > capH || g.width() <= 0 || g.height() <= 0)
            return false;
    }
    const QSize hint = m_manager->minimumSizeHint();
    if (hint.width() > capW || hint.height() > capH)
        return false;
    if (QWidget* w = m_manager->window()) {
        const QSize windowHint = w->minimumSizeHint();
        if (windowHint.width() > capW || windowHint.height() > capH)
            return false;
    }
    return true;
}

bool DockLayout::restoreLayout(const QByteArray& state)
{
    // ADS skips docks it no longer has (a drawing deleted since); a garbled state, a huge size or a
    // floating window left on an unplugged monitor falls back to the default layout.
    if (state.isEmpty()) {
        if (!m_default.isEmpty())
            m_manager->restoreState(m_default);
        return false;
    }
    const bool restored = m_manager->restoreState(state);
    if (restored && onSomeScreen() && layoutIsSane())
        return true;
    QString sizes;
    for (int s : m_manager->splitterSizes(m_center))
        sizes += QString::number(s) + QLatin1Char(' ');
    diag(QStringLiteral("restoreLayout REJECTED: restored=%1 sane=%2 onScreen=%3 splits=[%4] floats=%5")
        .arg(restored).arg(layoutIsSane()).arg(onSomeScreen()).arg(sizes.trimmed())
        .arg(m_manager->floatingWidgets().size()));
    if (!m_default.isEmpty())
        m_manager->restoreState(m_default);
    return false;
}

} // namespace kimcad
