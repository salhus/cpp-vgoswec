cmake_minimum_required(VERSION 3.21)
project(demo_vgoswec LANGUAGES CXX)

# ─── C++ standard ─────────────────────────────────────────────────────────────
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# GCC 13 workaround: broken std::format in C++20 mode
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS "14")
  add_compile_definitions(__cpp_lib_format=0)
  message(STATUS "GCC <14 detected — disabling std::format to avoid ABI bug")
endif()

# ─── Build type ───────────────────────────────────────────────────────────────
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# ─── CMAKE_PREFIX_PATH: re-inject from env var ────────────────────────────────
# CMake does NOT auto-populate CMAKE_PREFIX_PATH from the env var.
# This workaround ensures paths set by setup_env.sh are honoured.
# Adapted from salhus/Marine_Robotics_HIL_SEA-Stack/src/chrono_flap_sim/CMakeLists.txt.
if(DEFINED ENV{CMAKE_PREFIX_PATH})
  file(TO_CMAKE_PATH "$ENV{CMAKE_PREFIX_PATH}" _env_prefixes)
  list(PREPEND CMAKE_PREFIX_PATH ${_env_prefixes})
  list(REMOVE_DUPLICATES CMAKE_PREFIX_PATH)
  message(STATUS "CMAKE_PREFIX_PATH (after env re-injection): ${CMAKE_PREFIX_PATH}")
endif()

# ─── Dependencies ─────────────────────────────────────────────────────────────

# SEA-Stack must be installed and SEAStack_DIR (or CMAKE_PREFIX_PATH) set.
# See scripts/setup_env.sh and docs/DOWNSTREAM_PROJECT.md.
find_package(SEAStack REQUIRED)

# Project Chrono ≥ 10.  Chrono_DIR must point to the cmake/ subdir of the build tree.
# VSG headers/libs: find_package(vsg/vsgXchange/vsgImGui) before Chrono so that
# Chrono::Chrono_vsg's link-interface targets are already imported.
find_package(vsg       QUIET)
find_package(vsgXchange QUIET)
find_package(vsgImGui  QUIET)
find_package(Chrono REQUIRED)

# yaml-cpp (config loading)
find_package(yaml-cpp REQUIRED)

# Eigen3 (indirect dependency via SEA-Stack; explicit for impedance.cpp)
find_package(Eigen3 REQUIRED NO_MODULE)

# ─── Library targets (non-Chrono logic — usable in tests without Chrono) ──────

add_library(vgoswec_core STATIC
  src/config_loader.cpp
  src/pid_controller.cpp
)
target_include_directories(vgoswec_core PUBLIC src)
target_link_libraries(vgoswec_core
  PUBLIC  SEAStack::Control
  PRIVATE yaml-cpp::yaml-cpp
          Eigen3::Eigen
)
target_compile_features(vgoswec_core PUBLIC cxx_std_17)

# Chrono-dependent library (active PTO, excitation provider, impedance, RSDA functor)
add_library(vgoswec_chrono STATIC
  src/active_pto.cpp
  src/excitation_force_provider.cpp
  src/impedance.cpp
  src/rsda_pto_functor.cpp
)
target_include_directories(vgoswec_chrono PUBLIC src)
target_link_libraries(vgoswec_chrono
  PUBLIC  vgoswec_core
          SEAStack::Pto
          SEAStack::Hydro
          SEAStack::HydroIO
          Chrono::Chrono_core
)

# Optional VSG visualization support
set(_demo_extra_libs "")
if(Chrono_VSG_AVAILABLE AND TARGET Chrono::Chrono_vsg)
  list(APPEND _demo_extra_libs Chrono::Chrono_vsg)
  message(STATUS "demo_vgoswec: VSG visualization enabled")
else()
  message(STATUS "demo_vgoswec: VSG not found — building headless (--no-viz will be forced)")
endif()

# Re-inject VSG lib path for linker (pattern from HIL companion CMakeLists.txt)
if(TARGET Chrono::Chrono_vsg)
  set(_vsg_search_prefixes ${CMAKE_PREFIX_PATH})
  if(DEFINED ENV{CMAKE_PREFIX_PATH})
    file(TO_CMAKE_PATH "$ENV{CMAKE_PREFIX_PATH}" _env_pfx)
    list(APPEND _vsg_search_prefixes ${_env_pfx})
  endif()
  list(APPEND _vsg_search_prefixes /usr/local /usr)
  set(_vsg_lib_hints "")
  foreach(_p ${_vsg_search_prefixes})
    list(APPEND _vsg_lib_hints "${_p}/lib")
  endforeach()

  find_library(_VSG_LIB       vsg       HINTS ${_vsg_lib_hints})
  find_library(_VSGXCHANGE_LIB vsgXchange HINTS ${_vsg_lib_hints})
  if(_VSG_LIB)       list(APPEND _demo_extra_libs ${_VSG_LIB})       endif()
  if(_VSGXCHANGE_LIB) list(APPEND _demo_extra_libs ${_VSGXCHANGE_LIB}) endif()
endif()

# ─── Main executable ──────────────────────────────────────────────────────────
add_executable(demo_vgoswec src/demo_vgoswec.cpp)
target_link_libraries(demo_vgoswec
  PRIVATE vgoswec_chrono
          SEAStack::ChronoAdapter
          SEAStack::HydroIO
          ${_demo_extra_libs}
)
target_compile_features(demo_vgoswec PRIVATE cxx_std_20)

# ─── Tests ────────────────────────────────────────────────────────────────────
include(CTest)
if(BUILD_TESTING)
  find_package(GTest QUIET)
  if(NOT GTest_FOUND)
    message(STATUS "GTest not found — smoke_test will not be built")
  else()
    add_executable(smoke_test tests/smoke_test.cpp)
    target_link_libraries(smoke_test
      PRIVATE vgoswec_core
              vgoswec_chrono
              GTest::GTest
              GTest::Main
    )
    add_test(NAME smoke_test COMMAND smoke_test)
  endif()
endif()
