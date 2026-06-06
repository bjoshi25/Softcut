import { expect, test } from "@playwright/test";

test("URL submit polls and renders results summary", async ({ page }) => {
  let jobPollCount = 0;
  await page.route("**/jobs/from-url", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "job_ui_001",
        pipeline_mode: "pipeline",
        status: "queued",
        stage: "queued",
        message: "Job queued.",
        artifacts: {}
      })
    });
  });

  await page.route("**/jobs/job_ui_001", async (route) => {
    jobPollCount += 1;
    const running = jobPollCount < 2;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "job_ui_001",
        pipeline_mode: "pipeline",
        status: running ? "running" : "completed",
        stage: running ? "analysis" : "done",
        message: running ? "Running analysis." : "Pipeline completed.",
        created_at_utc: "2026-04-20T00:00:00Z",
        started_at_utc: "2026-04-20T00:00:01Z",
        updated_at_utc: "2026-04-20T00:00:02Z",
        completed_at_utc: running ? null : "2026-04-20T00:00:05Z",
        artifacts: {}
      })
    });
  });

  await page.route("**/jobs/job_ui_001/results", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "job_ui_001",
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
          total_scenes: 121,
          sampled_scenes: 113,
          dense_rescans: 0
        },
        planner_summary: {
          planned_actions: 14,
          candidate_windows: 15,
          avg_confidence: 0.72,
          action_counts: { trim_segment: 10, beep_word: 1, mute_word: 3 }
        },
        planned_actions: [
          {
            action_id: "action_0001",
            action: "trim_segment",
            risk_level: "high",
            start_sec: 55.2,
            end_sec: 59.1,
            rationale: "violent_dialogue -> trim_segment"
          }
        ]
      })
    });
  });

  await page.goto("/");
  await page.getByLabel("Video URL").fill("https://example.com/video.mp4");
  await page.getByRole("button", { name: "Run Analysis + Planner" }).click();

  await expect(page.getByText("Job ID: job_ui_001")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Analysis Quality" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Planned Actions" })).toBeVisible();
  await expect(page.getByText("trim_segment")).toBeVisible();
});
