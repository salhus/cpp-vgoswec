cmake_minimum_required(VERSION 3.21)
project(demo_vgoswec LANGUAGES CXX)

# ─── C++ standard ─────────────────────────────────────────────────────────────
# Must match the standard SEA-Stack was built with (it uses cxx_std_17).
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# NOTE: Do NOT define libstdc++ feature-test macros (e.g. __cpp_lib_format)
# here. A previous revision set `add_compile_definitions(__cpp_lib_format=0)`
# globally, which desynchronized standard-library headers between this project
# and the prebuilt SEA-Stack libraries. That is an ODR violation: it links
# cleanly, then corrupts object layout at runtime.
# This project does not use std::format at all.

# ─── Build type ───────────────────────────────────────────────────────────────
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
  set_property(CACHE CMAKE_BUILD_TYPE PROPERTY
    STRINGS Debug Release RelWithDebInfo MinSizeRel)
endif()

# ─── CMAKE_PREFIX_PATH: re-inject from environment ───────────────────────────
# Populated by `chrono10 && seastack` (see ~/env/*.sh).
if(DEFINED ENV{CMAKE_PREFIX_PATH})
  file(TO_CMAKE_PATH "$ENV{CMAKE_PREFIX_PATH}" _env_prefixes)
  list(PREPEND CMAKE_PREFIX_PATH ${_env_prefixes})
  list(REMOVE_DUPLICATES CMAKE_PREFIX_PATH)
endif()
message(STATUS "CMAKE_PREFIX_PATH (effective): ${CMAKE_PREFIX_PATH}")

# ─── Dependencies ─────────────────────────────────────────────────────────────
find_package(SEAStack REQUIRED)
find_package(Chrono   REQUIRED)
find_package(yaml-cpp REQUIRED)
find_package(Eigen3   REQUIRED NO_MODULE)

find_package(vsg          QUIET)
find_package(vsgXchange   QUIET)
find_package(vsgImGui     QUIET)

# VSG exports only Debug and Release imported configurations. A RelWithDebInfo
# (or MinSizeRel) build matches neither and silently falls back to DEBUG,
# selecting libvsg_d.so while Chrono::Chrono_vsg carries the Release set —
# two copies of VSG in one process, crashing in vsg::Buffer::vk().
foreach(_vsg_tgt vsg::vsg vsgXchange::vsgXchange vsgImGui::vsgImGui)
  if(TARGET ${_vsg_tgt})
    set_target_properties(${_vsg_tgt} PROPERTIES
      MAP_IMPORTED_CONFIG_RELWITHDEBINFO Release
      MAP_IMPORTED_CONFIG_MINSIZEREL     Release
      MAP_IMPORTED_CONFIG_NOCONFIG       Release)
  endif()
endforeach()

message(STATUS "Chrono prefix: ${CHRONO_PACKAGE_PREFIX_DIR}")

# ─── Common compile settings ─────────────────────────────────────────────────
add_library(vgoswec_warnings INTERFACE)
target_compile_options(vgoswec_warnings INTERFACE -Wall -Wextra -Wpedantic)

# ─── Core library (Chrono-free) ──────────────────────────────────────────────
add_library(vgoswec_core STATIC
  src/config_loader.cpp
  src/pid_controller.cpp
)
target_include_directories(vgoswec_core PUBLIC src)
target_compile_features(vgoswec_core PUBLIC cxx_std_17)
target_link_libraries(vgoswec_core
  PUBLIC  SEAStack::Control
  PRIVATE yaml-cpp::yaml-cpp Eigen3::Eigen vgoswec_warnings
)

# ─── Chrono-dependent library ────────────────────────────────────────────────
add_library(vgoswec_chrono STATIC
  src/active_pto.cpp
  src/excitation_force_provider.cpp
  src/impedance.cpp
  src/rsda_pto_functor.cpp
)
target_include_directories(vgoswec_chrono PUBLIC src)
target_compile_features(vgoswec_chrono PUBLIC cxx_std_17)
target_link_libraries(vgoswec_chrono
  PUBLIC  vgoswec_core
          SEAStack::PTO
          SEAStack::Hydro
          SEAStack::HydroIO
          Chrono::Chrono_core
  PRIVATE vgoswec_warnings
)

