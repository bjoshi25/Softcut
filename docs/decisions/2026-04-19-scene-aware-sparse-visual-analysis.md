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

## Operational Validation (2026-04-20)

Latest degraded-profile run on CPU-only hardware produced:

- `quality_flags=[]`
- `coarse_clip_extract_failed=false`
- `scanned_frames=239`
- `visual_scoring_sec=145.4124`
- `coverage_summary.total_scenes=121`
- `coverage_summary.sampled_scenes=113` (`sampled_scene_ratio=0.933884`)
- `coverage_summary.avg_frames_sampled_per_scene=1.966942`
- `coverage_summary.escalated_scenes=0`
- `coverage_summary.dense_rescans=0`

Interpretation:

- Performance is now operationally stable for MVP iteration.
- Coverage is strong but not complete (8 scenes unsampled), so this baseline is
  accepted as "healthy to proceed" rather than "forensic recall complete."
- Dense fallback remains intentionally disabled in default degraded mode to keep
  CPU runtime predictable.

## Next Stage Gate

Proceed with this baseline and treat the following as follow-up hardening:

- Add a tiny strict/escalation mode budget for dense rescans (for example 2-3
  windows) on suspicious hits.
- Validate recall on 2-3 adversarial short-flash videos before claiming
  high-recall coverage.
