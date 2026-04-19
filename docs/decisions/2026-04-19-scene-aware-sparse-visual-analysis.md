# Scene-Aware Sparse Visual Analysis

## Status

Accepted.

## Context

Full-frame OpenNSFW2 scanning improves coverage but is too expensive on older
CPU-only machines. For 3-5 minute videos, dense per-frame scoring can dominate
runtime and trigger long timeouts.

We still need high recall for risky windows, especially around scene changes,
without blindly skipping content.

## Decision

Default visual scanning to `scene_aware_sparse`.

Strategy:

- Run a coarse broad pass with OpenNSFW2 using sparse global stride.
- Add representative frame coverage per scene (boundary + midpoint + long-scene
  stride samples).
- Build suspicious windows from coarse scores.
- Run dense local rescans only in suspicious windows.
- Merge and calibrate scores, then debounce into visual events.

Keep `full_video_every_frame` as an explicit fallback mode.

## Consequences

- Visual scan cost drops substantially on CPU-only systems while preserving
  targeted recall through dense local fallback.
- Strict quality mode now treats scene-aware sparse visual coverage as valid
  visual instrumentation (rather than disabled).
- Config surface grows with sparse/dense strategy knobs, but defaults are tuned
  for MVP practicality on non-GPU hardware.