# ─── SEA-Stack app library (not exported by SEAStackConfig) ──────────────────
# `seastack_app_lib` backs the single-run/report paths but is not part of the
# installed SEAStack:: export set, so it is located by hand. It MUST come from
# the same SEA-Stack build as the SEAStack:: targets above.
set(SEASTACK_SOURCE_DIR "$ENV{HOME}/SEA-Stack"
    CACHE PATH "SEA-Stack source tree (for app_lib and guihelper headers)")

find_library(SEASTACK_APP_LIB
  NAMES seastack_app_lib
  HINTS "${SEASTACK_SOURCE_DIR}/build/lib/Release"
        "${SEASTACK_SOURCE_DIR}/build/lib"
        "${SEASTACK_SOURCE_DIR}/install/lib"
  NO_DEFAULT_PATH
)

if(SEASTACK_APP_LIB)
  if(NOT TARGET SEAStack::app_lib)
    add_library(SEAStack::app_lib STATIC IMPORTED)
  endif()
  set_target_properties(SEAStack::app_lib PROPERTIES
    IMPORTED_LOCATION "${SEASTACK_APP_LIB}")
  message(STATUS "seastack_app_lib: ${SEASTACK_APP_LIB}")
else()
  message(WARNING
    "seastack_app_lib not found under ${SEASTACK_SOURCE_DIR} — "
    "building headless-safe path without it.")
endif()

# ─── Main executable ──────────────────────────────────────────────────────────
add_executable(demo_vgoswec src/demo_vgoswec.cpp)
target_compile_features(demo_vgoswec PRIVATE cxx_std_17)
target_link_libraries(demo_vgoswec
  PRIVATE vgoswec_chrono
          SEAStack::ChronoAdapter
          SEAStack::HydroIO
          vgoswec_warnings
)

if(SEASTACK_APP_LIB)
  target_link_libraries(demo_vgoswec PRIVATE SEAStack::app_lib)
endif()

# Chrono::Chrono_vsg is linked AFTER app_lib: static archives resolve in
# left-to-right order, and app_lib references Chrono VSG and ImGui symbols.
#
# The VSG targets themselves (vsg::vsg, vsgXchange, vsgImGui) are deliberately
# NOT linked here. Chrono::Chrono_vsg already propagates them in the
# configuration Chrono was built against; linking them again pulled in a second,
# debug-config copy of VSG alongside Chrono's release copy.
if(Chrono_VSG_AVAILABLE AND TARGET Chrono::Chrono_vsg)
  target_link_libraries(demo_vgoswec PRIVATE Chrono::Chrono_vsg)
  target_compile_definitions(demo_vgoswec PRIVATE VGOSWEC_HAVE_CHRONO_VSG=1)
  message(STATUS "VSG visualization: enabled")
else()
  message(STATUS "VSG visualization: disabled (headless build)")
endif()

if(EXISTS "${SEASTACK_SOURCE_DIR}/apps/seastack/gui/guihelper.h")
  target_include_directories(demo_vgoswec PRIVATE "${SEASTACK_SOURCE_DIR}/apps/seastack")
  target_compile_definitions(demo_vgoswec PRIVATE VGOSWEC_HAVE_SEASTACK_GUIHELPER=1)
  message(STATUS "guihelper: ${SEASTACK_SOURCE_DIR}/apps/seastack")
else()
  message(STATUS "guihelper: not found — forcing headless runtime path")
endif()

# ─── Tests ────────────────────────────────────────────────────────────────────
include(CTest)
if(BUILD_TESTING)
  find_package(GTest QUIET)
  if(GTest_FOUND)
    add_executable(smoke_test tests/smoke_test.cpp)
    target_link_libraries(smoke_test
      PRIVATE vgoswec_core vgoswec_chrono GTest::gtest GTest::gtest_main)
    add_test(NAME smoke_test COMMAND smoke_test)
  else()
    message(STATUS "GTest not found — smoke_test disabled")
  endif()
endif()
