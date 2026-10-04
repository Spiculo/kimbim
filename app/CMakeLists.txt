# SPDX-License-Identifier: GPL-3.0-or-later
# kimcad_core: everything except main(), so tests link the same code as the app.
qt_add_library(kimcad_core STATIC
    src/MainWindow.cpp src/MainWindow.h
    src/Translations.cpp src/Translations.h
    src/PythonEngine.cpp src/PythonEngine.h
    src/MeshChunk.cpp src/MeshChunk.h
    src/ElementBatch.cpp src/ElementBatch.h
    src/Viewport.cpp src/Viewport.h
    src/SelfTest.cpp src/SelfTest.h
    src/ModelTreePanel.cpp src/ModelTreePanel.h
    src/PropertiesPanel.cpp src/PropertiesPanel.h
    src/ModelLoader.cpp src/ModelLoader.h
)
target_include_directories(kimcad_core PUBLIC src)
target_link_libraries(kimcad_core PUBLIC Qt6::Widgets Python3::Python
    TKernel TKMath TKService TKV3d TKOpenGl TKBRep TKG3d)
target_include_directories(kimcad_core PUBLIC ${OpenCASCADE_INCLUDE_DIR})
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
