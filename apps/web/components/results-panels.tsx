"use client";

import { JobResults } from "../lib/api";

export function ResultsPanels({ results }: { results: JobResults }) {
  const quality = results.analysis_quality;
  const coverage = results.coverage_summary ?? {};
  const planner = results.planner_summary ?? {};
  const actionCounts = (planner["action_counts"] as Record<string, number> | undefined) ?? {};

  return (
    <section className="stack" aria-label="Results Panels">
      <article className="panel">
        <h3>Analysis Quality</h3>
        {quality ? (
          <div className="row three">
            <div className="kpi">
              <div className="key">Passed</div>
              <div className={`value ${quality.passed ? "status-ok" : "status-danger"}`}>
                {String(quality.passed)}
              </div>
            </div>
            <div className="kpi">
              <div className="key">Planner Eligible</div>
              <div className={`value ${quality.planner_eligible ? "status-ok" : "status-warn"}`}>
                {String(quality.planner_eligible)}
              </div>
            </div>
            <div className="kpi">
              <div className="key">Warnings</div>
              <div className="value">{quality.warnings.length}</div>
            </div>
          </div>
        ) : (
          <p className="muted">No analysis quality summary yet.</p>
        )}
      </article>

      <article className="panel">
        <h3>Coverage Summary</h3>
        <div className="row three">
          <div className="kpi">
            <div className="key">Total Scenes</div>
            <div className="value">{String(coverage["total_scenes"] ?? "-")}</div>
          </div>
          <div className="kpi">
            <div className="key">Sampled Scenes</div>
            <div className="value">{String(coverage["sampled_scenes"] ?? "-")}</div>
          </div>
          <div className="kpi">
            <div className="key">Dense Rescans</div>
            <div className="value">{String(coverage["dense_rescans"] ?? "-")}</div>
          </div>
        </div>
      </article>

      <article className="panel">
        <h3>Planner Summary</h3>
        <div className="row three">
          <div className="kpi">
            <div className="key">Planned Actions</div>
            <div className="value">{String(planner["planned_actions"] ?? "-")}</div>
          </div>
          <div className="kpi">
            <div className="key">Candidate Windows</div>
            <div className="value">{String(planner["candidate_windows"] ?? "-")}</div>
          </div>
          <div className="kpi">
            <div className="key">Avg Confidence</div>
            <div className="value">{String(planner["avg_confidence"] ?? "-")}</div>
          </div>
        </div>
        {Object.keys(actionCounts).length > 0 ? (
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(actionCounts).map(([action, count]) => (
                <tr key={action}>
                  <td className="mono">{action}</td>
                  <td>{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </article>
    </section>
  );
}
