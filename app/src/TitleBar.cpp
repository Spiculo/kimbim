// SPDX-License-Identifier: GPL-3.0-or-later
#include "TitleBar.h"

#include <QApplication>
#include <QEvent>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QMenu>
#include <QMenuBar>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QToolButton>
#include <QWindow>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <windowsx.h>
#include <dwmapi.h>
#endif

namespace kimcad {

namespace {
constexpr int kHeight = 34;
constexpr int kMinTitle = 80; // the title keeps at least this much before the menus collapse

bool darkPalette(const QPalette& p)
{
    return p.color(QPalette::Window).lightness() < 128;
}

QColor barColor(const QPalette& p)
{
    const QColor w = p.color(QPalette::Window);
    return darkPalette(p) ? w.darker(125) : w.darker(106);
}

// A small icon drawn with the palette's text colour (crisp at any scale).
template <typename Paint>
QIcon drawnIcon(int size, Paint paint)
{
    QIcon icon;
    for (const qreal dpr : {1.0, 1.5, 2.0}) {
        QPixmap pm(QSize(size, size) * dpr);
        pm.setDevicePixelRatio(dpr);
        pm.fill(Qt::transparent);
        QPainter p(&pm);
        p.setRenderHint(QPainter::Antialiasing);
        paint(p);
        icon.addPixmap(pm);
    }
    return icon;
}

QPixmap appIcon(const QPalette& pal, qreal dpr)
{
    QPixmap pm(QSize(18, 18) * dpr);
    pm.setDevicePixelRatio(dpr);
    pm.fill(Qt::transparent);
    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing);
    QPainterPath body;
    body.addRoundedRect(QRectF(1, 1, 16, 16), 3.5, 3.5);
    p.fillPath(body, pal.color(QPalette::Highlight));
    QFont f = QApplication::font();
    f.setBold(true);
    f.setPixelSize(12);
    p.setFont(f);
    p.setPen(pal.color(QPalette::HighlightedText));
    p.drawText(QRectF(1, 1, 16, 16), Qt::AlignCenter, QStringLiteral("K"));
    return pm;
}

#ifdef Q_OS_WIN
// The native frame comes back under the frameless Qt window: resize borders, Aero snap, the
// minimize/maximize animations, the shadow and (Windows 11) rounded corners.
void applyNativeFrame(QWidget* window)
{
    if (window->property("kimcadNativeFrame").toULongLong() == quint64(window->winId()))
        return;
    const HWND hwnd = reinterpret_cast<HWND>(window->winId());
    const LONG_PTR style = GetWindowLongPtrW(hwnd, GWL_STYLE);
    SetWindowLongPtrW(hwnd, GWL_STYLE,
        (style & ~LONG_PTR(WS_POPUP)) | WS_THICKFRAME | WS_CAPTION | WS_SYSMENU | WS_MAXIMIZEBOX | WS_MINIMIZEBOX);
    const MARGINS shadow{1, 1, 1, 1};
    DwmExtendFrameIntoClientArea(hwnd, &shadow);
    SetWindowPos(hwnd, nullptr, 0, 0, 0, 0,
        SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_NOACTIVATE);
    window->setProperty("kimcadNativeFrame", quint64(window->winId()));
}

// A maximized window may reach past its monitor's work area by the (invisible) frame: keep the
// content inside it.
void fitMaximized(QWidget* window)
{
    QMargins m;
    if (window->isMaximized() && window->internalWinId()) {
        const HWND hwnd = reinterpret_cast<HWND>(window->winId());
        RECT wr;
        MONITORINFO mi{};
        mi.cbSize = sizeof(mi);
        if (GetWindowRect(hwnd, &wr) && GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &mi)) {
            const qreal dpr = window->devicePixelRatioF();
            auto px = [dpr](long v) { return qMax(0, qRound(v / dpr)); };
            m = QMargins(px(mi.rcWork.left - wr.left), px(mi.rcWork.top - wr.top), px(wr.right - mi.rcWork.right),
                px(wr.bottom - mi.rcWork.bottom));
        }
    }
    if (window->contentsMargins() != m)
        window->setContentsMargins(m);
}
#endif

