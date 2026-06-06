import { render, screen } from "@testing-library/react";
import { ResultsPanels } from "../results-panels";

describe("ResultsPanels", () => {
  it("renders quality and planner summary sections", () => {
    render(
      <ResultsPanels
        results={{
          job_id: "job_001",
          status: "completed",
          stage: "done",
          artifacts: {},
          analysis_quality: {
            passed: true,
            planner_eligible: true,
            warnings: [],
            critical_findings: []
          },
          coverage_summary: {
            total_scenes: 10,
            sampled_scenes: 10,
            dense_rescans: 0
          },
          planner_summary: {
            planned_actions: 2,
            candidate_windows: 3,
            avg_confidence: 0.7,
            action_counts: { trim_segment: 2 }
          },
          planned_actions: []
        }}
      />
    );
    expect(screen.getByRole("heading", { name: /Analysis Quality/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Coverage Summary/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Planner Summary/i })).toBeInTheDocument();
  });
});
