# SPDX-License-Identifier: GPL-3.0-or-later
# kimcad_core: everything except main(), so tests link the same code as the app.
qt_add_library(kimcad_core STATIC
    src/MainWindow.cpp src/MainWindow.h
    src/Translations.cpp src/Translations.h
    src/PythonEngine.cpp src/PythonEngine.h
    src/MeshChunk.cpp src/MeshChunk.h
    src/ElementBatch.cpp src/ElementBatch.h
    src/Viewport.cpp src/Viewport.h
    src/ViewCube.cpp src/ViewCube.h
    src/SelfTest.cpp src/SelfTest.h
    src/ModelTreePanel.cpp src/ModelTreePanel.h
    src/PropertiesPanel.cpp src/PropertiesPanel.h
    src/LevelsBar.cpp src/LevelsBar.h
    src/HistoryPanel.cpp src/HistoryPanel.h
    src/CombineDialog.cpp src/CombineDialog.h
    src/LayersPanel.cpp src/LayersPanel.h
    src/Icons.cpp src/Icons.h
    src/Snapper.cpp src/Snapper.h
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
    src/DraftTool.cpp src/DraftTool.h src/DraftTools.cpp
    src/ModelLoader.cpp src/ModelLoader.h
    src/Cuts.cpp src/Cuts.h
    src/DrawingsPanel.cpp src/DrawingsPanel.h
    src/DrawingView.cpp src/DrawingView.h
    src/SheetExport.cpp src/SheetExport.h
    src/SheetsPanel.cpp src/SheetsPanel.h
    src/SchedulesDialog.cpp src/SchedulesDialog.h
    src/DockLayout.cpp src/DockLayout.h
    src/Scene.cpp src/Scene.h
    src/ViewHost.cpp src/ViewHost.h
    src/ToolPalette.cpp src/ToolPalette.h
    src/ToolOptionsBar.cpp src/ToolOptionsBar.h
    src/StatusStrip.cpp src/StatusStrip.h
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
)
target_include_directories(kimcad_core PUBLIC src)
# Element icons (owner feedback: objects need an icon and a hint on hover).
file(GLOB KIMCAD_ICONS RELATIVE ${CMAKE_CURRENT_SOURCE_DIR} resources/icons/*.svg)
qt_add_resources(kimcad_core "kimcad_icons" PREFIX "/icons" BASE resources/icons FILES ${KIMCAD_ICONS})
target_link_libraries(kimcad_core PUBLIC Qt6::Widgets Qt6::Svg Python3::Python
    TKernel TKMath TKService TKV3d TKOpenGl TKBRep TKG3d ads::qtadvanceddocking-qt6)
target_include_directories(kimcad_core PUBLIC ${OpenCASCADE_INCLUDE_DIR})
if(WIN32)
    target_link_libraries(kimcad_core PUBLIC dwmapi) # D75: the custom title bar keeps the native frame
endif()
target_compile_definitions(kimcad_core PUBLIC KIMCAD_VERSION="${PROJECT_VERSION}" _USE_MATH_DEFINES)
qt_add_translations(kimcad_core
    TS_FILES translations/kimcad_en.ts translations/kimcad_es.ts
    RESOURCE_PREFIX /i18n
)

qt_add_executable(kimcad-app src/main.cpp)
target_link_libraries(kimcad-app PRIVATE kimcad_core)

function(kimcad_test name)
    qt_add_executable(${name} tests/${name}.cpp)
    target_link_libraries(${name} PRIVATE kimcad_core Qt6::Test)
    add_test(NAME ${name} COMMAND ${name})
    set_tests_properties(${name} PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen;KIMCAD_PYTHON_PATH=${PROJECT_SOURCE_DIR}/python")
endfunction()

kimcad_test(test_translations)
kimcad_test(test_python_engine)
kimcad_test(test_mesh_chunk)
kimcad_test(test_element_batch)
kimcad_test(test_model_tree)
kimcad_test(test_visibility)
kimcad_test(test_main_window)
kimcad_test(test_cuts)
kimcad_test(test_model_loader)
kimcad_test(test_navigation)
kimcad_test(test_selection)
kimcad_test(test_selection_tools)
kimcad_test(test_checks)
kimcad_test(test_console)
kimcad_test(test_properties_panel)
kimcad_test(test_levels_bar)
kimcad_test(test_snapper)
kimcad_test(test_wall_tool)
kimcad_test(test_polygon_tool)
kimcad_test(test_host_tool)
kimcad_test(test_two_point_tool)
kimcad_test(test_draft_tool)
kimcad_test(test_measure_and_levels)
kimcad_test(test_rotate_tool)
kimcad_test(test_grip_tool)
kimcad_test(test_modify_tool)
kimcad_test(test_dock_layout)
kimcad_test(test_scene)
kimcad_test(test_tool_palette)
kimcad_test(test_preferences)
kimcad_test(test_graphics)
kimcad_test(test_dxf_export)

# GUI self-tests: need a real OpenGL window (GPU, or Mesa on the Linux CI runner). Label "gui".
file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/broken.ifc "ISO-10303-21;
this is not IFC
")
function(kimcad_gui_test name pass_regex)
    add_test(NAME ${name} COMMAND kimcad-app --self-test ${ARGN})
    set_tests_properties(${name} PROPERTIES
        LABELS gui
        ENVIRONMENT "KIMCAD_PYTHON_PATH=${PROJECT_SOURCE_DIR}/python"
        PASS_REGULAR_EXPRESSION "${pass_regex}")
endfunction()
kimcad_gui_test(app_selftest_fixture
    "\"ok\":true.*\"pick_matched\":2.*\"pick_missed\":0.*\"tree_follows_selection\":true" :fixture: --frames 5)
kimcad_gui_test(app_selftest_broken_file "\"ok\":false" ${CMAKE_CURRENT_BINARY_DIR}/broken.ifc)
kimcad_gui_test(app_selftest_quit_during_load "\"ok\":true,\"quit_during_load\":true" :fixture: --quit-during-load --chunk 1)
kimcad_gui_test(app_selftest_pop_out "\"ok\":true.*\"pop_out\":true" :fixture: --frames 2 --pop-out)
# D71: a plan tab open while the window closes: no OpenGL errors from views torn down after their window.
kimcad_gui_test(app_selftest_plan_tab_exit "\"ok\":true" :fixture: --frames 2 --bench-edit --plan-tab)
set_tests_properties(app_selftest_plan_tab_exit PROPERTIES FAIL_REGULAR_EXPRESSION "MakeCurrent\(\) has failed|Type: Error")
kimcad_gui_test(app_selftest_plan_cut "\"ok\":true.*\"planes\":1" :fixture: --frames 5 --plan-cut 1.5)
kimcad_gui_test(app_selftest_draw_walls "\"elements\":4,\"joins\":4,\"ok\":true,\"walls\":4" :new: --draw-walls "0,0 5,0 5,4 0,4 0,0")
kimcad_gui_test(app_selftest_house "\"beams\":1,\"columns\":1,\"doors\":1,\"elements\":9,\"grid\":4,\"joins\":4,\"ok\":true,\"openings\":2,\"slabs\":1,\"walls\":4,\"windows\":1" :new: --house)
kimcad_gui_test(app_selftest_box_select_visible "\"box_selected\":1,.*\"ok\":true" :occlusion: --frames 5 --box-select)
kimcad_gui_test(app_selftest_box_select_through "\"box_selected\":2,.*\"ok\":true" :occlusion: --frames 5 --box-select --select-through)
kimcad_gui_test(app_selftest_box_select "\"box_selected\":2.*\"ok\":true.*\"tree_selected\":2" :fixture: --frames 5 --box-select)
# D78: right to left is a crossing box, left to right a window box.
kimcad_gui_test(app_selftest_box_crossing "\"box_crossing_strip\":[1-9].*\"box_window_strip\":0" :fixture: --frames 5 --box-select)
# D76: picking and box selection in perspective; the wheel dollies; the view cube turns the view and
# leaves the selection alone; a preset view from the menu is animated and keeps the model on screen.
kimcad_gui_test(app_selftest_perspective
    "\"ok\":true,\"perspective\":true,\"perspective_dolly\":true,\"pick_matched\":2,\"pick_missed\":0" :fixture: --frames 5 --perspective)
kimcad_gui_test(app_selftest_box_select_perspective "\"box_selected\":2,.*\"ok\":true,\"perspective\":true" :fixture: --frames 5 --box-select --perspective)
kimcad_gui_test(app_selftest_view_cube
    "\"cube_found_top\":true,\"cube_home\":true,\"cube_selection_kept\":true,\"cube_top\":true" :fixture: --frames 2 --cube-click)
kimcad_gui_test(app_selftest_view_front "\"view_animated\":true,\"view_ok\":true" :fixture: --frames 2 --view Front)
# Slice 14: an elevation sends only the elements it can see to the serializer (the short wall is hidden
# behind the tall one from the south, in front of it from the north).
kimcad_gui_test(app_selftest_drawing_visible_south "\"drawing_shown\":true,\"drawing_visible\":1," :occlusion: --frames 1 --open-drawing "South Elevation")
kimcad_gui_test(app_selftest_drawing_visible_north "\"drawing_shown\":true,\"drawing_visible\":2," :occlusion: --frames 1 --open-drawing "North Elevation")
