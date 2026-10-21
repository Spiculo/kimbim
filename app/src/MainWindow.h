// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QElapsedTimer>
#include <QJsonArray>
#include <QTimer>
#include <QHash>
#include <QSet>
#include <QJsonArray>
#include <QJsonObject>
#include <QPointF>
#include <QVector>

#include <functional>
#include <memory>
#include <QImage>
#include <optional>
#include <QJsonValue>
#include <QStringList>
#include <QJsonObject>
#include <QMainWindow>

#include "Cuts.h"
#include "DockLayout.h"
#include "MaterialsDialog.h"
#include "Preferences.h"
#include <QThread>

#include <Bnd_Box.hxx>

class QAction;
namespace kimbim {

class CutPlanesPanel;
class InputAidsController;
class Tracker;
}
class QMenu;
class QDoubleSpinBox;

class QComboBox;
class QCheckBox;
class QSpinBox;
class QToolBar;
class QToolButton;
class QActionGroup;
class QMenuBar;
class QSlider;
class QLabel;
class QDoubleSpinBox;
class QLineEdit;

namespace kimbim {

class LevelsBar;
class TitleBar;
class ToolPalette;
class StatusStrip;
class ToolOptionsBar;
class Scene;
class ViewHost;
class DrawingsPanel;
class FindSelectPanel;
class LibraryPanel;
class ChecksPanel;
class ConsolePanel;
class SheetsPanel;
class SchedulesDialog;
class DrawingView;
class HistoryPanel;
class LayersPanel;
class WallTool;
class PolygonTool;
class HostTool;
class TwoPointTool;
class RotateTool;
class GripTool;
class MeasureController;
class UnderlayPicker;
class UnderlaySnapIndex;
struct UnderlayLines;
class ModifyTool;
class DraftTool;
struct WallSegment;
struct Snap;
struct Host;

class ModelLoader;
class ModelTreePanel;
class PropertiesPanel;
class Viewport;
struct MeshChunk;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    // quiet: report errors through signals only (no dialogs), for --self-test and automation.
    explicit MainWindow(QWidget* parent = nullptr, bool quiet = false, int chunkSize = 1000);
    ~MainWindow() override;

    void openFile(const QString& path);
    bool isLoading() const { return m_loading; }
    Preferences& preferences() { return m_prefs; }
    DockLayout::Placement newViewPlacement() const
    {
        return m_prefs.newViews() == QLatin1String("window") ? DockLayout::Placement::Floating
                                                             : DockLayout::Placement::AfterCurrent;
    }
    Viewport* viewport() const { return m_viewport; }
    InputAidsController* inputAids() const { return m_inputAids; } // D89: tracker and guides
    ModelTreePanel* treePanel() const { return m_tree; }
    PropertiesPanel* propertiesPanel() const { return m_properties; }
    void setPlanCutHeight(double metres);
    double planCutHeight() const;
    // D91: the plan slice for a level: its own override, else the project setting (1.20 m).
    double planCutForLevel(const QString& storey) const;

    // D95: 3D cut planes, a view state of the 3D view (saved with views; plan tabs unaffected).
    bool addVerticalCut(const QPointF& a, const QPointF& b, const QPointF& keep, double baseZ = 0);
    bool addHorizontalCut(double z);
    bool addObliqueCut(const QPointF& a, const QPointF& b, const QPointF& keep, double degrees, double baseZ = 0);
    bool addFaceCut(const gp_Pnt& point, const gp_Dir& normal);
    QVector<CutPlane> cutPlanes() const;
    int selectedCutPlane() const;
    bool selectCutPlane(int index);
    bool setCutPlaneEnabled(int index, bool on);
    bool setCutPlaneOffset(int index, double offset);
    bool setCutPlaneAngle(int index, double degrees);
    bool flipCutPlane(int index);
    bool removeCutPlane(int index);
    int availableCutPlaneSlots() const;

