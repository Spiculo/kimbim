// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveContext.hxx>
#include <AIS_ViewController.hxx>
#include <gp_Pnt.hxx>
#include <QPointF>
#include <utility>
#include <optional>
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
    // Live edits (Slice 4): new geometry for these elements (old instances retired, selection kept),
    // or elements gone from the model.
    void replaceElements(const MeshChunk& chunk);
    void removeElements(const QStringList& guids);

    // Plan view (Slice 4): straight down on a level, no orbit. set3DView() returns to the 3D view.
    void setPlanView(double elevation);
    void set3DView();
    bool isPlanView() const { return m_planView; }
    double planElevation() const { return m_planElevation; }
    // Screen point -> point on the horizontal plane z (metres). False without a window or when the
    // view ray is parallel to the plane.
    bool pointOnPlane(int x, int y, double z, gp_Pnt* out);

    // Drawing mode (wall tool): left clicks and moves become points on the work plane (z, metres)
    // instead of selection; middle-button navigation keeps working. Esc/right click end drawing.
    void setDrawingMode(bool on, double workPlaneZ = 0.0);
    bool isDrawingMode() const { return m_drawingMode; }
    // Rubber-band wall preview: a box along p1-p2 (plan metres); nullopt hides it.
    void setWallPreview(const std::optional<std::pair<QPointF, QPointF>>& axis, double thickness, double height);
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
    Aspect_VKeyMouse pressedButtons() const { return PressedMouseButtons(); }
    AIS_MouseGesture activeGesture() const { return myMouseActiveGesture; }
    AIS_RotationMode rotationMode() const { return RotationMode(); }
    // Click/box selection modifiers: plain = replace, Ctrl = add (Revit), Shift = toggle (ArchiCAD).
    AIS_SelectionScheme selectionSchemeFor(Aspect_VKeyMouse button, Aspect_VKeyFlags flags) const;
    // Box selection in window pixels (what left-drag does); returns how many elements are selected.
    int selectInRectangle(int x0, int y0, int x1, int y1, AIS_SelectionScheme scheme);

signals:
    void selectionChanged(const QStringList& guids);
    // Drawing mode. tolerance = ~10 screen pixels in metres at that point.
    void workPointMoved(QPointF point, double tolerance, Qt::KeyboardModifiers modifiers);
    void workPointClicked(QPointF point, double tolerance, Qt::KeyboardModifiers modifiers);
    void drawingEnded();
    void lengthKeyTyped(const QString& text);

protected:
    QPaintEngine* paintEngine() const override { return nullptr; }
    void paintEvent(QPaintEvent*) override;
    void resizeEvent(QResizeEvent*) override;
    void mousePressEvent(QMouseEvent*) override;
    void mouseReleaseEvent(QMouseEvent*) override;
    void mouseMoveEvent(QMouseEvent*) override;
    void wheelEvent(QWheelEvent*) override;
    void keyPressEvent(QKeyEvent*) override;
    void mouseDoubleClickEvent(QMouseEvent*) override;
    void OnSelectionChanged(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view) override;

private:
    struct Loc {
        int batch;
        int index;
    };
    bool ensureWindow();
    void applyNavigationPreset();
    void redisplay(const std::vector<int>& batches);
    bool retire(const QString& guid, std::vector<int>* touched); // true if it was selected
    NCollection_Vec2<int> toPixels(const QPointF& p) const;

    Handle(V3d_Viewer) m_viewer;
    Handle(V3d_View) m_view;
    Handle(AIS_InteractiveContext) m_context;
    std::vector<Handle(ElementBatch)> m_batches;
    QHash<QString, Loc> m_locate;
    bool m_planView = false;
    bool m_drawingMode = false;
    double m_workZ = 0.0;
    Handle(ElementBatch) m_preview;
    bool workPoint(const QPointF& widgetPos, QPointF* point, double* tolerance);
    double m_planElevation = 0.0;
    std::vector<Handle(Graphic3d_ClipPlane)> m_clipPlanes;
};

} // namespace kimcad
