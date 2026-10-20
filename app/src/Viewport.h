// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QPointer>

#include <AIS_AnimationCamera.hxx>
#include <AIS_InteractiveContext.hxx>
#include <AIS_ViewCube.hxx>
#include <AIS_ViewController.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <QColor>
#include <QHash>
#include <QPoint>
#include <QLineF>
#include <QPointF>
#include <QSet>
#include <QVector>
#include <utility>
#include <optional>
#include <V3d_View.hxx>
#include <NCollection_Vec2.hxx>
#include <V3d_Viewer.hxx>
#include <gp_Ax2.hxx>
#include <gp_Pln.hxx>

#include <QHash>
#include <QJsonArray>
#include <QJsonObject>
#include <QRect>
#include <QStringList>
#include <QWidget>

#include <array>
#include <functional>
#include <memory>
#include <vector>

#include <Image_PixMap.hxx>

#include "ElementBatch.h"
#include "Scene.h"
#include "Underlay.h"

class QTimer;
class QWheelEvent;

namespace kimbim {

// OCCT 3D view in a native Qt widget (D45). Navigation and click-selection come from
// AIS_ViewController; the model is a set of ElementBatch objects (D42) held by a Scene that several
// views can share (D71: the 3D tab and plan tabs).
class Viewport : public QWidget, protected AIS_ViewController {
    Q_OBJECT
public:
    explicit Viewport(QWidget* parent = nullptr);               // owns a new Scene (tests, self-test)
    explicit Viewport(Scene* scene, QWidget* parent = nullptr); // one view of `scene`
    ~Viewport() override;
    Scene* scene() const { return m_scene; }

    void addBatch(const Handle(ElementBatch)& batch);
    // Live edits (Slice 4): new geometry for these elements (old instances retired, selection kept),
    // or elements gone from the model.
    void replaceElements(const MeshChunk& chunk);
    void removeElements(const QStringList& guids);

    // Plan view (Slice 4): straight down on a level, no orbit. set3DView() returns to the 3D view.
    void setPlanView(double elevation);
    void set3DView();
    bool isPlanView() const { return m_planView; }
    // Preset views (D76): the camera turns (~250 ms) to look from that side or corner, keeping its
    // target and zoom; it fits all when the model would be off-screen. Not in plan views.
    void setStandardView(V3d_TypeOfOrientation orientation, bool animate = true);
    // Home view (D76, D92): south-east isometric by default; the user can set the current view as home
    // (a preference, applied to every viewport).
    void homeView(bool animate = true);
    static void setHomeView(const gp_Dir& dir, const gp_Dir& up);
    static gp_Dir homeDir();
    static gp_Dir homeUp();
    void useCurrentViewAsHome();           // capture this view's camera direction and up as home
    gp_Dir currentViewDirection() const;
    gp_Dir currentViewUp() const;
    static void setFieldOfView(double degrees); // the perspective camera's vertical field of view (D92)
    static double fieldOfView();
    // D92: how a box selects: by drag direction (AutoCAD), or Archicad's partial (any touch) / entire
    // (fully inside), whatever the direction.
    enum class BoxMode { Direction, Partial, Entire };
    static void setBoxMode(BoxMode mode);
    static BoxMode boxMode();
    static BoxMode boxModeFrom(const QString& preference); // "direction", "partial", "entire"
    // Perspective camera (D76), per view; plan views stay orthographic (the setting comes back in 3D).
    void setPerspective(bool on);
    bool isPerspective() const { return m_perspective; }
    bool isAnimating() const;
    void setAnimationDuration(double seconds) { m_animationSeconds = seconds; }
    // D92: the plan view's north indicator (a view option, on once true north is set). Display only;
    // shown only in plan views. `degrees` is counter-clockwise from the plan's +Y.
    void setNorthArrow(bool show, double degrees);
    bool northArrowShown() const { return m_planView && m_northWanted; }
    double northArrowAngle() const { return m_northDegrees; }
    // The view cube and its home button (D76), top right of 3D views; hidden in plan views.
    bool viewCubeShown() const { return !m_planView; }
    QRect viewCubeRect() const;   // widget pixels; clicks inside never reach selection
    QRect homeButtonRect() const;
    // The cube face, edge or corner under a widget point (false: none, or no window).
    bool viewCubeOrientationAt(const QPointF& pos, V3d_TypeOfOrientation* orientation);
    // Lines only (hidden-line drawing, Slice 4b): every batch, including later ones.
    void setLinesOnly(bool on);
    bool linesOnly() const { return m_scene->linesOnly; }
    double planElevation() const { return m_planElevation; }
    // Screen point -> point on the horizontal plane z (metres). False without a window or when the
    // view ray is parallel to the plane.
    bool pointOnPlane(int x, int y, double z, gp_Pnt* out);