    // Selection and editing (M2). Edits apply to every selected element as one undoable step.
    void setSelection(const QStringList& guids);
    QStringList selection() const { return m_selection; }
    bool applyPropertyEdit(const QString& pset, const QString& prop, const QJsonValue& value);
    bool applyName(const QString& name);
    bool removeProperty(const QString& pset, const QString& prop);
    // D50: change the value on the selected elements' types (every element of those types), no dialog.
    bool applyTypeEdit(const QString& pset, const QString& prop, const QJsonValue& value);
    bool resetToType(const QString& pset, const QString& prop);
    bool isDirty() const;
    bool deleteSelection();
    // Slice 4: new project, levels, plan view.
    bool newProject(); // from KimBim's built-in template
    // D72: office templates. "builtin" is KimBim's default; a template opens as an untitled project.
    bool newFromTemplate(const QString& path);
    bool saveAsTemplate(const QString& name, bool replace = false); // false if it exists and wasn't replaced
    bool addLevel(const QString& name, double elevation, bool fitBetween = false); // D92: push above or fit between
    LevelsBar* levelsBar() const { return m_levels; }
    // D85: underlays (Underlays.cpp). File > Place underlay... picks a DXF, PDF or image and places it on
    // the active level; placeUnderlay does the same without dialogs (options as app_bridge.add_underlay).
    void placeUnderlayDialog(const QString& path = {});
    QJsonObject placeUnderlay(const QString& path, const QJsonObject& options);
    void underlaysDialog();
    void refreshUnderlays();
    // Calibrate (two points, then their real distance) or move (from, to) an underlay by clicks in the
    // plan: mode is UnderlayPicker::Mode. finishUnderlayPick applies it (distance in metres for a
    // calibration; asked when not given).
    void startUnderlayPick(const QString& id, int mode);
    bool finishUnderlayPick(std::optional<double> distance = std::nullopt);
    UnderlayPicker* underlayPicker() const { return m_underlayPicker.get(); }
    std::shared_ptr<const UnderlaySnapIndex> underlaySnapIndex() const { return m_underlaySnap; }
    TitleBar* titleBar() const { return m_titleBar; } // D75: menus, level, cuts, title, Versions
    // Modeling tools (M3): one active at a time. Exposed for tests and the self-test, which drive
    // them with work-plane points.
    enum class Tool { None, Wall, Slab, Door, Window, Column, Beam, Grid, Move, Rotate, Stretch, Stair, SlabOpening, PlaceModel, Text, Dimension, Mark, Section, Elevation, Leader, Mirror, Room, Roof, Measure, Split, Trim, Join,
        Line, Polyline, ArcCircle, Rectangle, Fill, // 2D drafting (D84, DraftTools.cpp)
        Tag, NorthArrow, ScaleBar, Cloud, AngleDimension, RadialDimension, LevelDimension, // D87, MarkupTools.cpp
        Object, // D86: a library object (LibraryTools.cpp)
        Railing }; // D88, StairTools.cpp
    void setTool(Tool tool);
    Tool tool() const { return m_tool; }
    WallTool* wallTool() const { return m_wallTool; }
    PolygonTool* polygonTool() const { return m_polygonTool; }
    HostTool* hostTool() const { return m_hostTool; }
    TwoPointTool* twoPointTool() const { return m_twoPointTool; }
    RotateTool* rotateTool() const { return m_rotateTool; }
    GripTool* gripTool() const { return m_gripTool; }
    MeasureController* measure() const { return m_measure; } // D79: never edits the model
    // Editing (Slice 6). Walls joined to moved walls follow unless `detach` (Ctrl while clicking).
    bool moveSelection(QPointF delta, bool detach = false);
    bool rotateSelection(QPointF centre, double radians, bool detach = false);
    bool stretchWall(const QString& wall, QPointF p1, QPointF p2);
    bool setWallHeight(const QStringList& walls, double height);
    bool resizeOpening(const QString& guid, double width, double height, double sill);
    // Two-storey houses (Slice 7).
    bool copyToLevel(const QStringList& guids, const QString& storey);
    bool createStair(QPointF start, QPointF towards);
    // D88 (StairTools.cpp): the Stair tool's options choose stair or ramp, its shape (straight, L, U,
    // by sketch: a clicked walking line) and sizes; the Railing tool puts railings on a clicked stair or
    // ramp, or along a clicked path.
    bool createStairSketch(const QVector<QPointF>& walkingLine);
    bool railStairAt(QPointF p);
    bool createRailing(const QVector<QPointF>& path);
    void setStairShape(const QString& kind, const QString& shape, const QString& turn = QStringLiteral("left"));
    bool addSlabOpening(const QVector<QPointF>& outline);
    double heightToNextLevel();
    // Versioned projects (Slice 8, docs/03).
    bool enableVersioning(const QString& folder, const QString& message = QString());
    // D72: files. openPath picks by kind: a folder (project folder), .kim, or .ifc (per preference).
    bool openPath(const QString& path);
    bool openKim(const QString& path, bool readOnly = false);
    bool openIfc(const QString& path);
    // An IFC over the large_ifc_mb preference asks before making a .kim (minutes with the Python
    // decomposer): make it, edit the IFC directly, or cancel. Quiet mode (tests) asks this instead;
    // without it, quiet mode makes the .kim.
    enum class LargeIfc { MakeKim, EditIfc, Cancel };
    void setLargeIfcAnswer(std::function<LargeIfc(const QString& file, double mb)> answer)
    {
        m_largeIfcAnswer = std::move(answer);
    }
    bool openProject(const QString& folder, bool readOnly = false);
    bool saveAsFolder(const QString& folder);
    bool exportIfc(const QString& path);
    bool closeDocument(); // after the unsaved-work question: releases the file's lock
    QJsonObject documentState();
    bool hasUnversionedWork(); // work no version holds yet (Ctrl+S saves the file, not a version)
    // D72: project settings (kept with the .kim / folder, versioned).
    QJsonObject projectSettings() const { return m_settings; }
    // D98: the construction grid's geometry (a project setting); the view and snapping follow.
    bool setConstructionGrid(double spacing, int subdivisions, double angleDegrees, QPointF origin);
    // D98: Archicad's Grid System on the active level (one undo step).
    bool addGridSystem(QPointF corner, double angleDegrees, const QJsonArray& across, const QJsonArray& along,
        double extension);
    bool setProjectSettings(const QJsonObject& changes); // false (and nothing changes) if refused
    // D73: the purpose (pen set, visibility, overrides, layer combination) and the graphics tables.
    bool setPurpose(const QString& name);
    bool setGraphics(const QString& changesJson); // the editors' tables; false (nothing changes) if refused
    void setTrueLineWeights(bool on);
    // The pen for new annotations (the bottom bar's); selected annotations take it too.
    bool setCurrentPen(int pen);
    // Changes the current purpose's pieces (bottom bar "..."); a built-in purpose is copied first as
    // "<name> (modified)", which becomes current. Empty layers: none.
    // An empty renovation filter keeps the purpose's (D74).
    bool customizePurpose(const QString& penSet, const QString& visibility, const QString& overrides, const QString& layers,
        const QString& renovation = QString());
    // D74: the selection's renovation status; the status for new elements; marking elements that have none.
    bool setRenovationStatus(const QString& status);
    bool setStatusForNew(const QString& status);
    bool markUnmarked(const QString& status);
    // Quiet mode: the answer the "mark unmarked elements" question gets when an IFC opens ("" = leave them).
    void setImportStatusAnswer(const QString& status) { m_importStatusAnswer = status; }
    bool setSheetPurpose(const QString& number, const QString& purpose); // "" = the current purpose
    QStringList hiddenLayers() const { return QStringList(m_hiddenLayers.begin(), m_hiddenLayers.end()); }
    QString formatLength(double metres) const;            // in the project's unit and decimals
    QString formatArea(double squareMetres) const;        // D92: in the project's area unit and decimals
    // D72: recovery copies of unsaved work (written every N minutes; offered after a crash).
    bool writeRecovery();
    QJsonArray recoveries();
    bool recoverFrom(const QString& id);
    void offerRecovery(); // asks about each copy (not in quiet mode)
    bool saveVersion(const QString& message);
    QJsonArray history();
    bool compareWith(const QString& revA, const QString& revB = QStringLiteral("WORKING"));
    void endCompare();
    int compareChangeCount() const;
    bool createOption(const QString& name);
    bool switchOption(const QString& name);
    // Slice 20: milestones (named versions), deleting an option, object history, before/after.
    bool addMilestone(const QString& name, const QString& message = QString());
    bool deleteOption(const QString& name);
    // Slice 22: combine another option into the current one (choices: conflict id -> choice); the
    // combined model opens as unsaved work, coloured by what the other option brought.
    bool combineOptions(const QString& option, const QJsonObject& choices = QJsonObject());
    QJsonObject objectHistory(const QString& guid);
    QJsonObject beforeAfter(const QString& guid, const QString& revA, const QString& revB = QStringLiteral("WORKING"));
    bool discardChanges();
    bool isVersioned() const { return m_versioned; }
    // Layers and views (Slice 11, owner feedback).
    bool createLayer(const QString& name);
    bool assignSelectionToLayer(const QString& layer);
    void setLayerVisible(const QString& layer, bool visible);
    void setLayerLocked(const QString& layer, bool locked);
    bool setActiveLayer(const QString& layer);
    bool saveView(const QString& name);
    bool applyView(const QString& name);
    LayersPanel* layersPanel() const { return m_layersPanel; }
    // Models (Slice 12, owner feedback): a unit drawn once and placed on many levels.
    bool createWorksheet(const QString& name); // D98
    bool worksheetCommand(const char* command, const QStringList& args); // rename_worksheet, delete_worksheet
    bool createModel(const QString& name);
    bool placeModelAt(QPointF p, bool turned);
    bool updateModelInstances();
    bool explodeSelectedInstance();
    // Plan annotations (Slice 13): kind "text" (1 point), "dimension" (a, b, line point), "mark".
    bool addAnnotation(const QString& kind, const QVector<QPointF>& points, const QString& text);
    // Sections and elevations (Slice 14, D60/D61). kind "section" or "elevation": the marker line
    // p1-p2 looking towards `look` (Archicad's third click), infinite depth.
    bool createDrawing(const QString& kind, QPointF p1, QPointF p2, QPointF look);
    DrawingsPanel* drawingsPanel() const { return m_drawingsPanel; }
    QString drawingGuid(const QString& name); // "" if there is none
    // Open (or show) a drawing's tab and generate it in the background if it is out of date.
    bool openDrawing(const QString& guid);
    DrawingView* drawingView(const QString& guid) const { return m_drawingViews.value(guid); }
    void regenerateDrawing(const QString& guid);
    void showModelTab();
    // D71: the docking layout; the key of the current center view ("3d", "plan:<guid>", a drawing
    // guid or "sheet:<number>").
    DockLayout* dockLayout() const { return m_dock; }
    QString currentViewKey() const;
    bool currentViewShowsCutSlider() const; // D91: false in plan tabs (no cut slider there)
    // A level's plan tab (D71): opened once, raised after; a view of the same model as the 3D tab.
    Viewport* openPlanTab(const QString& storey); // nullptr if it isn't a level of this model
    Viewport* modelView() const;                  // the 3D tab's view
    ToolPalette* toolPalette() const { return m_palette; } // D71: the tools on the left
    ToolOptionsBar* toolOptions() const { return m_toolOptions; } // the active tool's fields
    StatusStrip* statusStrip() const { return m_status; }          // the bottom bar
    // Sheets and project info (Slice 16, M4 exit).
    SheetsPanel* sheetsPanel() const { return m_sheetsPanel; }
    // Schedules and quantities (D77): the schedule window, opened on a scheme ("doors", "rooms", ...).
    SchedulesDialog* openSchedules(const QString& scheme = QString());
    SchedulesDialog* schedulesDialog() const { return m_schedules; }
    QString addSheet(const QString& paper, const QString& title); // its number, "" on failure
    bool placeOnSheet(const QString& number, const QString& drawingGuid);
    bool placeLegend(const QString& number); // D74: a legend of the sheet's purpose, at a free spot
    bool openSheet(const QString& number);
    DrawingView* sheetView(const QString& number) const { return m_drawingViews.value(QStringLiteral("sheet:") + number); }
    bool exportSheet(const QString& number, const QString& path); // .pdf or .svg
    bool setProjectInfo(const QJsonObject& info);
    // D91: the sheet's title block, moved and its fields edited (saved with the sheet).
    QJsonObject titleBlock(const QString& number);
    bool setTitleBlock(const QString& number, const QJsonObject& changes);
    void editTitleBlock(const QString& number);
    // How many elements the last generation sent to the serializer (-1: all, no visible pass).
    int lastDrawingVisibleCount() const { return m_lastDrawingVisible; }
    // Milliseconds the last drawing's visible-element pass spent on the GUI thread (before the worker).
    double lastDrawingIncludeMs() const { return m_lastIncludeMs; }
    // Everyday editing (Slice 17, Archicad's Edit menu). Copies are selected afterwards.
    bool copySelection(QPointF delta);          // a moved copy (Ctrl+drag)
    void copyToClipboard();                     // Ctrl+C
    bool paste();                               // Ctrl+V: onto the active level, same plan position
    bool duplicateSelection();                  // Ctrl+D
    bool mirrorSelection(QPointF a, QPointF b, bool copy); // Ctrl+M tool: two clicks; Ctrl copies
    bool multiplySelection(const QString& kind, const QJsonObject& params); // Ctrl+U: linear / polar
    bool offsetSelection(double distance);
    // D80: split, trim/extend (to a boundary or a corner), join/merge and unjoin walls and beams
    // (ModifyEdits.cpp). Ctrl (join = false) leaves the elements unjoined.
    ModifyTool* modifyTool() const { return m_modifyTool; }
    // D84: 2D drafting (DraftTools.cpp). The options bar gives the line type, the arc mode and a fill's
    // pattern, background pen and area label; the pen is the current pen.
    DraftTool* draftTool() const { return m_draftTool; }
    static bool isDraftTool(Tool tool);
    bool addDrafting(const QString& kind, const QVector<QPointF>& points, bool closed = false);
    bool fillAt(QPointF p); // Alt+click with the Fill tool: fill the closed shape around p
    QJsonObject draftOptions(const QString& kind) const;
    // Stretch tool on a drafting shape (D84 grips): a click near one of its points picks it up, the
    // next click puts it down. False when nothing was near (the wall stretch goes on).
    bool draftGripClick(QPointF p, double tolerance, bool ortho);
    bool draftGripActive() const { return m_gripIndex >= 0; }
    // D87: the annotation pack (MarkupTools.cpp). Tag: click an element (with the leader on, then where
    // the text goes); north arrow, scale bar, revision cloud (drawn like a fill), angle (vertex, a point
    // on each side, the arc), radius/diameter (centre, a point on the circle, the text), level (a
    // point) or spot elevation (the point, the text). Tag all: the active level's untagged doors,
    // windows and walls that the view shows.
    static bool isMarkupTool(Tool tool);
    bool addTag(const QString& elementGuid, std::optional<QPointF> at = std::nullopt);
    bool addSymbol(const QString& kind, const QVector<QPointF>& points, const QString& text = QString());
    bool addCloud(const QVector<QPointF>& points);
    int tagAll();
    bool placeSheetSymbol(const QString& number, const QString& kind);
    bool placeSheetImage(const QString& number, const QString& path); // D98
    bool placeFigure(const QString& path, double widthMetres, QPointF bottomLeft); // D98: File > Place picture
    bool splitElement(const QString& guid, QPointF at, bool join = true);
    bool trimElement(const QString& guid, QPointF keep, const QString& boundary, QPointF b1, QPointF b2, bool join = true);
    bool cornerElements(const QString& first, QPointF p1, const QString& second, QPointF p2, bool join = true);
    bool joinElements(const QString& first, const QString& second);
    bool unjoinElements(const QString& first, const QString& second);
    // Drag to move (owner feedback): preview while dragging, move on release (Ctrl detaches).
    void dragMoveTo(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers);
    bool dragFinished(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers);
    // Milliseconds spent per step of editing (accumulated; for the tool benchmark).
    const QHash<QString, double>& timings() const { return m_timings; }
    void resetTimings() { m_timings.clear(); }
    bool columnAt(QPointF p, bool turned = false);
    // Slice 18: a room (Archicad zone) filling the walls around p; name asked unless quiet.
    bool roomAt(QPointF p, const QString& name = QString());
    // Slice 19: a roof over an outline (the roof kind and pitch from the toolbar); walls trimmed to it.
    bool createRoof(const QVector<QPointF>& outline);
    bool trimWallsToRoof(const QStringList& selection);
    bool releaseWallsFromRoof(const QStringList& selection);
    void setRoofKind(const QString& kind, double pitch);
    bool createSegment(QPointF p1, QPointF p2); // beam or grid axis, per the active tool
    int gridLineCount() const;
    void setWallToolActive(bool on) { setTool(on ? Tool::Wall : Tool::None); }
    bool createWall(const WallSegment& segment);
    bool createSlab(const QVector<QPointF>& outline);
    bool slabFromWalls(const QStringList& walls);
    bool insertOpening(const Host& host);
    bool treeHasGuid(const QString& guid) const;
    // Re-mesh changed elements and drop removed ones after an edit/undo/redo ({changed, removed}).
    void applyGeometry(const QJsonObject& geometry);
    // D78: selection tools (SelectionTools.cpp). Select similar: "type" = the selected elements' IFC
    // types (untyped: same class and predefined type), "class" = their classes. Find & Select runs a
    // query (kimbim.queries) and changes the selection by `how`: "replace", "add" or "remove"; it
    // returns how many elements matched (-1 if refused). Only what can be selected is taken: not on
    // hidden or locked layers, not hidden in the view. Criteria and selection sets are project settings.
    bool selectSimilar(const QString& mode);
    void selectAll(); // D92: with a creation tool active, its elements; otherwise everything
    static QString toolElementClass(Tool tool); // the IFC class a creation tool makes ("" if none)
    int findAndSelect(const QJsonObject& query, const QString& how = QStringLiteral("replace"));
    bool saveSelectionCriteria(const QString& name, const QJsonObject& criteria);
    bool deleteSelectionCriteria(const QString& name);
    bool saveSelectionSet(const QString& name);
    bool recallSelectionSet(const QString& name, const QString& how = QStringLiteral("replace"));
    bool deleteSelectionSet(const QString& name);
    FindSelectPanel* findSelectPanel(); // created and docked on first use
    // D86: the object library (LibraryTools.cpp). The Library panel (docked on first use) picks the
    // object and its parameters; the Object tool places it on the active level where you click,
    // turned by the object angle (Tab: +90 degrees, a typed number: that angle; Shift+click: +90
    // for that click). One undo step per object; the status for new elements and the active layer.
    LibraryPanel* libraryPanel();
    bool chooseObject(const QString& id, const QJsonObject& params = {}); // and start the Object tool
    bool placeObjectAt(QPointF p, bool turned = false);
    double objectAngle() const { return m_objectAngle; } // degrees
    void setObjectAngle(double degrees);
    void applyLibraryPaths(); // the office library from the preferences (folder and IFC files)
    // D81: checks (Checks.cpp). Runs kimbim.checks ("schema", "ids", "clash", "model") one by one on a
    // worker thread behind a progress dialog (Cancel stops them) and lists the issues in the panel;
    // false if any could not run or it was cancelled. IDS files (their XML) and clash sets are
    // project settings. showIssue selects the issue's elements and fits the view to them.
    ChecksPanel* checksPanel(); // created and docked on first use (Model > Check model...)
    bool runChecks(const QStringList& checks, const QJsonObject& options = {});
    bool addIdsFile(const QString& path);
    bool linkIdsFile(const QString& path); // D92: keep the IDS as a path into a folder, not embedded
    bool removeIdsFile(const QString& name);
    bool exportIdsReport(const QString& path);
    bool saveClashSet(const QString& name, const QJsonObject& set, const QString& replaces = QString());
    bool deleteClashSet(const QString& name);
    void showIssue(const QStringList& guids);
    // D82: the Python console (ConsoleTools.cpp). Runs code / a .py file in kimbim.console's namespace on a
    // worker thread (Stop interrupts it), shows the output in the panel, then applies its edits (afterEdit)
    // and selection. Returns console_run's result: {ok, output, error, traceback, geometry, edited, select}.
    ConsolePanel* consolePanel(); // created and docked on first use
    QJsonObject runConsole(const QString& code);
    QJsonObject runConsoleFile(const QString& path);
    bool save();                        // to the current file; asks for a path if there is none
    bool saveAs(const QString& path);

signals:
    void firstChunkShown();
    void loadFinished(int elements, bool stopped);
    void loadFailed(const QString& error);

protected:
    void closeEvent(QCloseEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;
    bool nativeEvent(const QByteArray& eventType, void* message, qintptr* result) override;

private:
    void buildMenus();
    void buildDocks();
    // A corrupt saved layout/geometry can ask for a multi-gigabyte window; reset it after show.
    void clampWindowSize();
    void applyDrawingPrefs(); // the drawing timeout and hidden-line mode, from the preferences
    void applyViewPreferences(); // D92: the perspective field of view and the home view, from the preferences
    void refreshNorthArrow(); // D92: the plan north indicator, from true north and the preference
    void applyTitleBarPreferences(); // D92: which controls the title bar holds
    void showAbout();
    void openDialog();
    void stopLoading();
    void showError(const QString& title, const QString& message);
    void refreshProperties();
    void afterEdit(const QJsonObject& result = {});
    bool maybeSave();
    QJsonObject bridge(const char* fn, const QStringList& args = {});
    // The same call on a worker thread, behind a progress dialog (slow work such as making a .kim).
    QJsonObject bridgeInBackground(const char* fn, const QStringList& args, const QString& label);
    void saveAsDialog();
    void addPropertyDialog(const QString& pset);
    void addPropertySetDialog();
    void typeEditDialog(const QString& pset, const QString& prop);
    void refreshLevels();
    void addLevelDialog();
    void levelsDialog(); // D79: Model > Levels..., the levels table
    void materialsDialog(MaterialsEdits::Kind kind); // D96: Graphics > Building materials / Surfaces / Composites
    void materialsCommand(const char* command, const QString& done);
    bool setElementMaterial(const QString& kind, const QString& name); // D96: the Properties panel's Material row
    QString wallReference() const;
    void refreshConstructionGrid(); // D98
    void gridOptionsDialog();
    void gridSystemDialog(); // D98: Model > Grid system...
    bool flipWalls(const QStringList& guids); // D97: Model > Flip walls
    bool setJunctions(const QString& mode);    // D97: through, butt or materials, for the selection
    void setPlanView(bool plan);
    void buildModelingToolbar();
    void buildPalette();
    void newSheetDialog(const QString& paper);
    void refreshTypes();
    void wallHeightDialog();
    void copyToLevelDialog();
    void buildVersions();
    void updateVersionsButton();
    void enableVersioningDialog();
    void refreshProject();
    void refreshLayers();
    void refreshGraphics();
    void regenerateOpenDrawings();
    void editPurposePieces();
    void refreshAnnotations();
    void annotationClick(QPointF p, Qt::KeyboardModifiers modifiers = {});
    void afterCopy(const QJsonObject& result);
    void multiplyDialog();
    void offsetDialog();
    void refreshDrawings();
    void refreshSheets(bool changed = true); // changed: the model changed, sheets need composing again
    void projectInfoDialog();
    void roomScheduleDialog();
    void exportSheetDialog(bool pdf);
    void exportDxfDialog(); // D83: File > Export DXF... (DxfExport.cpp)
    void addUnderlayActions(QMenu* file); // D85 (Underlays.cpp)
    void drawingClick(QPointF p);
    void onDrawingGenerated(const QString& guid, const QJsonObject& result, const QString& error);
    void activateView(const QString& key);
    void activateElement(const QString& guid); // double-click: properties, or a level's plan
    // Every model view gets the same signal handlers: `connect` runs for the views open now and
    // for every plan tab opened later.
    void onEachView(const std::function<void(Viewport*)>& connect);
    void closePlanTabs(const QStringList& keep = {});
    void closeView(const QString& key);
    void saveVersionDialog();
    LargeIfc askLargeIfc(const QString& path, double mb);
    void askImportStatus(); // D74: after an IFC opens, offer to mark the elements without a status
    bool askReadOnly(const QJsonObject& refused);
    bool prepareToOpen();
    void rememberRecent(const QString& path);
    void fillRecentMenu();
    void maybeAutoVersion();
    void afterSave();
    bool commitVersion(const QString& message);
    void saveAsFolderDialog();
    void exportIfcDialog();
    void newProjectDialog();
    void saveAsTemplateDialog();
    void projectSettingsDialog();
    void loadProjectSettings();
    void resetForNewModel();
    void preferencesDialog();
    void restartRecoveryTimer();
    void saveLayerStates();
    void openProjectDialog();
    void newOptionDialog();
    void milestoneDialog();
    void deleteOptionDialog();
    void combineDialog();
    void objectHistoryDialog();
    void beforeAfterDialog(const QString& guid, const QString& revA, const QString& revB);
    bool resolveUnsavedForSwitch();
    void openingSizeDialog();
    QJsonObject openingInfo(const QString& guid);
    void updateToolPreview();
    void setupModifyTools(ToolOptionsBar* bar); // D80
    void startModifyTool(Tool tool);
    void updateModifyPreview();
    void setupDraftTools(ToolOptionsBar* bar); // D84
    void setupLibrary(QMenu* model); // D86
    void updateObjectPreview();
    void refreshLibrary();
    void startDraftTool(Tool tool);
    void draftPointer(QPointF p, double tolerance, Qt::KeyboardModifiers mods, bool click);
    void updateDraftPreview();
    void setupStairTools(ToolOptionsBar* bar); // D88
    void startStairTool(Tool tool);
    bool stairPointer(QPointF p, double tolerance, Qt::KeyboardModifiers mods, bool click);
    void updateStairPreview();
    QJsonObject stairOptions() const;
    QJsonObject stairSymbolData(); // the level's stair symbols; refreshes the stair/part map
    void expandAssemblies(QStringList& guids) const;
    void setupMarkupTools(ToolOptionsBar* bar); // D87
    void setupInputAids();                      // D89 (MainWindowInputAids.cpp)
    bool trackerTool() const;                   // the current tool places points
    bool trackerClassic(const Tracker& tracker); // the tool's own typed value
    void startMarkupTool(Tool tool);
    void markupPointer(QPointF p, double tolerance, bool click);
    void updateMarkupPreview();
    bool modifyResult(const QJsonObject& r, const QString& failure);
    QJsonObject currentType() const;
    void refreshSnapData();
    void showSnap(const Snap& snap);
    void buildCutsToolbar();
    void applyCuts();
    struct CutSettings;
    void applyCutsTo(Viewport* view, CutSettings& settings);
    int addCutPlaneTo3D(const CutPlane& plane);
    void pushCutPlanesToPanel();
    enum class CutTool { None, Vertical, Oblique, Face };
    void startCutTool(CutTool tool);
    void endCutTool();
    void cutPlaneClick(const QPointF& p);
    void horizontalCutDialog();
    CutTool m_cutTool = CutTool::None;
    QVector<QPointF> m_cutPoints;
    QVector<CutPlane> m_cutDragBase;
    QMenu* m_cutPlanesMenu = nullptr;

    void applySelection(const QStringList& guids, const QString& how); // D78
    QStringList unselectableLayers() const;
    void refreshFindSelect();
    FindSelectPanel* m_findSelect = nullptr;
    LibraryPanel* m_library = nullptr;
    QAction* m_objectTurn = nullptr; // Tab while the Object tool is active
    double m_objectAngle = 0.0;
    std::optional<QPointF> m_objectHover;
    bool m_libraryPathsSent = false;
    void refreshChecks(); // D81
    ChecksPanel* m_checks = nullptr;
    void buildConsoleActions();
    void runScriptDialog();
    QJsonObject runConsoleCall(const char* fn, const QString& arg);
    ConsolePanel* m_console = nullptr;

    void onOpened(const QJsonObject& info);
    void onChunk(const MeshChunk& chunk);
    void onFinished(int elements, bool stopped);
    void onFailed(const QString& error);

    bool m_quiet;
    QString m_importStatusAnswer;
    bool m_askImportStatus = false; // an IFC is loading: ask about unmarked elements when it's done
    std::function<LargeIfc(const QString&, double)> m_largeIfcAnswer;
    Preferences m_prefs; // D72: user preferences (in memory only in quiet mode)
    bool m_loading = false;
    int m_loadedElements = 0;
    QString m_path;
    QElapsedTimer m_loadTimer;
    Scene* m_scene;
    Viewport* m_viewport; // the active model view (3D or a plan tab)
    ModelTreePanel* m_tree;
    PropertiesPanel* m_properties;
    QThread m_thread;
    ModelLoader* m_loader;
    QStringList m_selection;
    QSlider* m_cutSlider = nullptr;
    QLabel* m_cutLabel = nullptr;
    void updateCutSliderRange();
    LevelsBar* m_levels = nullptr;
    WallTool* m_wallTool = nullptr;
    PolygonTool* m_polygonTool = nullptr;
    HostTool* m_hostTool = nullptr;
    TwoPointTool* m_twoPointTool = nullptr;
    RotateTool* m_rotateTool = nullptr;
    GripTool* m_gripTool = nullptr;
    MeasureController* m_measure = nullptr;
    QToolButton* m_measureCopy = nullptr;
    ModifyTool* m_modifyTool = nullptr;
    QComboBox* m_modifyMode = nullptr;
    DraftTool* m_draftTool = nullptr;
    QString m_gripGuid; // a drafting shape's point being moved by the Stretch tool
    int m_gripIndex = -1;
    QVector<QPointF> m_gripPoints;
    QComboBox* m_draftLineType = nullptr;
    QComboBox* m_draftArcMode = nullptr;
    QComboBox* m_draftPolyMode = nullptr; // D98: polyline or spline
    QComboBox* m_draftPattern = nullptr;
    QSpinBox* m_draftBackground = nullptr; // 0: no background
    QToolButton* m_draftShowArea = nullptr;
    QSpinBox* m_draftOutline = nullptr; // D92: -1 the fill's pen, 0 none
    QComboBox* m_draftPatternScale = nullptr; // D92: paper or model
    bool m_gripRect = false; // D92: the gripped shape is a rectangle (stays rectangular when asked)
    QComboBox* m_tagStyle = nullptr;   // D87: Automatic (by kind) or a tag style
    QComboBox* m_tagShape = nullptr;   // the style's, or none / circle / box / hexagon
    QToolButton* m_tagLeader = nullptr;
    QComboBox* m_markupMode = nullptr; // radius / diameter, level / spot
    QLineEdit* m_markupText = nullptr; // a revision cloud's revision
    QString m_tagElement;              // the element picked, waiting for the text's place (leader)
    std::optional<QPointF> m_markupHover;
    DraftTool* m_pathTool = nullptr;      // D88: a stair's walking line, a railing's path
    QComboBox* m_stairKind = nullptr;     // stair / ramp
    QComboBox* m_stairShape = nullptr;    // straight, L, U, sketch
    QComboBox* m_stairTurn = nullptr;     // left / right
    QDoubleSpinBox* m_stairWidth = nullptr;
    QDoubleSpinBox* m_stairTread = nullptr;
    QDoubleSpinBox* m_stairRiser = nullptr;   // target riser
    QDoubleSpinBox* m_stairLanding = nullptr; // 0: the width
    QDoubleSpinBox* m_rampSlope = nullptr;    // percent
    QDoubleSpinBox* m_rampRise = nullptr;
    QComboBox* m_railingMode = nullptr;   // on a stair / by path
    QDoubleSpinBox* m_railingHeight = nullptr;
    QHash<QString, QString> m_assemblyOf;          // a stair's part or symbol -> the stair
    QHash<QString, QStringList> m_assemblyMembers; // stair -> its parts
    QHash<QString, QString> m_assemblyType;        // stair -> IfcStair / IfcRamp
    bool m_detach = false; // Ctrl held on the click that finished a move/rotate
    std::optional<QPointF> m_columnHover;
    Tool m_tool = Tool::None;
    QHash<int, QAction*> m_toolActions;
    QComboBox* m_types = nullptr;
    QDoubleSpinBox* m_wallHeight = nullptr;
    QComboBox* m_wallReference = nullptr; // D97: the Wall tool's reference line location
    QAction* m_gridShow = nullptr; // D98: View > Construction grid
    QAction* m_gridSnap = nullptr; // D98: View > Grid snap
    QCheckBox* m_objectGravity = nullptr; // D97: objects land on the slab under them
    QComboBox* m_roofKind = nullptr;
    QDoubleSpinBox* m_roofPitch = nullptr;
    bool m_warnedInconsistent = false;
    HistoryPanel* m_history = nullptr;
    LayersPanel* m_layersPanel = nullptr;
    QSet<QString> m_hiddenLayers, m_lockedLayers;
    QMenu* m_graphicsMenu = nullptr; // D73: the editors (Tasks 11-12 add to it)
    QString m_currentView;
    QHash<QString, QString> m_instanceOf; // element -> model instance it belongs to
    QHash<QString, QStringList> m_instanceMembers;
    QVector<QPointF> m_annotationPoints; // the dimension/section tool's clicks so far
    QStringList m_clipboard;            // Ctrl+C
    DockLayout* m_dock = nullptr;     // center views and side panels (D71)
    QHash<QString, ViewHost*> m_hosts; // model views by key: "3d", "plan:<guid>"
    QWidget* m_cutColumn = nullptr;    // the plan-cut slider, in the active model view
    QVector<std::function<void(Viewport*)>> m_viewConnectors;
    ToolPalette* m_palette = nullptr;
    QMenu* m_viewMenu = nullptr;
    ToolOptionsBar* m_toolOptions = nullptr;
    StatusStrip* m_status = nullptr;
    // Each view has its own cuts (a plan tab is cut at its level; the 3D tab need not be).
    struct CutSettings {
        bool planCut = false;
        bool box = false;
        double height = 1.2;
        Bnd_Box bounds;
        QVector<CutPlane> planes; // D95: user planes (the 3D view's; plan tabs keep them empty)
        int selectedPlane = -1;
    };
    QHash<Viewport*, CutSettings> m_cuts;
    DrawingsPanel* m_drawingsPanel = nullptr;
    SheetsPanel* m_sheetsPanel = nullptr;
    SchedulesDialog* m_schedules = nullptr;
    QHash<QString, DrawingView*> m_drawingViews;
    QSet<QString> m_generating, m_generateAgain;
    QList<QThread*> m_drawingThreads;
    int m_lastDrawingVisible = -1;
    double m_lastIncludeMs = 0;
    bool m_clamping = false; // guards against recursion while resetting a corrupt window size
    TitleBar* m_titleBar = nullptr;     // D75: the one row of chrome
    QMenuBar* m_menuBar = nullptr;      // in the title bar (QMainWindow::menuBar() would replace it)
    QMenu* m_helpMenu = nullptr;
    QMenu* m_versionsMenu = nullptr;    // D75: everything about versions, also behind the Versions button
    QToolButton* m_versionsButton = nullptr;
    QList<QAction*> m_projectActions;   // the Versions entries shown in versioned projects
    QList<QAction*> m_unversionedActions; // ...and the ones shown in unversioned projects
    QList<QAction*> m_optionActions;    // the design options, current one checked
    QActionGroup* m_optionGroup = nullptr;
    QAction* m_newOptionAction = nullptr;
    QString m_currentOption;
    QString m_compareA, m_compareB; // the versions being compared (empty when not comparing)
    bool m_versioned = false;
    QHash<QString, double> m_timings;
    QString m_projectFolder;
    QMenu* m_recentMenu = nullptr;
    int m_savesSinceVersion = 0; // D72: automatic versions every N saves...
    QElapsedTimer m_sinceVersion; // ...or N minutes
    QJsonObject m_document;
    bool m_panelsShrunk = false; // D92: the panels are at their smaller width
    QJsonObject m_settings;       // the project settings (D72)
    QTimer m_recoveryTimer;       // D72: the recovery copy
    QLineEdit* m_lengthInput = nullptr;
    InputAidsController* m_inputAids = nullptr; // D89
    QAction* m_undo = nullptr;
    QAction* m_redo = nullptr;
    QAction* m_planCut = nullptr;
    QAction* m_sectionBox = nullptr;
    CutPlanesPanel* m_cutPlanesPanel = nullptr;
    QDoubleSpinBox* m_cutHeight = nullptr;
    QWidget* m_planCutButton = nullptr; // D92: the title bar controls the preferences can hide
    QWidget* m_cutSeparator = nullptr;
    QMenu* m_fileMenu = nullptr;
    Bnd_Box m_boxBounds; // captured when the section box is switched on
    // D85: underlays (Underlays.cpp): linework by file, page images by file/page/dpi/colour.
    QHash<QString, std::shared_ptr<const UnderlayLines>> m_underlayLines;
    QHash<QString, QImage> m_underlayImages;
    std::shared_ptr<const UnderlaySnapIndex> m_underlaySnap;
    QString m_underlaySnapKey;
    std::shared_ptr<UnderlayPicker> m_underlayPicker;
};

} // namespace kimbim
