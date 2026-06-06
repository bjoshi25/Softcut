# Softcut UI Design Direction

## Intent

Minimal, trustworthy interface for long-running video moderation workflows.
Prioritize clarity and confidence over decoration.

## Visual Principles

- Monochrome-first palette with one restrained accent for interactive focus.
- Strong hierarchy through spacing and border rhythm, not heavy color.
- High information density in results tables while keeping generous whitespace in input sections.
- No ornamental motion; only progress and state transitions.

## Domain Adaptation

- Surface pipeline state prominently (`queued/running/completed/failed`, stage timeline).
- Keep risk summaries readable at a glance (`passed`, `planner_eligible`, warnings, action counts).
- Make advanced controls available but secondary to one-click pipeline.
- Results emphasize traceability: source artifacts, timestamps, and action rationale.

## Typography and Layout

- Use `ui-sans-serif` fallback stack for reliability in MVP.
- Fixed content width with centered column and composable cards.
- Tables and key-value grids for outputs; avoid dashboard clutter.
