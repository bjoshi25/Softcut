import { render, screen } from "@testing-library/react";
import { JobStatusCard } from "../job-status";

describe("JobStatusCard", () => {
  it("renders job details and status", () => {
    render(
      <JobStatusCard
        job={{
          job_id: "job_001",
          pipeline_mode: "pipeline",
          status: "running",
          stage: "analysis",
          message: "Working",
          created_at_utc: "2026-04-20T00:00:00Z",
          updated_at_utc: "2026-04-20T00:00:01Z",
          artifacts: {}
        }}
      />
    );
    expect(screen.getByText("job_001")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("analysis")).toBeInTheDocument();
  });
});
