"use client";

import { FormEvent, useState } from "react";
import {
  createJobFromUpload,
  createJobFromUrl,
  JobAccepted,
  queuePlanner
} from "../lib/api";

type Mode = "upload" | "url";

interface Props {
  onAccepted(job: JobAccepted): void;
}

export function SourceForm({ onAccepted }: Props) {
  const [mode, setMode] = useState<Mode>("url");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [jobId, setJobId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(runMode: "pipeline" | "analysis" | "planner") {
    setBusy(true);
    setError(null);
    try {
      let accepted: JobAccepted;
      if (runMode === "planner") {
        if (!jobId.trim()) {
          throw new Error("job_id is required for planner-only runs.");
        }
        accepted = await queuePlanner(jobId.trim());
      } else if (mode === "url") {
        if (!url.trim()) {
          throw new Error("URL is required.");
        }
        accepted = await createJobFromUrl({
          url: url.trim(),
          pipeline_mode: runMode,
          job_id: jobId.trim() || undefined
        });
      } else {
        if (!file) {
          throw new Error("File is required for upload mode.");
        }
        accepted = await createJobFromUpload({
          file,
          pipeline_mode: runMode,
          job_id: jobId.trim() || undefined
        });
      }
      onAccepted(accepted);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="panel stack"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        void run("pipeline");
      }}
    >
      <h2>Video Pipeline</h2>
      <p className="muted">Run analysis + planner in one click, or use advanced controls.</p>

      <div className="row two">
        <label>
          <span className="label">Input Mode</span>
          <select
            aria-label="Input Mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as Mode)}
          >
            <option value="url">URL</option>
            <option value="upload">Upload File</option>
          </select>
        </label>
        <label>
          <span className="label">Optional Job ID</span>
          <input
            type="text"
            aria-label="Job ID"
            value={jobId}
            onChange={(event) => setJobId(event.target.value)}
            placeholder="job_001"
          />
        </label>
      </div>

      {mode === "url" ? (
        <label>
          <span className="label">Video URL</span>
          <input
            type="url"
            aria-label="Video URL"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
          />
        </label>
      ) : (
        <label>
          <span className="label">Video File</span>
          <input
            type="file"
            aria-label="Video File"
            accept="video/*"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
      )}

      <div className="row two">
        <button type="submit" disabled={busy}>
          {busy ? "Working..." : "Run Analysis + Planner"}
        </button>
          <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => {
            void run("analysis");
          }}
        >
          Run Analysis Only
        </button>
      </div>
      <button
        type="button"
        className="secondary"
        disabled={busy}
        onClick={() => {
          void run("planner");
        }}
      >
        Run Planner Only
      </button>

      {error ? <p className="status-danger">{error}</p> : null}
    </form>
  );
}
