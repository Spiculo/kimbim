# SPDX-License-Identifier: GPL-3.0-or-later
# kimbim_core: everything except main(), so tests link the same code as the app.
qt_add_library(kimbim_core STATIC
    src/MainWindow.cpp src/MainWindow.h
    src/Translations.cpp src/Translations.h
    src/PythonEngine.cpp src/PythonEngine.h
    src/MeshChunk.cpp src/MeshChunk.h
    src/ElementBatch.cpp src/ElementBatch.h
    src/Viewport.cpp src/Viewport.h src/ViewportInput.cpp
    src/ViewCube.cpp src/ViewCube.h
    src/SelfTest.cpp src/SelfTest.h src/SelfTestRealOpen.cpp
    src/ModelTreePanel.cpp src/ModelTreePanel.h
    src/PropertiesPanel.cpp src/PropertiesPanel.h
    src/LevelsBar.cpp src/LevelsBar.h
    src/HistoryPanel.cpp src/HistoryPanel.h
    src/CombineDialog.cpp src/CombineDialog.h
    src/LayersPanel.cpp src/LayersPanel.h
    src/Icons.cpp src/Icons.h
    src/Snapper.cpp src/Snapper.h
    src/InputAids.cpp src/InputAids.h src/Tracker.cpp src/Tracker.h
    src/InputAidsController.cpp src/InputAidsController.h src/InputAidsOverlay.cpp src/InputAidsOverlay.h src/MainWindowInputAids.cpp
    src/WallTool.cpp src/WallTool.h
    src/PolygonTool.cpp src/PolygonTool.h
    src/HostTool.cpp src/HostTool.h
    src/TwoPointTool.cpp src/TwoPointTool.h
    src/MeasureTool.cpp src/MeasureTool.h
    src/MeasureOverlay.cpp src/MeasureOverlay.h
    src/MeasureController.cpp src/MeasureController.h
    src/LevelsDialog.cpp src/LevelsDialog.h
    src/RotateTool.cpp src/RotateTool.h
    src/GripTool.cpp src/GripTool.h
    src/ModifyTool.cpp src/ModifyTool.h src/ModifyEdits.cpp
    src/DraftTool.cpp src/DraftTool.h src/DraftTools.cpp src/MarkupTools.cpp src/StairTools.cpp
    src/ModelLoader.cpp src/ModelLoader.h
    src/Cuts.cpp src/Cuts.h src/CutPlanes.cpp src/CutPlanes.h
    src/CutPlaneOverlay.cpp src/CutPlaneOverlay.h src/CutPlanesPanel.cpp src/CutPlanesPanel.h
    src/DrawingsPanel.cpp src/DrawingsPanel.h
    src/DrawingView.cpp src/DrawingView.h
    src/SectionPath.cpp src/SectionPath.h
    src/SheetExport.cpp src/SheetExport.h
    src/SnapshotServer.cpp src/SnapshotServer.h
    src/SheetsPanel.cpp src/SheetsPanel.h
    src/SheetDialog.cpp src/SheetDialog.h
    src/SchedulesDialog.cpp src/SchedulesDialog.h
    src/DockLayout.cpp src/DockLayout.h
    src/Scene.cpp src/Scene.h
    src/ViewHost.cpp src/ViewHost.h
    src/ToolPalette.cpp src/ToolPalette.h
    src/ToolOptionsBar.cpp src/ToolOptionsBar.h
    src/StatusStrip.cpp src/StatusStrip.h
    src/ProposalBar.cpp src/ProposalBar.h
    src/ProposalDialog.cpp src/ProposalDialog.h
    src/AssistantPanel.cpp src/AssistantPanel.h
    src/TitleBar.cpp src/TitleBar.h
    src/Graphics.cpp src/Graphics.h
    src/PenGrid.cpp src/PenGrid.h
    src/GraphicsDialogs.cpp src/GraphicsDialogs.h src/RuleDialogs.cpp src/PurposeDialogs.cpp src/RenovationDialogs.cpp
    src/Preferences.cpp src/Preferences.h
    src/ProjectSettingsDialog.cpp src/ProjectSettingsDialog.h
    src/PreferencesDialog.cpp src/PreferencesDialog.h
    src/FindSelectPanel.cpp src/FindSelectPanel.h src/SelectionTools.cpp
    src/ChecksPanel.cpp src/ChecksPanel.h src/Checks.cpp
    src/ConsolePanel.cpp src/ConsolePanel.h src/ConsoleTools.cpp
    src/DxfExportDialog.cpp src/DxfExportDialog.h src/DxfExport.cpp
    src/Underlay.cpp src/Underlay.h src/ViewportUnderlays.cpp
    src/UnderlayDialogs.cpp src/UnderlayDialogs.h src/Underlays.cpp
    src/LibraryPanel.cpp src/LibraryPanel.h src/LibraryTools.cpp
    src/ObjectSettingsDialog.cpp src/ObjectSettingsDialog.h
    src/ObjectEditorDialog.cpp src/ObjectEditorDialog.h src/JsonTreeEditor.cpp src/JsonTreeEditor.h
    src/MaterialsDialog.cpp src/MaterialsDialog.h
    src/TypeManagerDialog.cpp src/TypeManagerDialog.h
    src/ClassificationsDialog.cpp src/ClassificationsDialog.h src/Types.cpp
)
target_include_directories(kimbim_core PUBLIC src)
# Element icons (owner feedback: objects need an icon and a hint on hover).
file(GLOB KIMBIM_ICONS RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} resources/icons/*.svg)
qt_add_resources(kimbim_core "kimbim_icons" PREFIX "/icons" BASE resources/icons FILES ${KIMBIM_ICONS})
target_link_libraries(kimbim_core PUBLIC Qt6::Widgets Qt6::Svg Python3::Python
    TKernel TKMath TKService TKV3d TKOpenGl TKBRep TKG3d ads::qtadvanceddocking-qt6)
target_include_directories(kimbim_core PUBLIC ${OpenCASCADE_INCLUDE_DIR})
if(WIN32)
    target_link_libraries(kimbim_core PUBLIC dwmapi) # D75: the custom title bar keeps the native frame
endif()
target_compile_definitions(kimbim_core PUBLIC KIMBIM_VERSION="${PROJECT_VERSION}" _USE_MATH_DEFINES)
qt_add_translations(kimbim_core
    TS_FILES translations/kimbim_en.ts translations/kimbim_es.ts
    RESOURCE_PREFIX /i18n
)

qt_add_executable(kimbim-app src/main.cpp)
target_link_libraries(kimbim-app PRIVATE kimbim_core)

function(kimbim_test name)
    qt_add_executable(${name} tests/${name}.cpp)
    target_link_libraries(${name} PRIVATE kimbim_core Qt6::Test)
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen;KIMBIM_PYTHON_PATH=${PROJECT_SOURCE_DIR}/python")
endfunction()

kimbim_test(test_translations)
kimbim_test(test_python_engine)
kimbim_test(test_mesh_chunk)
kimbim_test(test_element_batch)
kimbim_test(test_model_tree)
kimbim_test(test_visibility)
kimbim_test(test_main_window)
kimbim_test(test_agent_live)
kimbim_test(test_cuts)
kimbim_test(test_cut_planes)
kimbim_test(test_section_path)
kimbim_test(test_model_loader)
kimbim_test(test_navigation)
kimbim_test(test_selection)
kimbim_test(test_selection_tools)
kimbim_test(test_library)
kimbim_test(test_checks)
kimbim_test(test_console)
kimbim_test(test_properties_panel)
kimbim_test(test_levels_bar)
kimbim_test(test_snapper)
kimbim_test(test_input_aids)
kimbim_test(test_tracker)
kimbim_test(test_wall_tool)
kimbim_test(test_polygon_tool)
kimbim_test(test_host_tool)
kimbim_test(test_two_point_tool)
kimbim_test(test_draft_tool)
kimbim_test(test_markup_tools)
kimbim_test(test_measure_and_levels)
kimbim_test(test_rotate_tool)
kimbim_test(test_grip_tool)
kimbim_test(test_modify_tool)
kimbim_test(test_dock_layout)
kimbim_test(test_scene)
kimbim_test(test_tool_palette)
kimbim_test(test_preferences)
kimbim_test(test_graphics)
kimbim_test(test_dxf_export)
kimbim_test(test_underlays)
kimbim_test(test_materials_dialog)
kimbim_test(test_object_settings)
kimbim_test(test_types)
kimbim_test(test_object_editor)

# GUI self-tests: need a real OpenGL window (GPU, or Mesa on the Linux CI runner). Label "gui".
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/broken.ifc "ISO-10303-21;
this is not IFC
")
function(kimbim_gui_test name pass_regex)
    add_test(NAME ${name} COMMAND kimbim-app --self-test ${ARGN})
    set_tests_properties(${name} PROPERTIES
        LABELS gui
        ENVIRONMENT "KIMBIM_PYTHON_PATH=${PROJECT_SOURCE_DIR}/python"
        PASS_REGULAR_EXPRESSION "${pass_regex}")
endfunction()
kimbim_gui_test(app_selftest_fixture
    "\"ok\":true.*\"pick_matched\":2.*\"pick_missed\":0.*\"tree_follows_selection\":true" :fixture: --frames 5)
kimbim_gui_test(app_selftest_broken_file "\"ok\":false" ${CMAKE_CURRENT_BINARY_DIR}/broken.ifc)
kimbim_gui_test(app_selftest_quit_during_load "\"ok\":true,\"quit_during_load\":true" :fixture: --quit-during-load --chunk 1)
kimbim_gui_test(app_selftest_pop_out "\"ok\":true.*\"pop_out\":true" :fixture: --frames 2 --pop-out)
# D71: a plan tab open while the window closes: no OpenGL errors from views torn down after their window.
kimbim_gui_test(app_selftest_plan_tab_exit "\"ok\":true" :fixture: --frames 2 --bench-edit --plan-tab)
set_tests_properties(app_selftest_plan_tab_exit PROPERTIES FAIL_REGULAR_EXPRESSION "MakeCurrent\(\) has failed|Type: Error")
# A maximized window minimized while a model loads (the person switches away) and restored: it keeps
# to the screen (it grew to 32800 x 32164 px and crashed). --real-open: preferences, layout, questions.
kimbim_gui_test(app_selftest_minimize_maximized "\"ok\":true" :fixture: --real-open --maximized --minimize)
set_tests_properties(app_selftest_minimize_maximized PROPERTIES TIMEOUT 180) # the broken window resized forever
kimbim_gui_test(app_selftest_plan_cut "\"ok\":true.*\"planes\":1" :fixture: --frames 5 --plan-cut 1.5)
kimbim_gui_test(app_selftest_draw_walls "\"elements\":4,\"joins\":4,\"ok\":true,\"walls\":4" :new: --draw-walls "0,0 5,0 5,4 0,4 0,0")
kimbim_gui_test(app_selftest_house "\"beams\":1,\"columns\":1,\"doors\":1,\"elements\":9,\"grid\":4,\"joins\":4,\"ok\":true,\"openings\":2,\"slabs\":1,\"walls\":4,\"windows\":1" :new: --house)
kimbim_gui_test(app_selftest_box_select_visible "\"box_selected\":1,.*\"ok\":true" :occlusion: --frames 5 --box-select)
kimbim_gui_test(app_selftest_box_select_through "\"box_selected\":2,.*\"ok\":true" :occlusion: --frames 5 --box-select --select-through)
kimbim_gui_test(app_selftest_box_select "\"box_selected\":2.*\"ok\":true.*\"tree_selected\":2" :fixture: --frames 5 --box-select)
# D78: right to left is a crossing box, left to right a window box.
kimbim_gui_test(app_selftest_box_crossing "\"box_crossing_strip\":[1-9].*\"box_window_strip\":0" :fixture: --frames 5 --box-select)
# D76: picking and box selection in perspective; the wheel dollies; the view cube turns the view and
# leaves the selection alone; a preset view from the menu is animated and keeps the model on screen.
kimbim_gui_test(app_selftest_perspective
    "\"ok\":true,\"perspective\":true,\"perspective_dolly\":true,\"pick_matched\":2,\"pick_missed\":0" :fixture: --frames 5 --perspective)
kimbim_gui_test(app_selftest_box_select_perspective "\"box_selected\":2,.*\"ok\":true,\"perspective\":true" :fixture: --frames 5 --box-select --perspective)
kimbim_gui_test(app_selftest_view_cube
    "\"cube_found_top\":true,\"cube_home\":true,\"cube_selection_kept\":true,\"cube_top\":true" :fixture: --frames 2 --cube-click)
kimbim_gui_test(app_selftest_view_front "\"view_animated\":true,\"view_ok\":true" :fixture: --frames 2 --view Front)
# Slice 14: an elevation sends only the elements it can see to the serializer (the short wall is hidden
# behind the tall one from the south, in front of it from the north).
kimbim_gui_test(app_selftest_drawing_visible_south "\"drawing_shown\":true,\"drawing_visible\":1," :occlusion: --frames 1 --open-drawing "South Elevation")
kimbim_gui_test(app_selftest_drawing_visible_north "\"drawing_shown\":true,\"drawing_visible\":2," :occlusion: --frames 1 --open-drawing "North Elevation")
# D102: the windowless snapshot server for agent tools, driven over stdin/stdout like the worker does
# (the sample house from `pixi run house`). Needs a real OpenGL context; no window is shown.
qt_add_executable(test_snapshot_server tests/test_snapshot_server.cpp)
target_link_libraries(test_snapshot_server PRIVATE Qt6::Gui Qt6::Test)
add_dependencies(test_snapshot_server kimbim-app)
add_test(NAME app_snapshot_server COMMAND test_snapshot_server)
set_tests_properties(app_snapshot_server PROPERTIES
    LABELS gui
    TIMEOUT 600
    ENVIRONMENT "KIMBIM_PYTHON_PATH=${PROJECT_SOURCE_DIR}/python;KIMBIM_APP=$<TARGET_FILE:kimbim-app>;KIMBIM_HOUSE=${PROJECT_SOURCE_DIR}/build/house.ifc")
