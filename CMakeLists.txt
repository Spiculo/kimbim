# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.24)
project(KIMCAD VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Widgets Svg Test LinguistTools)
find_package(Python3 3.12 EXACT REQUIRED COMPONENTS Interpreter Development.Embed)
find_package(OpenCASCADE REQUIRED CONFIG)  # version pinned by pixi (8.0.1 novtk, D43)
qt_standard_project_setup(I18N_SOURCE_LANGUAGE en I18N_TRANSLATED_LANGUAGES es)

enable_testing()
add_subdirectory(app)
