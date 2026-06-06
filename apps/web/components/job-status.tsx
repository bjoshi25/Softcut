"use client";

import { JobState } from "../lib/api";

function cls(status: JobState["status"]): string {
  if (status === "completed") {
    return "status-ok";
  }
  if (status === "failed") {
    return "status-danger";
  }
  return "status-warn";
}

export function JobStatusCard({ job }: { job: JobState }) {
  return (
    <section className="panel" aria-label="Job Status">
      <h2>Job Status</h2>
      <div className="row three">
        <div className="kpi">
          <div className="key">Job ID</div>
          <div className="value mono">{job.job_id}</div>
        </div>
        <div className="kpi">
          <div className="key">Status</div>
          <div className={`value ${cls(job.status)}`}>{job.status}</div>
        </div>
        <div className="kpi">
          <div className="key">Stage</div>
          <div className="value">{job.stage}</div>
        </div>
      </div>
      <p className="muted">{job.message}</p>
      {job.error ? <p className="status-danger">{job.error}</p> : null}
    </section>
  );
}
