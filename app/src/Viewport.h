// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveContext.hxx>
#include <AIS_ViewController.hxx>
#include <V3d_View.hxx>
#include <NCollection_Vec2.hxx>
#include <V3d_Viewer.hxx>

#include <QHash>
#include <QStringList>
#include <QWidget>

#include <vector>

#include "ElementBatch.h"

namespace kimcad {

// OCCT 3D view in a native Qt widget (D45). Navigation and click-selection come from
// AIS_ViewController; the model is a set of ElementBatch objects (D42).
class Viewport : public QWidget, protected AIS_ViewController {
    Q_OBJECT
public:
    explicit Viewport(QWidget* parent = nullptr);
    ~Viewport() override;

    void addBatch(const Handle(ElementBatch)& batch);
    void clear();
    void fitAll();

    int batchCount() const { return int(m_batches.size()); }
    int elementCount() const { return m_locate.size(); }
    QStringList guids() const; // in batch order
    int visibleElementCount() const;
    qint64 triangleCount() const;

    void selectGuids(const QStringList& guids);
    QStringList selectedGuids() const;
    void setHidden(const QStringList& guids, bool hidden);
    void isolate(const QStringList& guids);
    void showAll();
    void addClipPlanes(const std::vector<Handle(Graphic3d_ClipPlane)>& planes);
    void clearClipPlanes();
    int clipPlaneCount() const { return int(m_clipPlanes.size()); }
    Bnd_Box boundsOf(const QStringList& guids) const; // all visible elements when empty

    // Measurement helpers used by --self-test.
    double measureFps(int frames);
    QString pickAt(int x, int y);
    // Renders the view into an image file through OCCT (independent of screen composition).
    bool dumpImage(const QString& path);
    bool projectCenterOf(const QString& guid, int* x, int* y) const;

    const Handle(AIS_InteractiveContext)& context() const { return m_context; }
    const Handle(V3d_View)& view() const { return m_view; }

    // Navigation (D48, Revit/ArchiCAD preset): middle-drag pans, Shift+middle-drag orbits around the
    // picked point, wheel zooms at the cursor, left-drag box-selects, right button is for menus.
    AIS_MouseGesture gestureFor(Aspect_VKeyMouse button, Aspect_VKeyFlags flags) const;
    AIS_RotationMode rotationMode() const { return RotationMode(); }

signals:
    void selectionChanged(const QStringList& guids);

protected:
    QPaintEngine* paintEngine() const override { return nullptr; }
    void paintEvent(QPaintEvent*) override;
    void resizeEvent(QResizeEvent*) override;
    void mousePressEvent(QMouseEvent*) override;
    void mouseReleaseEvent(QMouseEvent*) override;
    void mouseMoveEvent(QMouseEvent*) override;
    void wheelEvent(QWheelEvent*) override;
    void OnSelectionChanged(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view) override;

private:
    struct Loc {
        int batch;
        int index;
    };
    bool ensureWindow();
    void applyNavigationPreset();
    void redisplay(const std::vector<int>& batches);
    NCollection_Vec2<int> toPixels(const QPointF& p) const;

    Handle(V3d_Viewer) m_viewer;
    Handle(V3d_View) m_view;
    Handle(AIS_InteractiveContext) m_context;
    std::vector<Handle(ElementBatch)> m_batches;
    QHash<QString, Loc> m_locate;
    std::vector<Handle(Graphic3d_ClipPlane)> m_clipPlanes;
};

} // namespace kimcad
