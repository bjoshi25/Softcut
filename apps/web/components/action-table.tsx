"use client";

type ActionRow = {
  action_id: string;
  action: string;
  risk_level: string;
  start_sec: number;
  end_sec: number;
  rationale: string;
};

export function ActionTable({ actions }: { actions: ActionRow[] }) {
  if (!actions.length) {
    return (
      <section className="panel">
        <h3>Planned Actions</h3>
        <p className="muted">No planned actions available yet.</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h3>Planned Actions</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Action</th>
            <th>Risk</th>
            <th>Start</th>
            <th>End</th>
            <th>Rationale</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((item) => (
            <tr key={item.action_id}>
              <td className="mono">{item.action_id}</td>
              <td className="mono">{item.action}</td>
              <td>{item.risk_level}</td>
              <td>{item.start_sec.toFixed(3)}</td>
              <td>{item.end_sec.toFixed(3)}</td>
              <td>{item.rationale}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
