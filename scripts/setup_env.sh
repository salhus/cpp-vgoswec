#!/usr/bin/env bash
# scripts/setup_env.sh
#
# Source this file (do NOT execute it) to populate the env vars needed to
# build cpp-vgoswec against locally-built Chrono and SEA-Stack.
#
# Usage:
#   source scripts/setup_env.sh            # uses default paths under $HOME
#   CHRONO_BUILD=/opt/chrono/build \
#   SEASTACK_INSTALL=/opt/seastack/install \
#   VSG_INSTALL=/opt/vsg \
#     source scripts/setup_env.sh          # override any path
#
# Safe to source multiple times; will NOT duplicate path entries.
#
# Adapted from salhus/Marine_Robotics_HIL_SEA-Stack/scripts/setup_env.sh

# ─── Defaults (override by exporting before sourcing) ─────────────────────────
: "${CHRONO_BUILD:=$HOME/project-chrono/build}"
: "${SEASTACK_INSTALL:=$HOME/SEA-Stack/install}"
: "${VSG_INSTALL:=$HOME/Packages/vsg}"

# ─── Chrono ───────────────────────────────────────────────────────────────────
if [ -d "$CHRONO_BUILD/cmake" ]; then
  export Chrono_DIR="$CHRONO_BUILD/cmake"
else
  echo "[setup_env] WARN: Chrono cmake dir not found at $CHRONO_BUILD/cmake" >&2
fi

# ─── SEA-Stack (use install tree, NOT build tree) ─────────────────────────────
if [ -d "$SEASTACK_INSTALL/lib/cmake/SEAStack" ]; then
  export SEAStack_DIR="$SEASTACK_INSTALL/lib/cmake/SEAStack"
else
  echo "[setup_env] WARN: SEA-Stack not installed at $SEASTACK_INSTALL." >&2
  echo "[setup_env]       Run:  cmake --install \$HOME/SEA-Stack/build --prefix $SEASTACK_INSTALL" >&2
fi

# ─── Runtime linker ───────────────────────────────────────────────────────────
if [ -d "$CHRONO_BUILD/lib" ]; then
  case ":${LD_LIBRARY_PATH:-}:" in
    *":$CHRONO_BUILD/lib:"*) ;;
    *) export LD_LIBRARY_PATH="$CHRONO_BUILD/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
  esac
fi

if [ -d "$SEASTACK_INSTALL/lib" ]; then
  case ":${LD_LIBRARY_PATH:-}:" in
    *":$SEASTACK_INSTALL/lib:"*) ;;
    *) export LD_LIBRARY_PATH="$SEASTACK_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
  esac
fi

# ─── VSG assets (needed at runtime for visualization) ─────────────────────────
if [ -d "$CHRONO_BUILD/data" ] && [ -d "$VSG_INSTALL/share" ]; then
  export VSG_FILE_PATH="$CHRONO_BUILD/data:$VSG_INSTALL/share/vsgExamples"
fi

# ─── CMAKE_PREFIX_PATH ────────────────────────────────────────────────────────
# Helper: prepend $1 to CMAKE_PREFIX_PATH iff not already present.
_prepend_prefix() {
  case ":${CMAKE_PREFIX_PATH:-}:" in
    *":$1:"*) ;;
    *)       export CMAKE_PREFIX_PATH="$1${CMAKE_PREFIX_PATH:+:$CMAKE_PREFIX_PATH}" ;;
  esac
}

[ -d "$SEASTACK_INSTALL" ]      && _prepend_prefix "$SEASTACK_INSTALL"
[ -d "$CHRONO_BUILD/cmake" ]    && _prepend_prefix "$CHRONO_BUILD/cmake"
[ -d "$VSG_INSTALL" ]           && _prepend_prefix "$VSG_INSTALL"

unset -f _prepend_prefix

# ─── CH_USE_SIMD must be OFF (SEA-Stack requirement) ──────────────────────────
# Reminder: rebuild Chrono with -DCH_USE_SIMD=OFF if you haven't already.
# See docs: https://github.com/salhus/Marine_Robotics_HIL_SEA-Stack/docs/local-chrono-build.md

# ─── Report ───────────────────────────────────────────────────────────────────
echo "[setup_env] Chrono_DIR        = ${Chrono_DIR:-<unset>}"
echo "[setup_env] SEAStack_DIR      = ${SEAStack_DIR:-<unset>}"
echo "[setup_env] LD_LIBRARY_PATH   = ${LD_LIBRARY_PATH:-<unset>}"
echo "[setup_env] CMAKE_PREFIX_PATH = ${CMAKE_PREFIX_PATH:-<unset>}"