    // Drawing mode (wall tool): left clicks and moves become points on the work plane (z, metres)
    // instead of selection; middle-button navigation keeps working. Esc/right click end drawing.
    void setDrawingMode(bool on, double workPlaneZ = 0.0);
    void setWorkPlaneZ(double z) { m_workZ = z; }
    bool isDrawingMode() const { return m_drawingMode; }
    // Rubber-band wall preview: a box along p1-p2 (plan metres); nullopt hides it.
    void setWallPreview(const std::optional<std::pair<QPointF, QPointF>>& axis, double thickness, double height);
    // General tool preview: boxes along a-b, `width` across, from z0 to z1 (absolute metres).
    struct PreviewBox {
        QPointF a, b;
        double width = 0, z0 = 0, z1 = 0;
    };
    void setPreviewBoxes(const QVector<PreviewBox>& boxes);
    // D79: the active tool's own drawing in this view (the measure path); null removes it.
    void setToolOverlay(const Handle(AIS_InteractiveObject)& overlay);
    bool hasToolOverlay() const { return !m_toolOverlay.IsNull(); }
    // The first element surface under a widget point, world metres (false: none, or no window).
    bool surfacePointAt(const QPointF& widgetPos, gp_Pnt* out);
    QPointF pointerPos() const { return m_pointer; } // the mouse's last position while drawing
    // D89: the input aids' drawings in this view (temporary guides in the plan, the tracker beside
    // the cursor); null removes one. Display only, over the model.
    enum class AidOverlay { Guides, Tracker };
    void setAidOverlay(AidOverlay which, const Handle(AIS_InteractiveObject)& overlay);
    bool hasAidOverlay(AidOverlay which) const { return m_aidOverlays.contains(int(which)); }
    // D89 Tab cycling (Revit): Tab with the mouse resting over overlapping elements highlights the
    // next one under the cursor (Shift+Tab the previous); a click there selects the highlighted one.
    QString cycleNext(const QPointF& widgetPos, bool backwards = false); // the highlighted guid ("" none)
    QString cycleCandidate() const { return m_cycleGuid; }
    QStringList elementsAt(const QPointF& widgetPos); // front to back (needs a window, or a provider)
    void setPickProvider(std::function<QStringList(const QPointF&)> provider) { m_pickProvider = std::move(provider); }
    // D89 touchpad: two-finger scroll pans (Shift: orbits in 3D), pinch and Ctrl+scroll zoom; with
    // "zoom" every wheel event zooms (mouse), with "pan" every un-modified scroll pans (touchpad),
    // "auto" tells them apart (pixel deltas, horizontal deltas or scroll phases mean a touchpad).
    enum class ScrollMode { Auto, Zoom, Pan };
    static void setScrollMode(ScrollMode mode);
    static ScrollMode scrollMode();
    static ScrollMode scrollModeFrom(const QString& preference); // "auto", "zoom", "pan"
    enum class ScrollAction { None, Zoom, Pan, Orbit };
    ScrollAction lastScrollAction() const { return m_lastScroll; } // for tests
    void panByPixels(double dx, double dy);                  // the content follows (widget pixels)
    void zoomByFactor(double factor, const QPointF& widgetPos); // > 1 zooms in, keeping widgetPos still
    // Grid axes of the active level: dashed lines with their tags at both ends (not selectable).
    struct GridLine {
        QPointF a, b;
        QString tag;
    };
    void setGridLines(const QVector<GridLine>& lines, double z);
    // D85: underlays drawn in this view under the model (just above level `z`): DXF linework as one
    // OCCT segment array per underlay (vertex colours, placement as the object's transformation, so a
    // move or rotation re-uses the GPU buffers); PDF pages and images as a textured quad. Not
    // selectable. An underlay whose display settings are unchanged keeps its presentation.
    struct UnderlayView {
        Underlay underlay;
        std::shared_ptr<const UnderlayLines> lines; // DXF
        QImage image;                               // PDF page or image, already greyscaled/tinted
        double z = 0.0;
    };
    void setUnderlays(const QVector<UnderlayView>& underlays);
    int underlayCount() const { return int(m_underlays.size()); }
    qint64 underlaySegmentCount() const;
    // Plan annotations of the active level (Slice 13): text labels, dimensions, marks; drawn on
    // top, selectable (their guids join selectedGuids), hidden/locked with their layer.
    struct Annotation {
        QString guid, kind, text;
        QVector<QPointF> points; // world metres: text/mark anchor; dimension chain points + line point; leader tip..text
        double size = 2.5;       // text size in millimetres on paper (printed at 1:100)
        int pen = 0;             // D73: its pen; 0 = the annotations kind's pen
        // D84 drafting shapes (line, polyline, arc, circle, fill), drawn in plan views only: the
        // polylines to draw, the line type's dashes (mm on paper), and a fill's area, hatch,
        // solid or background pen and area label (text, at labelAt).
        QVector<QVector<QPointF>> curves;
        QVector<double> dash;
        QVector<QPointF> area;
        QVector<QLineF> hatch;
        bool solid = false;
        int backgroundPen = 0;
        std::optional<QPointF> labelAt;
        bool isDrafting() const;
        // D87 symbols (tags, north arrows, scale bars, clouds, angle/radius/level dimensions), drawn in
        // plan views only: `curves` as above, filled polygons in the pen's colour, and text labels
        // (anchor: -1 start, 0 middle, 1 end).
        struct Label {
            QString text;
            QPointF at;
            double size = 2.5;
            int anchor = 0;
        };
        bool symbol = false;
        QVector<QVector<QPointF>> solids;
        QVector<Label> labels;
    };
    int draftingCount() const; // drafting shapes shown
    QVector<QPointF> annotationPoints(const QString& guid) const; // as listed (world metres)
    void setAnnotations(const QVector<Annotation>& annotations, double z);
    int annotationCount() const;
    // Section and elevation markers (Slice 14): kind "section"/"elevation", text = the drawing's
    // name, points = the line's two ends and a point on the side it looks at. Shown in plan view on
    // every level (not in 3D, as in Archicad), selectable like annotations (Move, Rotate, Delete).
    void setDrawingMarkers(const QVector<Annotation>& markers, double z);
    int markerCount() const;
    QStringList annotationGuids() const;
    QStringList annotationTexts() const;
    // The plan cut's sections (owner feedback): elements cut at height z get a dark fill and a bold
    // outline (poché); nullopt removes them. Kept up to date as elements change.
    void setSectionHeight(std::optional<double> z);
    int sectionElementCount() const { return m_sectionElements; }
    int gridLineCount() const { return m_gridLineCount; }
    void clear();
    void fitAll();
    void fitTo(const QStringList& guids); // D81: zoom to these elements (keeps the direction)
    double zoomPercent() const; // 100 = the fitted view (D71: the bottom bar)

