// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QAbstractButton>
#include <QMargins>
#include <QRect>
#include <QWidget>

class QHBoxLayout;
class QLabel;
class QMenu;
class QMenuBar;
class QToolButton;

namespace kimbim {

// One of the minimize / maximize-restore / close buttons, drawn to match the window's palette (the
// close button turns red on hover, as on Windows).
class CaptionButton : public QAbstractButton {
    Q_OBJECT
public:
    enum class Kind { Minimize, Maximize, Close };
    CaptionButton(Kind kind, QWidget* parent = nullptr);
    QSize sizeHint() const override { return {46, 34}; }
    void setRestore(bool restore); // the maximize button shows "restore" while maximized
protected:
    void paintEvent(QPaintEvent*) override;
    void enterEvent(QEnterEvent*) override { update(); }
    void leaveEvent(QEvent*) override { update(); }
private:
    Kind m_kind;
    bool m_restore = false;
};

// D75: the window's one row of chrome, replacing the native title bar, the menu row and the top
// toolbar. Left to right: the app icon, the menus (or one menu button when the bar is too narrow),
// the level and cut controls, a draggable area with the document title, the Versions button and the
// window buttons. Empty areas drag the window; on Windows the native frame keeps Aero snap, the
// resize borders, the shadow and double-click to maximize (MainWindow::nativeEvent asks hitTest).
class TitleBar : public QWidget {
    Q_OBJECT
public:
    explicit TitleBar(QWidget* window);
    QMenuBar* menuBar() const { return m_menuBar; }
    QToolButton* menuButton() const { return m_menuButton; } // the menus, collapsed
    void addControl(QWidget* control);  // the level and cut controls, after the menus
    QWidget* addControlSeparator();
    void setTrailing(QWidget* widget);  // before the window buttons (the Versions button)
    QString title() const;              // what the bar shows
    bool menusCollapsed() const;
    // Whether a point (in this bar's coordinates) drags the window: empty space and the title.
    bool isDragArea(const QPoint& pos) const;

    // Frameless window helpers. install: set up the window (call once, before it is shown).
    static void install(QWidget* window);
    // For QWidget::nativeEvent of the window: WM_NCCALCSIZE and WM_NCHITTEST (Windows only).
    static bool nativeEvent(QWidget* window, TitleBar* bar, const QByteArray& type, void* message, qintptr* result);
    // The content margins (logical pixels) that keep a maximized window's content inside the work
    // area: how far its frame (`frame` px thick) reaches past each side (physical rects). None when the
    // overhang is more than a frame (a minimized window at -32000, -32000).
    static QMargins maximizedMargins(const QRect& window, const QRect& workArea, int frame, qreal dpr);

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;
    void paintEvent(QPaintEvent* event) override;

private:
    void updateTitle();
    void updateCollapse();
    void toggleMaximized();
    void fillMenuButton();

    QWidget* m_window;
    QHBoxLayout* m_row;
    QLabel* m_icon;
    QToolButton* m_menuButton;
    QMenu* m_collapsed;
    QMenuBar* m_menuBar;
    QWidget* m_controls;
    QHBoxLayout* m_controlsRow;
    QLabel* m_title;
    QWidget* m_trailing = nullptr;
    CaptionButton* m_min;
    CaptionButton* m_max;
    CaptionButton* m_close;
};

} // namespace kimbim
