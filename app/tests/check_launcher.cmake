# SPDX-License-Identifier: GPL-3.0-or-later
# Runs the generated desktop launcher and checks that it starts KimBim with its own environment.
if(NOT DEFINED LAUNCHER)
    message(FATAL_ERROR "LAUNCHER is not set")
endif()
file(TO_NATIVE_PATH "${LAUNCHER}" launcher)
if(WIN32)
    execute_process(COMMAND cmd /c call "${launcher}" --version
        OUTPUT_VARIABLE out ERROR_VARIABLE err RESULT_VARIABLE rc)
else()
    execute_process(COMMAND "${launcher}" --version
        OUTPUT_VARIABLE out ERROR_VARIABLE err RESULT_VARIABLE rc)
endif()
if(NOT rc EQUAL 0)
    message(FATAL_ERROR "launcher failed (${rc}): ${out}${err}")
endif()
if(NOT out MATCHES "KimBim [0-9]")
    message(FATAL_ERROR "unexpected launcher output: ${out}${err}")
endif()
message(STATUS "launcher OK: ${out}")