    int batchCount() const { return int(m_scene->batches.size()); }
    int elementCount() const { return m_scene->locate.size(); }
    QStringList guids() const; // in batch order
    QString typeOf(const QString& guid) const; // IFC class of a shown element ("" if unknown)
    // Compare (Slice 8): colour these elements (others keep their class colour) until cleared.
    void setElementColors(const QHash<QString, QColor>& colors);
    void clearElementColors() { setElementColors({}); }
    int coloredCount() const;
    // Layers (Slice 11): elements hidden or locked by their layer's state in the current view.
    void setLayerState(const QSet<QString>& hiddenGuids, const QSet<QString>& lockedGuids);
    bool isLocked(const QString& guid) const;
    int visibleElementCount() const;
    qint64 triangleCount() const;

    void selectGuids(const QStringList& guids);
    QStringList selectedGuids() const;
    // D73: the purpose's styles, visibility and pens, for every view of the scene (and its poché).
    void setGraphics(const Graphics& graphics, bool trueWeights);
    const Graphics& graphics() const { return m_scene->graphics; }
    bool isElementHidden(const QString& guid) const; // hidden for any reason (user, layer, visibility)
    void setHidden(const QStringList& guids, bool hidden);
    void isolate(const QStringList& guids);
    void showAll();
    void addClipPlanes(const std::vector<Handle(Graphic3d_ClipPlane)>& planes);
    void clearClipPlanes();
    int clipPlaneCount() const { return int(m_clipPlanes.size()); }
    int viewClipPlaneCount() const; // the cut planes on this view's V3d_View
    // Overlays belong to their view (D71); for tests.
    bool showsOverlay(const Handle(AIS_InteractiveObject)& obj, const Handle(V3d_View)& view) const;
    Handle(AIS_InteractiveObject) gridObject() const { return m_grid; }
    Bnd_Box boundsOf(const QStringList& guids) const; // all visible elements when empty
    // The box of these elements' meshes (the building's), less the far outliers of a georeferenced
    // site: what a drawing frames. Void if none of them is shown.
    Bnd_Box buildingBounds(const QStringList& guids) const;

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
    // D78: dragged right to left (x1 < x0) it is a crossing box (takes what it touches), left to right
    // a window box (only what is fully inside), as in AutoCAD and Revit.
    int selectInRectangle(int x0, int y0, int x1, int y1, AIS_SelectionScheme scheme, bool through = false);
    static bool isCrossingBox(int startX, int endX)
    {
        if (s_boxMode == BoxMode::Partial)
            return true;
        if (s_boxMode == BoxMode::Entire)
            return false;
        return endX < startX;
    }
    static BoxMode s_boxMode;
    void setSelectThrough(bool on) { m_selectThrough = on; }
    bool selectThrough() const { return m_selectThrough; }
    // Guids with at least one visible pixel in the rectangle (nullopt: cannot tell, e.g. no window).
    std::optional<QSet<QString>> visibleIn(int x0, int y0, int x1, int y1);
    // Elements a section/elevation can see (Slice 14 visible-element pass, spike S6): an
    // orthographic camera on the line p1-p2 looking towards `look`, between heights z0 and z1,
    // up to `depth` metres beyond the line (< 0: no limit). Rendered offscreen in id colours.
    std::optional<QSet<QString>> visibleFrom(QPointF p1, QPointF p2, QPointF look, double z0, double z1, double depth);
    // Elements a floor plan can see (Slice 14 pass, for plan drawings): a top-down orthographic camera
    // over the model's `bounds` at `elevation`, cut `cut` metres above it, keeping what is below the
    // cut down to `floor` metres below the level. Rendered offscreen in id colours.
    std::optional<QSet<QString>> visibleFromPlan(const Bnd_Box& bounds, double elevation, double cut, double floor);
    // Mesh-based plan geometry for a drawing (no hidden-line pass): per element, its cut outline at
    // `cutZ` when it crosses that plane, else the outline of its top below it (projection). World x,y.
    // {cut: [{guid, loops}], proj: [{guid, loops}], bounds: [x0, y0, x1, y1]}.
    QJsonObject planGeometry(const QStringList& guids, double cutZ, double floorZ) const;
    // Mesh-based section/elevation geometry (OCCT polygon hidden-line removal, fast): the visible
    // edges of each element in the view plane and, for a section (`section` not null), the cut
    // outlines. View-plane metres (x right, y up), plus the view->world matrix for the SVG.
    // {proj: [{guid, lines: [x1,y1,x2,y2, ...]}], cut: [{guid, loops}], view: [16 numbers]}.
    QJsonObject viewGeometry(const QStringList& guids, const gp_Ax2& view, const gp_Pln* section, const Bnd_Box& bounds);
    QJsonObject finishViewGeometry(const gp_Ax3& ax3, const QJsonArray& proj, const gp_Pln* section) const;

signals:
    void selectionChanged(const QStringList& guids);
    // Drawing mode. tolerance = ~10 screen pixels in metres at that point.
    void workPointMoved(QPointF point, double tolerance, Qt::KeyboardModifiers modifiers);
    void workPointClicked(QPointF point, double tolerance, Qt::KeyboardModifiers modifiers);
    void drawingEnded();      // Esc or right click: cancel / stop
    void drawingConfirmed();  // Enter or double click: finish the current shape
    void lengthKeyTyped(const QString& text);
    // The mouse rested on an element ("" when it left it): the app shows a hint.
    void hovered(const QString& guid, const QPoint& globalPos);
    void zoomChanged(double percent);
    // Double-click on an element or a plan note (not while drawing): its properties (D71).
    void elementDoubleClicked(const QString& guid);
    // Drag to move (owner feedback): left-drag that starts on a selected element; points on the work
    // plane, tolerance = ~10 px in metres.
    void dragMoved(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers);
    void dragReleased(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers);

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
    bool event(QEvent*) override;                       // D89: native touchpad gestures
    bool focusNextPrevChild(bool) override { return false; } // D89: Tab is the view's (cycling, tracker)
    void leaveEvent(QEvent*) override;
    void OnSelectionChanged(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view) override;
    void handleSelectionPoly(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view) override;
    void handleViewRedraw(const Handle(AIS_InteractiveContext)& ctx, const Handle(V3d_View)& view) override;

private:
    bool ensureWindow();
    void applyNavigationPreset();
    void redisplay(const std::vector<int>& batches);
    bool retire(const QString& guid, std::vector<int>* touched); // true if it was selected
    NCollection_Vec2<int> toPixels(const QPointF& p) const;