// Watches the main window: the native frame (Windows), and resizing from the edges elsewhere.
class FrameFilter : public QObject {
public:
    explicit FrameFilter(QWidget* window) : QObject(window), m_window(window) {}

    bool eventFilter(QObject* watched, QEvent* event) override
    {
        if (watched == m_window) {
            switch (event->type()) {
#ifdef Q_OS_WIN
            case QEvent::WinIdChange:
            case QEvent::Show:
                if (m_window->internalWinId())
                    applyNativeFrame(m_window);
                break;
            case QEvent::WindowStateChange:
            case QEvent::Resize:
                fitMaximized(m_window);
                break;
#else
            case QEvent::Show:
                if (QWindow* w = m_window->windowHandle(); w && !m_handle) {
                    m_handle = w;
                    w->installEventFilter(this);
                }
                break;
#endif
            default:
                break;
            }
            return false;
        }
#ifndef Q_OS_WIN
        if (watched == m_handle)
            return edgeEvent(event);
#endif
        return false;
    }

private:
#ifndef Q_OS_WIN
    Qt::Edges edgesAt(const QPointF& p) const
    {
        if (m_window->isMaximized() || m_window->isFullScreen())
            return {};
        const int b = 5;
        Qt::Edges e;
        if (p.x() < b)
            e |= Qt::LeftEdge;
        if (p.x() >= m_window->width() - b)
            e |= Qt::RightEdge;
        if (p.y() < b)
            e |= Qt::TopEdge;
        if (p.y() >= m_window->height() - b)
            e |= Qt::BottomEdge;
        return e;
    }

    bool edgeEvent(QEvent* event)
    {
        if (event->type() != QEvent::MouseMove && event->type() != QEvent::MouseButtonPress)
            return false;
        auto* me = static_cast<QMouseEvent*>(event);
        const Qt::Edges edges = edgesAt(me->position());
        if (event->type() == QEvent::MouseMove && me->buttons() == Qt::NoButton) {
            if (edges != m_edges) {
                m_edges = edges;
                if (!edges)
                    m_handle->unsetCursor();
                else if (edges == (Qt::LeftEdge | Qt::TopEdge) || edges == (Qt::RightEdge | Qt::BottomEdge))
                    m_handle->setCursor(Qt::SizeFDiagCursor);
                else if (edges == (Qt::RightEdge | Qt::TopEdge) || edges == (Qt::LeftEdge | Qt::BottomEdge))
                    m_handle->setCursor(Qt::SizeBDiagCursor);
                else if (edges & (Qt::LeftEdge | Qt::RightEdge))
                    m_handle->setCursor(Qt::SizeHorCursor);
                else
                    m_handle->setCursor(Qt::SizeVerCursor);
            }
            return false;
        }
        if (event->type() == QEvent::MouseButtonPress && me->button() == Qt::LeftButton && edges)
            return m_handle->startSystemResize(edges);
        return false;
    }

    QWindow* m_handle = nullptr;
    Qt::Edges m_edges;
#endif
    QWidget* m_window;
};
} // namespace

CaptionButton::CaptionButton(Kind kind, QWidget* parent)
    : QAbstractButton(parent)
    , m_kind(kind)
{
    setFocusPolicy(Qt::NoFocus);
    setAttribute(Qt::WA_Hover);
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
}

void CaptionButton::setRestore(bool restore)
{
    m_restore = restore;
    update();
}

