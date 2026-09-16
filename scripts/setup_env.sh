#!/usr/bin/env bash
# scripts/setup_env.sh
#
# Source this file (do NOT execute it) to populate the env vars needed to
# build and run cpp-vgoswec against locally-built Chrono, SEA-Stack and VSG.
#
# Usage:
#   source scripts/setup_env.sh           # uses default paths under $HOME
#   CHRONO_ROOT=/opt/chrono/install \
#   SEASTACK_INSTALL=/opt/seastack/install \
#   VSG_INSTALL=/opt/vsg \
#     source scripts/setup_env.sh         # override any path
#
# Safe to source multiple times; will NOT duplicate path entries.
#
# Kept in sync with salhus/Marine_Robotics_HIL_SEA-Stack/scripts/setup_env.sh

# ─── Defaults (override by exporting before sourcing) ─────────────────────────
# CHRONO_ROOT may be either an install tree (lib/cmake/Chrono) or a build
# tree (cmake). Both layouts are detected below.
: "${CHRONO_ROOT:=$HOME/project-chrono_v10/install}"
: "${SEASTACK_INSTALL:=$HOME/SEA-Stack/install}"
: "${VSG_INSTALL:=$HOME/Packages/vsg}"
: "${ROS_DISTRO:=jazzy}"

# Back-compat: honour a legacy CHRONO_BUILD override if the caller still sets it.
if [ -n "${CHRONO_BUILD:-}" ] && [ -d "$CHRONO_BUILD" ]; then
  CHRONO_ROOT="$CHRONO_BUILD"
fi

# ─── Chrono ───────────────────────────────────────────────────────────────────
# Install trees put the config under lib/cmake/Chrono; build trees use cmake/.
if [ -d "$CHRONO_ROOT/lib/cmake/Chrono" ]; then
  export Chrono_DIR="$CHRONO_ROOT/lib/cmake/Chrono"
  _chrono_layout="install"
elif [ -d "$CHRONO_ROOT/cmake" ]; then
  export Chrono_DIR="$CHRONO_ROOT/cmake"
  _chrono_layout="build"
else
  echo "[setup_env] WARN: no Chrono cmake dir under $CHRONO_ROOT" >&2
  echo "[setup_env]       Looked for lib/cmake/Chrono (install) and cmake (build)." >&2
  _chrono_layout="none"
fi

# Chrono runtime data (meshes, shaders, fonts). Only present in install trees
# and in the source tree; the build tree points back at the source data dir.
if [ -d "$CHRONO_ROOT/share/chrono/data" ]; then
  export CHRONO_DATA_DIR="$CHRONO_ROOT/share/chrono/data/"
elif [ -d "$CHRONO_ROOT/../data" ]; then
  export CHRONO_DATA_DIR="$(cd "$CHRONO_ROOT/../data" && pwd)/"
else
  echo "[setup_env] WARN: Chrono data dir not found under $CHRONO_ROOT" >&2
fi

# VSG resolves assets like "vsg/fonts/OpenSans-Bold.vsgb" relative to this root,
# so VSG_FILE_PATH must be the data dir itself, NOT data/vsg. Pointing it one
# level too deep makes font lookup fail and the renderer segfault on frame 1.
if [ -n "${CHRONO_DATA_DIR:-}" ] && [ -d "${CHRONO_DATA_DIR}vsg" ]; then
  export VSG_FILE_PATH="${CHRONO_DATA_DIR%/}"
fi

# ─── SEA-Stack (use install tree, NOT build tree — see docs) ──────────────────
if [ -d "$SEASTACK_INSTALL/lib/cmake/SEAStack" ]; then
  export SEAStack_DIR="$SEASTACK_INSTALL/lib/cmake/SEAStack"
else
  echo "[setup_env] WARN: SEA-Stack not installed at $SEASTACK_INSTALL." >&2
  echo "[setup_env]       Run:  cmake --install \$HOME/SEA-Stack/build --prefix $SEASTACK_INSTALL" >&2
fi

# ─── CMAKE_PREFIX_PATH ────────────────────────────────────────────────────────
# Helper: prepend $1 to a colon-separated var iff not already present.
_prepend_path_var() {
  local _var="$1" _dir="$2" _cur
  [ -d "$_dir" ] || return 0
  eval "_cur=\${$_var:-}"
  case ":${_cur}:" in
    *":$_dir:"*) ;;  # already present, no-op
    *)           export "$_var=$_dir${_cur:+:$_cur}" ;;
  esac
}

_prepend_path_var CMAKE_PREFIX_PATH "$SEASTACK_INSTALL"
_prepend_path_var CMAKE_PREFIX_PATH "$CHRONO_ROOT"
_prepend_path_var CMAKE_PREFIX_PATH "$VSG_INSTALL"

# ─── LD_LIBRARY_PATH ──────────────────────────────────────────────────────────
# Needed at runtime for Chrono/VSG, and by SEA-Stack's install-time dependency
# scan for liburdfdom_model.so / libChrono_core.so.
_prepend_path_var LD_LIBRARY_PATH "/opt/ros/$ROS_DISTRO/lib"
_prepend_path_var LD_LIBRARY_PATH "/opt/ros/$ROS_DISTRO/lib/x86_64-linux-gnu"
_prepend_path_var LD_LIBRARY_PATH "/usr/lib/x86_64-linux-gnu/hdf5/serial"
_prepend_path_var LD_LIBRARY_PATH "$VSG_INSTALL/lib"
_prepend_path_var LD_LIBRARY_PATH "$CHRONO_ROOT/lib"
_prepend_path_var LD_LIBRARY_PATH "$SEASTACK_INSTALL/lib"

unset -f _prepend_path_var

# ─── Sanity checks ────────────────────────────────────────────────────────────
# A stray /usr/local yaml-cpp alongside Chrono's bundled copy makes
# `cmake --install` fail with "Multiple conflicting paths found".
if [ -e /usr/local/lib/libyaml-cpp.so.0.8 ]; then
  echo "[setup_env] WARN: /usr/local/lib/libyaml-cpp.so.0.8 exists and may conflict" >&2
  echo "[setup_env]       with Chrono's bundled copy during 'cmake --install'." >&2
  echo "[setup_env]       Note: renaming it in place is not enough — ldconfig re-creates" >&2
  echo "[setup_env]       the SONAME symlink. Move the file out of /usr/local/lib." >&2
fi

if [ -n "${VSG_FILE_PATH:-}" ] && [ ! -f "$VSG_FILE_PATH/vsg/fonts/OpenSans-Bold.vsgb" ]; then
  echo "[setup_env] WARN: VSG font not found under $VSG_FILE_PATH/vsg/fonts/" >&2
  echo "[setup_env]       Visualization may crash on startup." >&2
fi

# ─── Report ───────────────────────────────────────────────────────────────────
echo "[setup_env] Chrono_DIR        = ${Chrono_DIR:-<unset>} (${_chrono_layout} tree)"
echo "[setup_env] CHRONO_DATA_DIR   = ${CHRONO_DATA_DIR:-<unset>}"
echo "[setup_env] VSG_FILE_PATH     = ${VSG_FILE_PATH:-<unset>}"
echo "[setup_env] SEAStack_DIR      = ${SEAStack_DIR:-<unset>}"
echo "[setup_env] CMAKE_PREFIX_PATH = ${CMAKE_PREFIX_PATH:-<unset>}"
echo "[setup_env] LD_LIBRARY_PATH   = ${LD_LIBRARY_PATH:-<unset>}"

unset _chrono_layout
