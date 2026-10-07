# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.24)
project(KIMCAD VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets Svg Test LinguistTools)
find_package(Python3 3.12 EXACT REQUIRED COMPONENTS Interpreter Development.Embed)
find_package(OpenCASCADE REQUIRED CONFIG)  # version pinned by pixi (8.0.1 novtk, D43)
qt_standard_project_setup(I18N_SOURCE_LANGUAGE en I18N_TRANSLATED_LANGUAGES es)

# Qt Advanced Docking System (LGPL-2.1): dockable, floating and auto-hide panels and tabs (D71).
# conda-forge only packages it for Qt 5, so it is built here, pinned to a release commit.
include(FetchContent)
set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BUILD_STATIC ON CACHE BOOL "" FORCE)
set(ADS_VERSION 4.5.0 CACHE STRING "" FORCE)
FetchContent_Declare(qtads
    GIT_REPOSITORY https://github.com/githubuser0xFFFF/Qt-Advanced-Docking-System.git
    GIT_TAG 87cffe5d40307c61141c88b88c10c5e7d181d880 # 4.5.0
)
# ADS only adds its cmake/modules (Versioning) when ADS_VERSION is unset; we pin the version.
list(APPEND CMAKE_MODULE_PATH ${FETCHCONTENT_BASE_DIR}/qtads-src/cmake/modules)
FetchContent_MakeAvailable(qtads)

enable_testing()
add_subdirectory(app)