void CaptionButton::paintEvent(QPaintEvent*)
{
    QPainter p(this);
    const bool hot = underMouse() || isDown();
    QColor glyph = palette().color(window()->isActiveWindow() ? QPalette::Active : QPalette::Inactive, QPalette::WindowText);
    if (!window()->isActiveWindow())
        glyph.setAlphaF(0.55f);
    if (hot) {
        if (m_kind == Kind::Close) {
            p.fillRect(rect(), isDown() ? QColor(0x94, 0x1f, 0x14) : QColor(0xc4, 0x2b, 0x1c));
            glyph = Qt::white;
        } else {
            QColor bg = palette().color(QPalette::WindowText);
            bg.setAlphaF(isDown() ? 0.22f : 0.12f);
            p.fillRect(rect(), bg);
        }
    }
    const QRectF box(width() / 2.0 - 5, height() / 2.0 - 5, 10, 10);
    QPen pen(glyph, 1.0);
    pen.setCosmetic(true);
    p.setPen(pen);
    switch (m_kind) {
    case Kind::Minimize:
        p.drawLine(QPointF(box.left(), box.center().y() + 0.5), QPointF(box.right(), box.center().y() + 0.5));
        break;
    case Kind::Maximize:
        if (m_restore) {
            p.drawRect(box.adjusted(0.5, 2.5, -2.5, -0.5));
            p.drawPolyline(QPolygonF({QPointF(box.left() + 2.5, box.top() + 2.5), QPointF(box.left() + 2.5, box.top() + 0.5),
                QPointF(box.right() - 0.5, box.top() + 0.5), QPointF(box.right() - 0.5, box.bottom() - 2.5),
                QPointF(box.right() - 2.5, box.bottom() - 2.5)}));
        } else {
            p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5));
        }
        break;
    case Kind::Close:
        p.setRenderHint(QPainter::Antialiasing);
        p.drawLine(box.topLeft(), box.bottomRight());
        p.drawLine(box.topRight(), box.bottomLeft());
        break;
    }
}

TitleBar::TitleBar(QWidget* window)
    : QWidget(window)
    , m_window(window)
{
    setObjectName(QStringLiteral("titleBar"));
    setFixedHeight(kHeight);
    m_row = new QHBoxLayout(this);
    m_row->setContentsMargins(0, 0, 0, 0);
    m_row->setSpacing(2);

    m_icon = new QLabel(this);
    m_icon->setFixedSize(32, kHeight);
    m_icon->setAlignment(Qt::AlignCenter);
    m_icon->setPixmap(appIcon(palette(), devicePixelRatioF()));
    m_row->addWidget(m_icon);

    m_menuButton = new QToolButton(this);
    m_menuButton->setObjectName(QStringLiteral("menuButton"));
    m_menuButton->setAutoRaise(true);
    m_menuButton->setToolTip(tr("Menu"));
    m_menuButton->setPopupMode(QToolButton::InstantPopup);
    m_menuButton->setStyleSheet(QStringLiteral("QToolButton::menu-indicator { image: none; width: 0; }"));
    const QColor text = palette().color(QPalette::WindowText);
    m_menuButton->setIcon(drawnIcon(16, [text](QPainter& p) {
        p.setPen(QPen(text, 1.4));
        for (const qreal y : {4.5, 8.0, 11.5})
            p.drawLine(QPointF(2.5, y), QPointF(13.5, y));
    }));
    m_collapsed = new QMenu(m_menuButton);
    m_menuButton->setMenu(m_collapsed);
    connect(m_collapsed, &QMenu::aboutToShow, this, &TitleBar::fillMenuButton);
    m_menuButton->hide();
    m_row->addWidget(m_menuButton);

    m_menuBar = new QMenuBar(this);
    m_menuBar->setObjectName(QStringLiteral("menuBar"));
    m_menuBar->setNativeMenuBar(false);
    m_menuBar->setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    m_menuBar->setAutoFillBackground(false);
    m_menuBar->setStyleSheet(QStringLiteral("QMenuBar { background: transparent; }"));
    m_row->addWidget(m_menuBar, 0, Qt::AlignVCenter);

    m_controls = new QWidget(this);
    m_controls->setObjectName(QStringLiteral("titleBarControls"));
    m_controlsRow = new QHBoxLayout(m_controls);
    m_controlsRow->setContentsMargins(8, 0, 0, 0);
    m_controlsRow->setSpacing(4);
    m_row->addWidget(m_controls);

    m_title = new QLabel(this);
    m_title->setObjectName(QStringLiteral("documentTitle"));
    m_title->setAlignment(Qt::AlignCenter);
    m_title->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    m_title->setMinimumWidth(24);
    m_title->installEventFilter(this);
    m_row->addWidget(m_title, 1);

    m_min = new CaptionButton(CaptionButton::Kind::Minimize, this);
    m_min->setObjectName(QStringLiteral("minimizeButton"));
    m_min->setToolTip(tr("Minimize"));
    m_max = new CaptionButton(CaptionButton::Kind::Maximize, this);
    m_max->setObjectName(QStringLiteral("maximizeButton"));
    m_max->setToolTip(tr("Maximize"));
    m_close = new CaptionButton(CaptionButton::Kind::Close, this);
    m_close->setObjectName(QStringLiteral("closeButton"));
    m_close->setToolTip(tr("Close"));
    connect(m_min, &QAbstractButton::clicked, m_window, &QWidget::showMinimized);
    connect(m_max, &QAbstractButton::clicked, this, &TitleBar::toggleMaximized);
    connect(m_close, &QAbstractButton::clicked, m_window, &QWidget::close);
    m_row->addSpacing(4);
    for (CaptionButton* b : {m_min, m_max, m_close})
        m_row->addWidget(b);
#ifdef Q_OS_MACOS
    for (CaptionButton* b : {m_min, m_max, m_close})
        b->hide(); // the native frame stays on macOS
#endif
    m_window->installEventFilter(this);
    m_menuBar->installEventFilter(this);
    updateTitle();
}

