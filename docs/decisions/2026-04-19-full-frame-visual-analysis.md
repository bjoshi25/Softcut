# Full-Frame Visual Analysis

## Status

Superseded by `2026-04-19-scene-aware-sparse-visual-analysis.md`.

## Context

Softcut needs visual risk evidence that reflects the real source video, not a
small set of representative still images. A sampled-frame path could miss short
red-band trailer moments and made `visual_flags=0` hard to interpret even when
OpenNSFW2 was installed and available.

Scanning every decoded frame can also create too many edit targets if each
above-threshold frame becomes its own evidence item. That would make downstream
cut planning choppy.

## Decision

Run OpenNSFW2 through its video-frame API with `frame_interval=1` and
`aggregation_size=1` for production analysis.

After scoring, calibrate the active threshold only from the full-frame score
distribution:

- Use the configured threshold when any frame crosses it.
- If no frame crosses it but the score tail is above a calibration floor, lower
  the active threshold to a high-percentile score.
- If the entire score distribution is below the calibration floor, keep zero
  visual flags and record score diagnostics.

Merge adjacent above-threshold frame hits into debounced visual events before
writing `visual_flags`, and cap event density per minute so cut candidates stay
smooth.

## Consequences

- Visual analysis no longer extracts or scores sampled image files.
- A zero-flag OpenNSFW2 run now records score distribution diagnostics such as
  max score, percentiles, active threshold, and calibration reason.
- OpenNSFW2 runs are more computationally expensive because every frame is
  scored.
- OpenNSFW2 remains a nudity/sexual-content signal; violence-heavy trailers may
  still need a complementary visual adapter.
