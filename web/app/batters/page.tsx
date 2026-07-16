"use client";

import { useEffect, useState } from "react";
import { getJSON, fmtNum, fmtPct, today } from "@/lib/api";

type BatterPrediction = {
  game_pk: number;
  home: string;
  away: string;
  batter: string;
  probable_pitcher: string | null;
  lineup_slot: number | null;
  exp_pa: number | null;
  exp_h: number | null;
  exp_tb: number | null;
  exp_hr: number | null;
  exp_bb: number | null;
  exp_k: number | null;
  p_hit: number | null;
  p_hr: number | null;
  p_tb2: number | null;
};

export default function BattersPage() {
  const [date, setDate] = useState(today());
  const [rows, setRows] = useState<BatterPrediction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gameFilter, setGameFilter] = useState<string>("all");

  useEffect(() => {
    setRows(null);
    setError(null);
    setGameFilter("all");
    getJSON<BatterPrediction[]>(`/api/batters?date=${date}`)
      .then(setRows)
      .catch((e) => setError(String(e)));
  }, [date]);

  const matchups = [...new Set((rows ?? []).map((r) => `${r.away} @ ${r.home}`))];
  const visible = (rows ?? []).filter(
    (r) => gameFilter === "all" || `${r.away} @ ${r.home}` === gameFilter,
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Batter vs probable pitcher</h1>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        {rows && matchups.length > 1 && (
          <select
            value={gameFilter}
            onChange={(e) => setGameFilter(e.target.value)}
            className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          >
            <option value="all">all games</option>
            {matchups.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        )}
      </div>
      {error && (
        <p className="text-sm text-zinc-500">No batter predictions for {date}.</p>
      )}
      {!rows && !error && <p className="text-sm text-zinc-500">Loading…</p>}
      {rows && (
        <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
              <tr>
                <th className="px-3 py-2">Batter</th>
                <th className="px-3 py-2 text-right">Slot</th>
                <th className="px-3 py-2">Game</th>
                <th className="px-3 py-2">vs SP</th>
                <th className="px-3 py-2 text-right">P(hit)</th>
                <th className="px-3 py-2 text-right">P(HR)</th>
                <th className="px-3 py-2 text-right">P(2+ TB)</th>
                <th className="px-3 py-2 text-right">E[H]</th>
                <th className="px-3 py-2 text-right">E[TB]</th>
                <th className="px-3 py-2 text-right">E[K]</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r, i) => (
                <tr
                  key={`${r.game_pk}-${r.batter}-${i}`}
                  className="border-t border-zinc-200 dark:border-zinc-800"
                >
                  <td className="px-3 py-2 font-medium">{r.batter}</td>
                  <td className="px-3 py-2 text-right text-zinc-500">
                    {r.lineup_slot ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-zinc-500">
                    {r.away} @ {r.home}
                  </td>
                  <td className="px-3 py-2 text-zinc-500">
                    {r.probable_pitcher ?? "TBD"}
                  </td>
                  <td className="px-3 py-2 text-right">{fmtPct(r.p_hit)}</td>
                  <td className="px-3 py-2 text-right">{fmtPct(r.p_hr)}</td>
                  <td className="px-3 py-2 text-right">{fmtPct(r.p_tb2)}</td>
                  <td className="px-3 py-2 text-right">{fmtNum(r.exp_h)}</td>
                  <td className="px-3 py-2 text-right">{fmtNum(r.exp_tb)}</td>
                  <td className="px-3 py-2 text-right">{fmtNum(r.exp_k)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