void TitleBar::addControl(QWidget* control)
{
    control->setParent(m_controls);
    m_controlsRow->addWidget(control, 0, Qt::AlignVCenter);
}

void TitleBar::addControlSeparator()
{
    auto* line = new QFrame(m_controls);
    line->setFrameShape(QFrame::VLine);
    line->setFrameShadow(QFrame::Plain);
    line->setFixedHeight(kHeight / 2);
    QPalette p = line->palette();
    p.setColor(QPalette::WindowText, palette().color(QPalette::Mid));
    line->setPalette(p);
    m_controlsRow->addWidget(line, 0, Qt::AlignVCenter);
}

void TitleBar::setTrailing(QWidget* widget)
{
    m_trailing = widget;
    widget->setParent(this);
    m_row->insertWidget(m_row->indexOf(m_title) + 1, widget, 0, Qt::AlignVCenter);
}

QString TitleBar::title() const
{
    return m_title->property("fullTitle").toString();
}

bool TitleBar::menusCollapsed() const
{
    return m_menuBar->isHidden();
}

bool TitleBar::isDragArea(const QPoint& pos) const
{
    const QWidget* c = childAt(pos);
    if (!c || c == m_title || c == m_icon || c == m_controls)
        return true;
    // labels and plain containers between the controls
    return qobject_cast<const QLabel*>(c) || c->metaObject() == &QFrame::staticMetaObject
        || c->metaObject() == &QWidget::staticMetaObject;
}

void TitleBar::install(QWidget* window)
{
#ifndef Q_OS_MACOS
    window->setWindowFlags(window->windowFlags() | Qt::FramelessWindowHint | Qt::WindowMinMaxButtonsHint);
    window->installEventFilter(new FrameFilter(window));
#else
    Q_UNUSED(window)
#endif
}

bool TitleBar::nativeEvent(QWidget* window, TitleBar* bar, const QByteArray& type, void* message, qintptr* result)
{
#ifdef Q_OS_WIN
    if (type != "windows_generic_MSG")
        return false;
    const MSG* msg = static_cast<const MSG*>(message);
    switch (msg->message) {
    case WM_NCCALCSIZE:
        if (msg->wParam) { // the whole window is client area: no native title bar or borders drawn
            *result = 0;
            return true;
        }
        return false;
    case WM_NCHITTEST: {
        if (window->isFullScreen()) {
            *result = HTCLIENT;
            return true;
        }
        RECT wr;
        GetWindowRect(msg->hwnd, &wr);
        const POINT p{GET_X_LPARAM(msg->lParam), GET_Y_LPARAM(msg->lParam)};
        const qreal dpr = window->devicePixelRatioF();
        const int b = window->isMaximized() ? 0 : qRound(5 * dpr);
        const bool left = p.x < wr.left + b, right = p.x >= wr.right - b;
        const bool top = p.y < wr.top + b, bottom = p.y >= wr.bottom - b;
        if (top && left)
            *result = HTTOPLEFT;
        else if (top && right)
            *result = HTTOPRIGHT;
        else if (bottom && left)
            *result = HTBOTTOMLEFT;
        else if (bottom && right)
            *result = HTBOTTOMRIGHT;
        else if (left)
            *result = HTLEFT;
        else if (right)
            *result = HTRIGHT;
        else if (top)
            *result = HTTOP;
        else if (bottom)
            *result = HTBOTTOM;
        else {
            const QPoint local(qFloor((p.x - wr.left) / dpr), qFloor((p.y - wr.top) / dpr));
            const QPoint inBar = bar ? bar->mapFrom(window, local) : QPoint(-1, -1);
            *result = bar && bar->isVisible() && bar->rect().contains(inBar) && bar->isDragArea(inBar) ? HTCAPTION : HTCLIENT;
        }
        return true;
    }
    default:
        return false;
    }
#else
    Q_UNUSED(window) Q_UNUSED(bar) Q_UNUSED(type) Q_UNUSED(message) Q_UNUSED(result)
    return false;
#endif
}

