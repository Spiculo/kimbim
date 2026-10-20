// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QObject>
#include <QPointer>
#include <QPointF>
#include <QTimer>

#include <functional>
#include <memory>

#include "InputAids.h"
#include "Tracker.h"

class QKeyEvent;

namespace kimbim {

class Viewport;

// D89: one tracker and one set of guides for every point-placing tool. It watches each view's work
// points after the window's tool dispatch (so the tool's Snapper has just recorded its anchor and
// snapped point in the shared InputAids), takes the drawing keys before the view and the window's
// shortcuts (digits, Tab, '<', ';', 'a'/'#', '@', and Enter/Esc/Backspace while something is
// typed), keeps the Snapper locks in step with the typed values, and places a typed point by sending
// the view's own workPointMoved/workPointClicked signals with a negative tolerance (exact: no
// snapping), so every tool takes it exactly as a click. A lone typed length goes to the tool's own
// typed-length handling first (Hooks::classic), which keeps each tool's meaning of "a length".
class InputAidsController : public QObject {
    Q_OBJECT
public:
    struct Hooks {
        std::function<bool()> active;                // the current tool places points
        std::function<bool(const Tracker&)> classic; // the tool takes the typed value its own way (true: used)
        std::function<double()> planZ;               // the work plane's height (guides overlay)
    };
    explicit InputAidsController(Hooks hooks, QObject* parent = nullptr);

    const std::shared_ptr<InputAids>& aids() const { return m_aids; }
    Tracker& tracker() { return m_tracker; }
    void attach(Viewport* v);
    bool commit(Viewport* v);       // Enter: place the typed point (false: nothing to place)
    void reset();                   // the tool changed: typed values and guides gone
    void clearGuides();
    void setGuidesEnabled(bool on);
    QTimer& acquireTimer() { return m_acquire; } // half a second on a snap point acquires it
    bool trackerShown() const { return m_trackerShown; }

signals:
    void guidesChanged();

protected:
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    void moved(Viewport* v, QPointF p, double tolerance, Qt::KeyboardModifiers mods);
    void inputChanged(); // typed values changed: locks, the tool's preview, the overlays
    void rerun();        // the last mouse position again through the window's dispatch
    void refresh();
    void hide(Viewport* v);
    bool isTrackerKey(const QKeyEvent* e) const;

    Hooks m_hooks;
    std::shared_ptr<InputAids> m_aids;
    Tracker m_tracker;
    QTimer m_acquire;
    QPointer<Viewport> m_view;
    QPointF m_raw;
    double m_tolerance = 0.1;
    Qt::KeyboardModifiers m_mods;
    int m_serial = -1;
    bool m_committing = false;
    bool m_hasPointer = false;
    bool m_trackerShown = false;
};

} // namespace kimbim
