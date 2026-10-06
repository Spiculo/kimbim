// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <AIS_InteractiveContext.hxx>
#include <AIS_ViewController.hxx>
#include <gp_Pnt.hxx>
#include <QColor>
#include <QHash>
#include <QPointF>
#include <QSet>
#include <QVector>
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
    // Lines only (hidden-line drawing, Slice 4b): every batch, including later ones.
    void setLinesOnly(bool on);
    bool linesOnly() const { return m_linesOnly; }
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
    // General tool preview: boxes along a-b, `width` across, from z0 to z1 (absolute metres).
    struct PreviewBox {
        QPointF a, b;
        double width = 0, z0 = 0, z1 = 0;
    };
    void setPreviewBoxes(const QVector<PreviewBox>& boxes);
    // Grid axes of the active level: dashed lines with their tags at both ends (not selectable).
    struct GridLine {
        QPointF a, b;
        QString tag;
    };
    void setGridLines(const QVector<GridLine>& lines, double z);
    // The plan cut's sections (owner feedback): elements cut at height z get a dark fill and a bold
    // outline (poché); nullopt removes them. Kept up to date as elements change.
    void setSectionHeight(std::optional<double> z);
    int sectionElementCount() const { return m_sectionElements; }
    int gridLineCount() const { return m_gridLineCount; }
    void clear();
    void fitAll();

    int batchCount() const { return int(m_batches.size()); }
    int elementCount() const { return m_locate.size(); }
    QStringList guids() const; // in batch order
    QString typeOf(const QString& guid) const; // IFC class of a shown element ("" if unknown)
    // Compare (Slice 8): colour these elements (others keep their class colour) until cleared.
    void setElementColors(const QHash<QString, QColor>& colors);
    void clearElementColors() { setElementColors({}); }
    int coloredCount() const;
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
    // Box selection: by default only elements you can see (not hidden behind others); `through`
    // also takes hidden ones (Alt while dragging, or the select-through setting).
    int selectInRectangle(int x0, int y0, int x1, int y1, AIS_SelectionScheme scheme, bool through = false);
    void setSelectThrough(bool on) { m_selectThrough = on; }
    bool selectThrough() const { return m_selectThrough; }
    // Guids with at least one visible pixel in the rectangle (nullopt: cannot tell, e.g. no window).
    std::optional<QSet<QString>> visibleIn(int x0, int y0, int x1, int y1);

signals:
    void selectionChanged(const QStringList& guids);
    // Drawing mode. tolerance = ~10 screen pixels in metres at that point.
    void workPointMoved(QPointF point, double tolerance, Qt::KeyboardModifiers modifiers);
    void workPointClicked(QPointF point, double tolerance, Qt::KeyboardModifiers modifiers);
    void drawingEnded();      // Esc or right click: cancel / stop
    void drawingConfirmed();  // Enter or double click: finish the current shape
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
    void handleSelectionPoly(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view) override;

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
    bool m_linesOnly = false;
    QHash<QString, QColor> m_colors;
    void applyColors(const Handle(ElementBatch)& batch) const;
    bool m_selectThrough = false;
    bool m_quietSelection = false;
    int m_nextIdBase = 0;
    std::vector<int> m_idBases; // per batch, for decoding ids
    void keepOnlyVisible(const QSet<QString>& before, AIS_SelectionScheme scheme, int x0, int y0, int x1, int y1);
    QSet<QString> selectedSet() const;
    bool m_drawingMode = false;
    double m_workZ = 0.0;
    Handle(ElementBatch) m_preview;
    Handle(AIS_InteractiveObject) m_grid;
    Handle(AIS_InteractiveObject) m_section;
    std::optional<double> m_sectionZ;
    int m_sectionElements = 0;
    void rebuildSection();
    int m_gridLineCount = 0;
    bool workPoint(const QPointF& widgetPos, QPointF* point, double* tolerance);
    double m_planElevation = 0.0;
    std::vector<Handle(Graphic3d_ClipPlane)> m_clipPlanes;
};

} // namespace kimcad
