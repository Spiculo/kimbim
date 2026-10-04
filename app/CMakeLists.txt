# SPDX-License-Identifier: GPL-3.0-or-later
# kimcad_core: everything except main(), so tests link the same code as the app.
qt_add_library(kimcad_core STATIC
    src/MainWindow.cpp src/MainWindow.h
    src/Translations.cpp src/Translations.h
)
target_include_directories(kimcad_core PUBLIC src)
target_link_libraries(kimcad_core PUBLIC Qt6::Widgets)
target_compile_definitions(kimcad_core PUBLIC KIMCAD_VERSION="${PROJECT_VERSION}")
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
    set_tests_properties(${name} PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endfunction()

kimcad_test(test_translations)
