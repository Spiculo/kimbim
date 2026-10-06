// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QElapsedTimer>
#include <QHash>
#include <QSet>
#include <QJsonArray>
#include <QJsonObject>
#include <QPointF>
#include <QVector>

#include <optional>
#include <QJsonValue>
#include <QStringList>
#include <QMainWindow>
#include <QThread>

#include <Bnd_Box.hxx>

class QAction;
class QDoubleSpinBox;

class QComboBox;
class QToolBar;
class QSlider;
class QLabel;
class QDoubleSpinBox;
class QLineEdit;

namespace kimcad {

class LevelsBar;
class HistoryPanel;
class LayersPanel;
class WallTool;
class PolygonTool;
class HostTool;
class TwoPointTool;
class RotateTool;
class GripTool;
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
    Viewport* viewport() const { return m_viewport; }
    ModelTreePanel* treePanel() const { return m_tree; }
    PropertiesPanel* propertiesPanel() const { return m_properties; }
    void setPlanCutHeight(double metres);
    double planCutHeight() const;

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
    bool newProject();
    bool addLevel(const QString& name, double elevation);
    LevelsBar* levelsBar() const { return m_levels; }
    // Modeling tools (M3): one active at a time. Exposed for tests and the self-test, which drive
    // them with work-plane points.
    enum class Tool { None, Wall, Slab, Door, Window, Column, Beam, Grid, Move, Rotate, Stretch, Stair, SlabOpening, PlaceModel, Text, Dimension, Mark };
    void setTool(Tool tool);
    Tool tool() const { return m_tool; }
    WallTool* wallTool() const { return m_wallTool; }
    PolygonTool* polygonTool() const { return m_polygonTool; }
    HostTool* hostTool() const { return m_hostTool; }
    TwoPointTool* twoPointTool() const { return m_twoPointTool; }
    RotateTool* rotateTool() const { return m_rotateTool; }
    GripTool* gripTool() const { return m_gripTool; }
    // Editing (Slice 6). Walls joined to moved walls follow unless `detach` (Ctrl while clicking).
    bool moveSelection(QPointF delta, bool detach = false);
    bool rotateSelection(QPointF centre, double radians, bool detach = false);
    bool stretchWall(const QString& wall, QPointF p1, QPointF p2);
    bool setWallHeight(const QStringList& walls, double height);
    bool resizeOpening(const QString& guid, double width, double height, double sill);
    // Two-storey houses (Slice 7).
    bool copyToLevel(const QStringList& guids, const QString& storey);
    bool createStair(QPointF start, QPointF towards);
    bool addSlabOpening(const QVector<QPointF>& outline);
    double heightToNextLevel();
    // Versioned projects (Slice 8, docs/03).
    bool enableVersioning(const QString& folder, const QString& message = QString());
    bool openProject(const QString& folder);
    bool saveVersion(const QString& message);
    QJsonArray history();
    bool compareWith(const QString& revA, const QString& revB = QStringLiteral("WORKING"));
    void endCompare();
    int compareChangeCount() const;
    bool createOption(const QString& name);
    bool switchOption(const QString& name);
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
    bool createModel(const QString& name);
    bool placeModelAt(QPointF p, bool turned);
    bool updateModelInstances();
    bool explodeSelectedInstance();
    // Plan annotations (Slice 13): kind "text" (1 point), "dimension" (a, b, line point), "mark".
    bool addAnnotation(const QString& kind, const QVector<QPointF>& points, const QString& text);
    // Drag to move (owner feedback): preview while dragging, move on release (Ctrl detaches).
    void dragMoveTo(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers);
    bool dragFinished(QPointF start, QPointF current, double tolerance, Qt::KeyboardModifiers modifiers);
    // Milliseconds spent per step of editing (accumulated; for the tool benchmark).
    const QHash<QString, double>& timings() const { return m_timings; }
    void resetTimings() { m_timings.clear(); }
    bool columnAt(QPointF p, bool turned = false);
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
    bool save();                        // to the current file; asks for a path if there is none
    bool saveAs(const QString& path);

signals:
    void firstChunkShown();
    void loadFinished(int elements, bool stopped);
    void loadFailed(const QString& error);

protected:
    void closeEvent(QCloseEvent* event) override;

private:
    void buildMenus();
    void buildDocks();
    void showAbout();
    void openDialog();
    void stopLoading();
    void showError(const QString& title, const QString& message);
    void refreshProperties();
    void afterEdit(const QJsonObject& result = {});
    bool maybeSave();
    QJsonObject bridge(const char* fn, const QStringList& args = {});
    void saveAsDialog();
    void addPropertyDialog(const QString& pset);
    void addPropertySetDialog();
    void typeEditDialog(const QString& pset, const QString& prop);
    void refreshLevels();
    void addLevelDialog();
    void setPlanView(bool plan);
    void buildModelingToolbar();
    void refreshTypes();
    void wallHeightDialog();
    void copyToLevelDialog();
    void buildProjectToolbar();
    void refreshProject();
    void refreshLayers();
    void refreshAnnotations();
    void annotationClick(QPointF p);
    void saveVersionDialog();
    void enableVersioningDialog();
    void openProjectDialog();
    void newOptionDialog();
    bool resolveUnsavedForSwitch();
    void openingSizeDialog();
    QJsonObject openingInfo(const QString& guid);
    void updateToolPreview();
    QJsonObject currentType() const;
    void refreshSnapData();
    void showSnap(const Snap& snap);
    void buildCutsToolbar();
    void applyCuts();

    void onOpened(const QJsonObject& info);
    void onChunk(const MeshChunk& chunk);
    void onFinished(int elements, bool stopped);
    void onFailed(const QString& error);

    bool m_quiet;
    bool m_loading = false;
    int m_loadedElements = 0;
    QString m_path;
    QElapsedTimer m_loadTimer;
    Viewport* m_viewport;
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
    bool m_detach = false; // Ctrl held on the click that finished a move/rotate
    std::optional<QPointF> m_columnHover;
    Tool m_tool = Tool::None;
    QHash<int, QAction*> m_toolActions;
    QComboBox* m_types = nullptr;
    QDoubleSpinBox* m_wallHeight = nullptr;
    QAction* m_wallHeightAction = nullptr;
    QAction* m_lengthAction = nullptr;
    bool m_warnedInconsistent = false;
    HistoryPanel* m_history = nullptr;
    LayersPanel* m_layersPanel = nullptr;
    QSet<QString> m_hiddenLayers, m_lockedLayers;
    QString m_currentView;
    QHash<QString, QString> m_instanceOf; // element -> model instance it belongs to
    QHash<QString, QStringList> m_instanceMembers;
    QVector<QPointF> m_annotationPoints; // the dimension tool's clicks so far
    QToolBar* m_projectBar = nullptr;
    QComboBox* m_options = nullptr;
    bool m_versioned = false;
    QHash<QString, double> m_timings;
    QString m_projectFolder;
    QLineEdit* m_lengthInput = nullptr;
    QAction* m_undo = nullptr;
    QAction* m_redo = nullptr;
    QAction* m_planCut = nullptr;
    QAction* m_sectionBox = nullptr;
    QDoubleSpinBox* m_cutHeight = nullptr;
    Bnd_Box m_boxBounds; // captured when the section box is switched on
};

} // namespace kimcad
