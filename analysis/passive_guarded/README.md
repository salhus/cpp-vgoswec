# Passive-guarded capture-efficiency benchmark

Results in this folder are for the `exc_ff_pid` controller with the
**passive-safety guard ENABLED** (`passive_safe: true`).

- The guard replaces any energy-injecting command (`tau * theta_dot > 0`)
  with the dissipative damping floor `-B_ctrl * theta_dot`, so **no reactive
  power is delivered**. These numbers are a passive-bounded baseline, NOT the
  reactive/active-control performance.
- Sea state: regular waves, H = 0.05 m, CG-referenced hydro.
- eta ~ 8-13% peak; peaks track flap resonance.

Reactive controllers (ComplexConjugate / unguarded exc_ff_pid) will be
benchmarked separately in a sibling folder. See analysis/BENCHMARK_NOTES.md.