    QPointer<Scene> m_scene;                  // shared with the other views of the model (a closed tab's view
                                              // can be deleted late: never touch a scene that is gone)
    Handle(AIS_InteractiveContext) m_context; // == m_scene->context()
    Handle(V3d_View) m_view;
    bool m_planView = false;
    bool applyLayerState(const Handle(ElementBatch)& batch) const; // true if any element changed
    void applyColors(const Handle(ElementBatch)& batch) const;
    bool applyGraphics(const Handle(ElementBatch)& batch) const; // true if any element changed
    bool m_selectThrough = false;
    void keepOnlyVisible(const QSet<QString>& before, AIS_SelectionScheme scheme, int x0, int y0, int x1, int y1);
    // Renders the view's camera into a w x h offscreen image in id colours; guids seen in the rectangle.
    std::optional<QSet<QString>> idsInImage(int w, int h, int x0, int y0, int x1, int y1);
    // The id image from the current camera: every shown element in its id colour, nothing else (the
    // annotations, grid, cube, previews and underlays are left out). Rows from the top.
    struct IdImage {
        std::shared_ptr<Image_PixMap> image;
        std::array<int, 256> toLinear{};
        bool bgr = false;
        int width = 0, height = 0;
        int at(int x, int y) const; // the element id at a pixel (0: none); x right, y down
    };
    std::optional<IdImage> renderIds(int w, int h);
    QString guidOfId(int id) const; // empty if not a live element
    QSet<QString> selectedSet() const;
    bool m_drawingMode = false;
    QTimer* m_hoverTimer = nullptr;
    bool m_dragCandidate = false;
    bool m_dragging = false;
    QPointF m_dragPressPos;
    QPointF m_dragStart;
    QPointF m_hoverPos;
    double m_workZ = 0.0;
    Handle(ElementBatch) m_preview;
    Handle(AIS_InteractiveObject) m_toolOverlay;
    QPointF m_pointer;
    Handle(AIS_InteractiveObject) m_grid;
    QVector<Annotation> m_annotationData;
    QVector<Annotation> m_markerData;
    double m_annotationZ = 0.0;
    QHash<QString, Handle(AIS_InteractiveObject)> m_annotations;
    void displayAnnotations();
    Handle(AIS_InteractiveObject) m_section;
    std::optional<double> m_sectionZ;
    int m_sectionElements = 0;
    void rebuildSection();
    void keepHere(const Handle(AIS_InteractiveObject)& obj);
    void keepOverlaysHere();
    int m_gridLineCount = 0;
    struct UnderlayShown {
        Handle(AIS_InteractiveObject) prs;
        QString key;
        qint64 segments = 0;
    };
    QHash<QString, UnderlayShown> m_underlays; // by underlay id (ViewportUnderlays.cpp)
    void removeUnderlays();
    bool workPoint(const QPointF& widgetPos, QPointF* point, double* tolerance);
    double m_planElevation = 0.0;
    double m_fitScale = 0.0; // the view's scale when fitted (100%)
    double m_lastZoom = -1.0;
    std::vector<Handle(Graphic3d_ClipPlane)> m_clipPlanes;
    // D76: view cube, preset views, perspective.
    void ensureViewCube();
    void eraseViewCube();
    // D92: the plan north compass.
    void ensureNorthArrow();
    void eraseNorthArrow();
    Handle(AIS_InteractiveObject) m_northArrow;
    double m_northDpr = 0.0;
    double m_northAngleShown = -1.0;
    bool m_northWanted = false;
    double m_northDegrees = 0.0;
    void applyProjection();
    void goTo(const gp_Dir& dir, const gp_Dir& up, bool animate, bool fit);
    void animateTo(const Handle(Graphic3d_Camera)& end, bool animate);
    void orbitBy(double dx, double dy); // dragging the cube: turntable around the view's target
    enum class CubePress { None, Cube, Home };
    Handle(AIS_ViewCube) m_cube;
    Handle(AIS_InteractiveObject) m_home;
    double m_cubeDpr = 0.0;
    Handle(AIS_AnimationCamera) m_animation;
    double m_animationSeconds = 0.25;
    bool m_perspective = false;
    // D89 (ViewportInput.cpp)
    QHash<int, Handle(AIS_InteractiveObject)> m_aidOverlays;
    QStringList m_cycleList;
    int m_cycleIndex = 0;
    QString m_cycleGuid;
    QPointF m_cyclePos;
    bool m_cycleClick = false; // the press selected the cycled element: swallow its release
    std::function<QStringList(const QPointF&)> m_pickProvider;
    ScrollAction m_lastScroll = ScrollAction::None;
    bool touchpadScroll(QWheelEvent* e);
    bool cycleClick(QMouseEvent* e);
    void highlightCycled();
    CubePress m_cubePress = CubePress::None;
    QPointF m_cubePressPos;
    bool m_cubeDragging = false;
};

} // namespace kimbim
