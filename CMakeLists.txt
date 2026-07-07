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

# ─── CMAKE_PREFIX_PATH: re-inject from env var ───────────────────────────────
if(DEFINED ENV{CMAKE_PREFIX_PATH})
  file(TO_CMAKE_PATH "$ENV{CMAKE_PREFIX_PATH}" _env_prefixes)
  list(PREPEND CMAKE_PREFIX_PATH ${_env_prefixes})
  list(REMOVE_DUPLICATES CMAKE_PREFIX_PATH)
endif()
message(STATUS "CMAKE_PREFIX_PATH (effective): ${CMAKE_PREFIX_PATH}")

# ─── Dependencies ─────────────────────────────────────────────────────────────
find_package(SEAStack REQUIRED)
find_package(vsg QUIET)
find_package(vsgXchange QUIET)
find_package(vsgImGui QUIET)
find_package(Chrono REQUIRED)
find_package(yaml-cpp REQUIRED)
find_package(Eigen3 REQUIRED NO_MODULE)

# ─── Core library ─────────────────────────────────────────────────────────────
add_library(vgoswec_core STATIC
  src/config_loader.cpp
  src/pid_controller.cpp
)
target_include_directories(vgoswec_core PUBLIC src)
target_link_libraries(vgoswec_core
  PUBLIC SEAStack::Control
  PRIVATE yaml-cpp::yaml-cpp Eigen3::Eigen
)
target_compile_features(vgoswec_core PUBLIC cxx_std_17)

# ─── Chrono-dependent library ────────────────────────────────────────────────
add_library(vgoswec_chrono STATIC
  src/active_pto.cpp
  src/excitation_force_provider.cpp
  src/impedance.cpp
)
target_include_directories(vgoswec_chrono PUBLIC src)
target_link_libraries(vgoswec_chrono
  PUBLIC vgoswec_core
         SEAStack::PTO
         SEAStack::Hydro
         SEAStack::HydroIO
         Chrono::Chrono_core
)
target_compile_options(vgoswec_chrono PRIVATE -Wall -Wextra -Wpedantic)

# ─── Optional VSG / Chrono_vsg ───────────────────────────────────────────────
set(_demo_extra_libs "")
if(Chrono_VSG_AVAILABLE AND TARGET Chrono::Chrono_vsg)
  list(APPEND _demo_extra_libs Chrono::Chrono_vsg)
  message(STATUS "demo_vgoswec: VSG visualization enabled")
else()
  message(STATUS "demo_vgoswec: VSG not available — building headless-compatible demo")
endif()

# Optional explicit vsg libs (fallback hints)
if(TARGET Chrono::Chrono_vsg)
  set(_vsg_search_prefixes ${CMAKE_PREFIX_PATH})
  if(DEFINED ENV{CMAKE_PREFIX_PATH})
    file(TO_CMAKE_PATH "$ENV{CMAKE_PREFIX_PATH}" _env_pfx)
    list(APPEND _vsg_search_prefixes ${_env_pfx})
  endif()
  list(APPEND _vsg_search_prefixes /usr/local /usr)

  set(_vsg_lib_hints "")
  foreach(_p IN LISTS _vsg_search_prefixes)
    list(APPEND _vsg_lib_hints "${_p}/lib")
  endforeach()

  find_library(_VSG_LIB vsg HINTS ${_vsg_lib_hints})
  find_library(_VSGXCHANGE_LIB vsgXchange HINTS ${_vsg_lib_hints})

  if(_VSG_LIB)
    list(APPEND _demo_extra_libs ${_VSG_LIB})
  endif()
  if(_VSGXCHANGE_LIB)
    list(APPEND _demo_extra_libs ${_VSGXCHANGE_LIB})
  endif()
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
target_compile_options(demo_vgoswec PRIVATE -Wall -Wextra -Wpedantic)

# TEMP FIX: SEA-Stack guihelper is in source tree, not installed SDK include.
set(SEASTACK_SOURCE_DIR_HINT "$ENV{HOME}/SEA-Stack")
if(EXISTS "${SEASTACK_SOURCE_DIR_HINT}/apps/seastack/gui/guihelper.h")
  target_include_directories(demo_vgoswec PRIVATE
    "${SEASTACK_SOURCE_DIR_HINT}/apps/seastack"
  )
  target_compile_definitions(demo_vgoswec PRIVATE VGOSWEC_HAVE_SEASTACK_GUIHELPER=1)

  # Optional: only if your guihelper implementation needs this imported target.
  if(TARGET vsgImGui::vsgImGui)
    target_link_libraries(demo_vgoswec PRIVATE vsgImGui::vsgImGui)
  endif()

  message(STATUS "demo_vgoswec: using guihelper from SEA-Stack source tree (${SEASTACK_SOURCE_DIR_HINT})")
else()
  message(STATUS "demo_vgoswec: guihelper not found in SEA-Stack source tree; forcing headless runtime path")
endif()

# ─── Tests ────────────────────────────────────────────────────────────────────
include(CTest)
if(BUILD_TESTING)
  find_package(GTest QUIET)
  if(GTest_FOUND)
    add_executable(smoke_test tests/smoke_test.cpp)
    target_link_libraries(smoke_test
      PRIVATE vgoswec_core
              vgoswec_chrono
              GTest::GTest
              GTest::Main
    )
    add_test(NAME smoke_test COMMAND smoke_test)
  else()
    message(STATUS "GTest not found — smoke_test disabled")
  endif()
endif()
