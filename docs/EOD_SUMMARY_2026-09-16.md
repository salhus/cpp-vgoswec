# End of Day — 2026-09-16

Infrastructure day. No simulation results changed; the work was on the **build
environment and toolchain switching**, which had two silent-failure modes that
could have produced wrong results without any error message.

## 1. What changed

### `~/env/*.sh` toolchain scripts (outside this repo)

The `chrono10` / `chrono-dev` / `chrono-main` / `seastack` aliases were rewritten
around a new shared helper, `~/env/_chrono_common.sh`. See `~/TOOLCHAIN.md` for
the user-facing workflow.

Fixes, in order of severity:

- **Flavor switching did not unset the previous Chrono.** `chrono10 && chrono-dev`
  left *both* `project-chrono_v10/install/lib` and `project-chrono_sh/build/lib`
  on `LD_LIBRARY_PATH`, and the dynamic loader silently took whichever came
  first. Same class of bug as the VSG two-copies-in-one-process failure. Now
  `_chrono_reset` strips all known Chrono prefixes on every switch.
- **SEA-Stack env survived a Chrono switch.** After `chrono10 && seastack && chrono-dev`,
  `SEAStack_DIR` still pointed at a SEA-Stack built against the v10 ABI, now
  paired with the dev Chrono — exactly the mismatch `seastack.sh` warns about,
  except the warning only fires when you run `seastack`, not when you switch out
  from under it. `_chrono_reset` now clears SEA-Stack too, with a visible NOTE.
- **A failed helper load latched permanently.** The old guard set
  `_CHRONO_COMMON_LOADED=1` on the line *after* the `source`, unconditionally —
  so if the source failed, every later attempt skipped loading entirely. Symptom
  observed: `Chrono_DIR` set correctly but `LD_LIBRARY_PATH` missing every Chrono
  entry, with no error on subsequent invocations. Now the flag is set only on
  success, and a failed load aborts.
- `VSG_FILE_PATH` trailing slash stripped; added a font-existence warning so the
  renderer's frame-1 segfault is diagnosed at source time instead of run time.
- `CXXFLAGS` no longer accumulates duplicate `-march=native` on re-source.
- `chrono-dev.sh` had been overwritten with `chrono10.sh`'s contents — it printed
  `[chrono] v10` and re-applied the v10 paths. Restored.
- Removed stale `~/env/*.sh~` editor backups.

### Verification

Both paths now build and run clean from a fresh shell:

- `source scripts/setup_env.sh` (repo-local, no `~/env/` needed)
- `chrono10 && seastack` (toolchain aliases alone)

A diff of the two showed only cosmetic differences: `CMAKE_PREFIX_PATH` ordering,
a vestigial `project-chrono_v10/build/lib` entry in the alias path, and the
`VSG_FILE_PATH` trailing slash. **The aliases alone are sufficient** — configure,
build, and a full `vgoswec_0_exc_ff_pid` run all succeed without `setup_env.sh`.

## 2. Open questions raised today

### `CH_USE_SIMD` — documentation contradicted reality

Three places claimed SEA-Stack requires Chrono built with `CH_USE_SIMD=OFF`
(`.bashrc` alias comment, `chrono10.sh` header, `seastack.sh` header, and
`README.md` prerequisites). **The working v10 build has SIMD ON** with
`-march=native`, and the entire stack builds and runs.

The comments have been corrected to match observed reality. If the `OFF`
requirement was real and simply hasn't bitten yet, these files are now
confidently wrong — this needs confirming against SEA-Stack's own build config.

This also plausibly explains the last-bit floating-point drift seen in the VGM-0
results CSV: `-march=native` with SIMD enabled is exactly the codegen difference
that moves a ULP.

### `scripts/setup_env.sh` bypasses `_chrono_reset`

The repo script sets the same variables independently of the aliases. Running
`chrono-dev` and then `source scripts/setup_env.sh` yields v10 paths *without*
the reset having cleared dev. Worth having `setup_env.sh` warn on a
`CHRONO_FLAVOR` mismatch.

### `CMP0144` now fires twice

The rewrite exports `CHRONO_ROOT` where the old `chrono10.sh` only set
`CHRONO_PREFIX`, so CMake now warns about both `SEASTACK_ROOT` and `CHRONO_ROOT`.
Harmless under the current policy (CMake ignores them), but if `CMP0144` is ever
set to `NEW`, `find_package` would start honoring env vars pointing at install
trees.

## 3. Pre-existing issues surfaced by today's clean run

Not introduced today, but visible in the verification output:

- **`[impedance] INFO: legacy A55-match rho=...` prints on repeated hydro
  lookups.** It is a static property of the H5 file, not per-frequency — the
  de-normalization path re-resolves `rho` on every table lookup instead of once
  at load. Log noise burying real output.
- **`<-- VGM45 resonance` marker printed during a VGM-0 run.** The annotation at
  ω = 1.84 rad/s is hardcoded for the 45° flap and printed regardless of config.
  Either a stale label or the sweep is annotating the wrong body.
- **`Chrono libraries not found for the debug configuration`** — benign for
  `RelWithDebInfo`, but a `-DCMAKE_BUILD_TYPE=Debug` build would fail to link.
- **`libyaml-cpp.so.0.8` runtime-path conflict** between `/usr/lib/x86_64-linux-gnu`
  and Chrono's bundled copy, warned at `add_executable` for both targets.

## 4. Repo hygiene

- `analysis/passive/` exists on disk but is gitignored and untracked — superseded
  by `analysis/passive_guarded/`. Safe to delete.
- `analysis/passive_vs_optpassive/figures/` is an output path written by
  `scripts/passive_vs_optpassive_sweep.py` but exists neither on disk nor in git.
  Dead path; the tree was superseded by `analysis/three_regime/`.
- `check.md` at repo root is a single line of LaTeX (the ff+PID torque law).
  Belongs in `docs/CONTROLLERS.md`.

The `analysis/` tree itself is structurally sound — a 3-source / 3-derived DAG,
not the six competing conventions it looks like at a glance:

| Tree | Role | Producer |
|------|------|----------|
| `analysis/cc/` | source | `cc_capture_efficiency_sweep.py` |
| `analysis/opt_passive/` | source | `passive_vs_optpassive_sweep.py` |
| `analysis/passive_guarded/` | source | `capture_efficiency_sweep.py` |
| `analysis/comparison/` | derived | `cc_vs_ffpid_comparison.py` |
| `analysis/three_regime/` | derived | `three_regime_comparison.py` (reads all three sources) |
| `analysis/figures/` | derived | `plot_kpkd_surface.py` (from top-level `kpkd_sweep_VGM*.csv`) |

Renaming `passive_guarded` to something describing what it actually is (tuned
`exc_ff_pid`) would improve clarity but breaks four scripts, three FINDINGS docs,
and every reproduce command in `docs/REPRODUCTION.md`. Not worth it.

## 5. Next

Unchanged from 2026-07-11: **#50** (literature positioning) remains the critical
path. Today's work was environment maintenance, not progress on that gate.
