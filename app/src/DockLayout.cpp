// SPDX-License-Identifier: GPL-3.0-or-later
#include "DockLayout.h"

#include <AutoHideDockContainer.h>
#include <DockAreaWidget.h>
#include <DockContainerWidget.h>
#include <DockManager.h>
#include <DockWidget.h>
#include <DockWidgetTab.h>
#include <FloatingDockContainer.h>

#include <DockAreaTitleBar.h>
#include <DockComponentsFactory.h>

#include "Icons.h"

#include <QFile>
#include <QGuiApplication>
#include <QMainWindow>
#include <QMenu>
#include <QScreen>
#include <QSplitter>
#include <QAbstractButton>
#include <QLabel>
#include <QLayout>
#include <QToolButton>

#include <algorithm>

namespace kimbim {

namespace {

// D90: every dock area's title bar gets a Panels button (all panels, the rarely used ones included)
// where the area holds panels; and the tool palette's area hides its title bar.
class Factory : public ads::CDockComponentsFactory {
public:
    ads::CDockAreaTitleBar* createDockAreaTitleBar(ads::CDockAreaWidget* area) const override
    {
        auto* bar = ads::CDockComponentsFactory::createDockAreaTitleBar(area);
        auto* button = new QToolButton(bar);
        button->setObjectName(QStringLiteral("panelsButton"));
        button->setAutoRaise(true);
        button->setIcon(themedIcon(QStringLiteral("panel-more")));
        button->setToolTip(DockLayout::tr("Panels"));
        button->setPopupMode(QToolButton::InstantPopup);
        button->setStyleSheet(QStringLiteral("QToolButton::menu-indicator { image: none; width: 0; }"));
        button->hide();
        bar->insertWidget(bar->indexOf(bar->button(ads::TitleBarButtonTabsMenu)), button);
        QObject::connect(area, &ads::CDockAreaWidget::currentChanged, button, [area] { DockLayout::styleArea(area); });
        area->installEventFilter(watcher());
        return bar;
    }

