"use client";

import Link from "next/link";
import { useState } from "react";
import { JobAccepted } from "../lib/api";
import { SourceForm } from "../components/source-form";
import { JobView } from "../components/job-view";

export default function HomePage() {
  const [accepted, setAccepted] = useState<JobAccepted | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  return (
    <main className="container stack">
      <header className="panel">
        <h1>Softcut</h1>
        <p className="muted">
          Minimal moderation pipeline UI for upload/URL ingestion, analysis, and planner outputs.
        </p>
      </header>

      <SourceForm
        onAccepted={(job) => {
          setAccepted(job);
          setActiveJobId(job.job_id);
        }}
      />

      {accepted ? (
        <section className="panel">
          <h3>Latest Submission</h3>
          <p className="mono">Job ID: {accepted.job_id}</p>
          <p className="muted">{accepted.message}</p>
          <Link href={`/jobs/${encodeURIComponent(accepted.job_id)}`}>Open dedicated job page</Link>
        </section>
      ) : null}

      {activeJobId ? <JobView jobId={activeJobId} /> : null}
    </main>
  );
}
