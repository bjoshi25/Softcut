"use client";

import { useQuery } from "@tanstack/react-query";
import { getJob, getJobResults } from "../lib/api";
import { JobStatusCard } from "./job-status";
import { ResultsPanels } from "./results-panels";
import { ActionTable } from "./action-table";

export function JobView({ jobId }: { jobId: string }) {
  const jobQuery = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) {
        return 2000;
      }
      return data.status === "running" || data.status === "queued" ? 2000 : false;
    }
  });

  const resultQuery = useQuery({
    queryKey: ["job-results", jobId],
    queryFn: () => getJobResults(jobId),
    enabled: Boolean(jobQuery.data),
    refetchInterval: (query) => {
      const status = jobQuery.data?.status;
      if (status === "running" || status === "queued") {
        return 2500;
      }
      return query.state.data ? false : 2500;
    }
  });

  if (jobQuery.isPending) {
    return <section className="panel">Loading job status...</section>;
  }
  if (jobQuery.error) {
    return <section className="panel status-danger">{String(jobQuery.error)}</section>;
  }

  const job = jobQuery.data;
  const results = resultQuery.data;

  return (
    <div className="stack">
      <JobStatusCard job={job} />
      {results ? (
        <>
          <ResultsPanels results={results} />
          <ActionTable actions={results.planned_actions ?? []} />
        </>
      ) : (
        <section className="panel muted">Results not available yet.</section>
      )}
    </div>
  );
}
