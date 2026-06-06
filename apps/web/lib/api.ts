export type JobStatus = "queued" | "running" | "completed" | "failed";
export type JobStage = "queued" | "ingest" | "analysis" | "planner" | "done" | "failed";
export type PipelineMode = "pipeline" | "analysis" | "planner";

export interface JobAccepted {
  job_id: string;
  pipeline_mode: string;
  status: JobStatus;
  stage: JobStage;
  message: string;
  artifacts: Record<string, string>;
}

export interface JobState {
  job_id: string;
  pipeline_mode: string;
  status: JobStatus;
  stage: JobStage;
  message: string;
  created_at_utc: string;
  started_at_utc?: string | null;
  updated_at_utc: string;
  completed_at_utc?: string | null;
  artifacts: Record<string, string>;
  error?: string | null;
}

export interface JobResults {
  job_id: string;
  status: JobStatus;
  stage: JobStage;
  artifacts: Record<string, string>;
  analysis_quality?: {
    passed: boolean;
    planner_eligible: boolean;
    warnings: string[];
    critical_findings: string[];
  } | null;
  coverage_summary?: Record<string, unknown> | null;
  planner_summary?: Record<string, unknown> | null;
  planned_actions: Array<{
    action_id: string;
    action: string;
    risk_level: string;
    start_sec: number;
    end_sec: number;
    rationale: string;
  }>;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Request failed with ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function createJobFromUrl(input: {
  url: string;
  pipeline_mode: "pipeline" | "analysis";
  job_id?: string;
}): Promise<JobAccepted> {
  const res = await fetch(`${API_BASE}/jobs/from-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });
  return parseJson<JobAccepted>(res);
}

export async function createJobFromUpload(input: {
  file: File;
  pipeline_mode: "pipeline" | "analysis";
  job_id?: string;
}): Promise<JobAccepted> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("pipeline_mode", input.pipeline_mode);
  if (input.job_id) {
    form.append("job_id", input.job_id);
  }
  const res = await fetch(`${API_BASE}/jobs/from-upload`, {
    method: "POST",
    body: form
  });
  return parseJson<JobAccepted>(res);
}

export async function queuePlanner(jobId: string): Promise<JobAccepted> {
  const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/planner`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({})
  });
  return parseJson<JobAccepted>(res);
}

export async function getJob(jobId: string): Promise<JobState> {
  const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
    cache: "no-store"
  });
  return parseJson<JobState>(res);
}

export async function getJobResults(jobId: string): Promise<JobResults> {
  const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}/results`, {
    cache: "no-store"
  });
  return parseJson<JobResults>(res);
}
