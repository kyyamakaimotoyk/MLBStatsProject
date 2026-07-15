"use client";

import { useEffect, useState } from "react";
import { getJSON, fmtNum, fmtPct } from "@/lib/api";

type TeamPerf = {
  model_type: string;
  model_version: string;
  n: number;
  win_acc: number;
  margin_mae: number;
  total_mae: number;
};
type BatterPerf = {
  model_version: string;
  n: number;
  brier_p_hit: number;
  brier_p_hr: number;
  mae_h: number;
};
type Performance = { days: number; team: TeamPerf[]; batter: BatterPerf[] };

export default function PerformancePage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Performance | null>(null);

  useEffect(() => {
    setData(null);
    getJSON<Performance>(`/api/performance?days=${days}`)
      .then(setData)
      .catch(() => setData({ days, team: [], batter: [] }));
  }, [days]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Model performance</h1>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        >
          {[7, 30, 90, 365].map((d) => (
            <option key={d} value={d}>
              last {d} days
            </option>
          ))}
        </select>
      </div>
      {!data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && (
        <>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-zinc-600 dark:text-zinc-400">
              Team models (vs final scores)
            </h2>
            {data.team.length === 0 ? (
              <p className="text-sm text-zinc-500">No graded predictions yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
                  <tr>
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2">Version</th>
                    <th className="px-3 py-2 text-right">N</th>
                    <th className="px-3 py-2 text-right">Win acc</th>
                    <th className="px-3 py-2 text-right">Margin MAE</th>
                    <th className="px-3 py-2 text-right">Total MAE</th>
                  </tr>
                </thead>
                <tbody>
                  {data.team.map((r) => (
                    <tr
                      key={`${r.model_type}-${r.model_version}`}
                      className="border-t border-zinc-200 dark:border-zinc-800"
                    >
                      <td className="px-3 py-2 font-medium">{r.model_type}</td>
                      <td className="px-3 py-2 text-zinc-500">{r.model_version}</td>
                      <td className="px-3 py-2 text-right">{r.n}</td>
                      <td className="px-3 py-2 text-right">{fmtPct(r.win_acc)}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(r.margin_mae, 3)}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(r.total_mae, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-zinc-600 dark:text-zinc-400">
              Batter model
            </h2>
            {data.batter.length === 0 ? (
              <p className="text-sm text-zinc-500">No graded predictions yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
                  <tr>
                    <th className="px-3 py-2">Version</th>
                    <th className="px-3 py-2 text-right">N</th>
                    <th className="px-3 py-2 text-right">Brier P(hit)</th>
                    <th className="px-3 py-2 text-right">Brier P(HR)</th>
                    <th className="px-3 py-2 text-right">MAE hits</th>
                  </tr>
                </thead>
                <tbody>
                  {data.batter.map((r) => (
                    <tr
                      key={r.model_version}
                      className="border-t border-zinc-200 dark:border-zinc-800"
                    >
                      <td className="px-3 py-2 font-medium">{r.model_version}</td>
                      <td className="px-3 py-2 text-right">{r.n}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(r.brier_p_hit, 4)}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(r.brier_p_hr, 4)}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(r.mae_h, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