    // Re-fits the panel tabs when an area changes width.
    class Watcher : public QObject {
    public:
        bool eventFilter(QObject* o, QEvent* e) override
        {
            if (e->type() == QEvent::Resize)
                if (auto* area = qobject_cast<ads::CDockAreaWidget*>(o))
                    DockLayout::styleArea(area);
            return false;
        }
    };
    static Watcher* watcher()
    {
        static Watcher w;
        return &w;
    }
};

} // namespace

DockLayout::DockLayout(QMainWindow* window)
    : QObject(window)
{
    ads::CDockManager::setConfigFlag(ads::CDockManager::FocusHighlighting, true);
    ads::CDockManager::setConfigFlag(ads::CDockManager::OpaqueSplitterResize, true);
    // D90: no undock button (room for the tabs): a tab still drags out, and its right-click menu detaches it.
    ads::CDockManager::setConfigFlag(ads::CDockManager::DockAreaHasUndockButton, false);
    // D90: panel tabs show only their icon (the title in the tooltip), the current one also its title
    // when it fits (styleArea); view tabs keep their titles; buttons that do nothing hide; the tabs menu
    // shows only when tabs are cut.
    ads::CDockManager::setConfigFlag(ads::CDockManager::DockAreaHideDisabledButtons, true);
    ads::CDockManager::setConfigFlag(ads::CDockManager::DockAreaDynamicTabsMenuButtonVisibility, true);
    ads::CDockManager::setConfigFlag(ads::CDockManager::DisableTabTextEliding, true); // the current tab reads in full
    ads::CDockManager::setAutoHideConfigFlags(ads::CDockManager::AutoHideFlags(ads::CDockManager::DefaultAutoHideConfig)
        | ads::CDockManager::AutoHideSideBarsIconOnly);
    ads::CDockComponentsFactory::setFactory(new Factory);
    m_manager = new ads::CDockManager(window); // becomes the window's central widget
    m_manager->setObjectName(QStringLiteral("dockManager"));
    m_manager->setProperty("kimbimDockLayout", QVariant::fromValue<QObject*>(this));
    // ADS draws inactive tab titles in palette(dark): unreadable on a dark palette (the owner's screen).
    // D90: compact title bars (12 px buttons, no extra padding): a panel's title row costs ~20 px.
    m_manager->setStyleSheet(m_manager->styleSheet() + QStringLiteral(
        "ads--CDockWidgetTab QLabel, ads--CAutoHideTab { color: palette(placeholder-text); }"
        "ads--CDockWidgetTab[activeTab=\"true\"] QLabel { color: palette(window-text); }"
        "ads--CDockWidgetTab { padding: 0px 1px; }"
        "ads--CDockWidgetTab QLabel { padding: 0px; margin: 0px; }"
        "ads--CTitleBarButton, #panelsButton { padding: 0px; margin: 0px; }"
        "#tabsMenuButton, #detachGroupButton, #dockAreaCloseButton, #dockAreaAutoHideButton, #dockAreaMinimizeButton"
        " { qproperty-iconSize: 12px; }"
        "#panelsButton { qproperty-iconSize: 14px; }"
        "#tabCloseButton { margin-top: 0px; qproperty-iconSize: 12px; }"));
    connect(m_manager, &ads::CDockManager::stateRestored, this, [this] {
        for (ads::CDockAreaWidget* area : m_manager->openedDockAreas())
            styleArea(area);
    });
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
    // D90: an icon tab (its title shows only while it is the current one, and on hover).
    if (QFile::exists(QStringLiteral(":/icons/panel-%1.svg").arg(key)))
        dock->setIcon(themedIcon(QStringLiteral("panel-") + key));
    dock->setTabToolTip(title);
    tightenTab(dock);
    m_panelKeys << key;
    if (!m_panels) {
        // the panel area of a restored layout: wherever the other panels are
        for (const QString& other : std::as_const(m_panelKeys))
            if (ads::CDockWidget* d = m_manager->findDockWidget(other); d && d != dock && d->dockAreaWidget()
                && !d->isClosed() && !d->isAutoHide()) {
                m_panels = d->dockAreaWidget();
                break;
            }
    }
    if (m_panels)
        m_manager->addDockWidgetTabToArea(dock, m_panels);
    else
        m_panels = m_manager->addDockWidget(ads::RightDockWidgetArea, dock);
    styleArea(dock->dockAreaWidget());
    return dock;
}

ads::CDockWidget* DockLayout::addLeft(const QString& key, const QString& title, QWidget* widget)
{
    ads::CDockWidget* dock = makeDock(key, title, widget);
    dock->setFeature(ads::CDockWidget::CustomCloseHandling, false);
    dock->setFeature(ads::CDockWidget::DockWidgetClosable, false);
    if (QFile::exists(QStringLiteral(":/icons/panel-%1.svg").arg(key)))
        dock->setIcon(themedIcon(QStringLiteral("panel-") + key));
    dock->setTabToolTip(title);
    m_left = m_manager->addDockWidget(ads::LeftDockWidgetArea, dock);
    styleArea(m_left);
    return dock;
}

void DockLayout::tightenTab(ads::CDockWidget* dock)
{
    // ADS pads a tab by a quarter of the font height on each side of the icon and around the close
    // button (~46 px for an icon alone); icon tabs need ~26 px.
    QLayout* l = dock->tabWidget() ? dock->tabWidget()->layout() : nullptr;
    if (!l)
        return;
    l->setContentsMargins(3, 0, 0, 0);
    for (int i = 0; i < l->count(); ++i)
        if (QSpacerItem* s = l->itemAt(i)->spacerItem())
            s->changeSize(2, 0, QSizePolicy::Fixed, QSizePolicy::Minimum);
    l->invalidate();
}

void DockLayout::setPanelsMenu(QMenu* menu)
{
    m_panelsMenu = menu;
    for (ads::CDockAreaWidget* area : m_manager->openedDockAreas())
        styleArea(area);
}

void DockLayout::styleArea(ads::CDockAreaWidget* area)
{
    if (!area || !area->dockManager())
        return;
    auto* self = qobject_cast<DockLayout*>(area->dockManager()->property("kimbimDockLayout").value<QObject*>());
    if (!self)
        return;
    bool panels = false, tools = false;
    for (ads::CDockWidget* d : area->dockWidgets()) {
        panels = panels || self->m_panelKeys.contains(d->objectName());
        tools = tools || d->objectName() == QLatin1String("tools");
    }
    if (auto* b = area->titleBar() ? area->titleBar()->findChild<QToolButton*>(QStringLiteral("panelsButton")) : nullptr) {
        b->setMenu(self->m_panelsMenu);
        b->setVisible(panels && self->m_panelsMenu);
    }
    // Panel tabs: icons; the current one's title too when every tab still fits beside it.
    if (panels && area->titleBar()) {
        int used = 8;
        QLabel* currentTitle = nullptr;
        for (ads::CDockWidget* d : area->dockWidgets()) {
            QLabel* label = d->tabWidget()->findChild<QLabel*>(QStringLiteral("dockWidgetTabLabel"));
            const bool panel = self->m_panelKeys.contains(d->objectName());
            if (label && panel) {
                label->setVisible(false);
                if (d == area->currentDockWidget())
                    currentTitle = label;
            }
            if (!d->isClosed())
                used += d->tabWidget()->sizeHint().width();
        }
        for (QAbstractButton* b : area->titleBar()->findChildren<QAbstractButton*>(Qt::FindDirectChildrenOnly))
            if (b->isVisibleTo(area->titleBar()))
                used += b->sizeHint().width();
        if (currentTitle)
            currentTitle->setVisible(used + currentTitle->fontMetrics().horizontalAdvance(currentTitle->text()) + 4
                <= area->width());
    }
    // The tool palette alone in its area needs no title row: it floats and auto-hides from its own menu.
    const bool hide = tools && area->dockWidgetsCount() == 1;
    if (area->dockAreaFlags().testFlag(ads::CDockAreaWidget::HideSingleWidgetTitleBar) != hide)
        area->setDockAreaFlag(ads::CDockAreaWidget::HideSingleWidgetTitleBar, hide);
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

QList<int> DockLayout::splitterSizes() const
{
    return m_center ? m_manager->splitterSizes(m_center) : QList<int>{};
}

void DockLayout::setPanelPinned(const QString& key, bool pinned)
{
    auto* dock = m_manager->findDockWidget(key);
    if (!dock || key == QLatin1String("tools") || key.startsWith(QLatin1String("plan:")))
        return;
    if (pinned)
        m_pinned.insert(key);
    else
        m_pinned.remove(key);
    dock->setFeature(ads::CDockWidget::DockWidgetClosable, !pinned);
    if (QAction* toggle = dock->toggleViewAction()) {
        toggle->setEnabled(!pinned);
        if (pinned && !dock->isVisible())
            dock->toggleView(true); // a permanent tab is always there
    }
}

void DockLayout::setSideWidths(int left, int right)
{
    if (!m_center)
        return;
    emit sideWidthsChanged(left, right);
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
    // D90: when the window is resized the tool palette keeps its width (Archicad's palettes; a small
    // window doesn't squeeze it to one column), the panels too (the views take the change; a small screen can auto-hide the panels).
    if (auto* splitter = qobject_cast<QSplitter*>(m_center->parentWidget()))
        for (int i = 0; i < splitter->count(); ++i) {
            QWidget* w = splitter->widget(i);
            splitter->setStretchFactor(i, w == m_center.data() ? 1 : 0);
        }
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
    if (!m_default.isEmpty())
        m_manager->restoreState(m_default);
    return false;
}

} // namespace kimbim