bool TitleBar::eventFilter(QObject* watched, QEvent* event)
{
    if (watched == m_window) {
        switch (event->type()) {
        case QEvent::WindowTitleChange:
        case QEvent::ModifiedChange:
            updateTitle();
            break;
        case QEvent::WindowStateChange:
            m_max->setRestore(m_window->isMaximized());
            m_max->setToolTip(m_window->isMaximized() ? tr("Restore") : tr("Maximize"));
            break;
        case QEvent::ActivationChange:
            update();
            for (CaptionButton* b : {m_min, m_max, m_close})
                b->update();
            break;
        default:
            break;
        }
    } else if (watched == m_title && event->type() == QEvent::Resize) {
        updateTitle();
    } else if (watched == m_menuBar && (event->type() == QEvent::ActionAdded || event->type() == QEvent::ActionRemoved
                                           || event->type() == QEvent::ActionChanged)) {
        updateCollapse();
    }
    return QWidget::eventFilter(watched, event);
}

void TitleBar::updateTitle()
{
    QString t = m_window->windowTitle();
    const QString prefix = QStringLiteral("KIMCAD — "); // as MainWindow titles the window
    if (t.startsWith(prefix))
        t = t.mid(prefix.size()); // the icon already says KIMCAD
    t.replace(QStringLiteral("[*]"), m_window->isWindowModified() ? QStringLiteral(" •") : QString());
    m_title->setProperty("fullTitle", t);
    m_title->setToolTip(t);
    m_title->setText(m_title->fontMetrics().elidedText(t, Qt::ElideMiddle, qMax(0, m_title->width() - 8)));
}

void TitleBar::updateCollapse()
{
    int fixed = m_icon->width() + m_controls->sizeHint().width() + kMinTitle + 3 * 46 + 4 + 8 * m_row->spacing();
    if (m_trailing)
        fixed += m_trailing->sizeHint().width();
    const bool collapse = fixed + m_menuBar->sizeHint().width() > width();
    if (collapse == m_menuBar->isHidden())
        return;
    m_menuBar->setVisible(!collapse);
    m_menuButton->setVisible(collapse);
}

void TitleBar::fillMenuButton()
{
    m_collapsed->clear(); // the menus' own actions: they belong to their menus, not to this one
    for (QAction* a : m_menuBar->actions())
        if (a->isVisible())
            m_collapsed->addAction(a);
}

void TitleBar::toggleMaximized()
{
    if (m_window->isMaximized())
        m_window->showNormal();
    else
        m_window->showMaximized();
}

void TitleBar::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    updateCollapse();
}

void TitleBar::mousePressEvent(QMouseEvent* event)
{
    // On Windows the native frame moves the window (the hit test says "caption"); elsewhere Qt does.
    if (event->button() == Qt::LeftButton && isDragArea(event->position().toPoint()))
        if (QWindow* w = m_window->windowHandle(); w && w->startSystemMove())
            return;
    QWidget::mousePressEvent(event);
}

void TitleBar::mouseDoubleClickEvent(QMouseEvent* event)
{
    if (event->button() == Qt::LeftButton && isDragArea(event->position().toPoint()))
        toggleMaximized();
    else
        QWidget::mouseDoubleClickEvent(event);
}

void TitleBar::paintEvent(QPaintEvent*)
{
    QPainter p(this);
    p.fillRect(rect(), barColor(palette()));
    QColor line = palette().color(QPalette::Mid);
    line.setAlphaF(0.6f);
    p.fillRect(QRect(0, height() - 1, width(), 1), line);
}

} // namespace kimcad
