"use client";

import { useEffect, useState } from "react";
import { getJSON, fmtNum, fmtPct } from "@/lib/api";

type Prediction = {
  game_pk: number;
  game_date: string;
  status: string | null;
  home: string;
  away: string;
  home_score: number | null;
  away_score: number | null;
  is_final: boolean;
  model_type: string;
  p_home: number | null;
  pred_margin: number | null;
  pred_total: number | null;
};

function tomorrowOrToday(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function PicksPage() {
  const [date, setDate] = useState(tomorrowOrToday());
  const [rows, setRows] = useState<Prediction[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    setError(null);
    getJSON<Prediction[]>(`/api/predictions?date=${date}`)
      .then(setRows)
      .catch((e) => setError(String(e)));
  }, [date]);

  const games = new Map<number, Prediction[]>();
  rows?.forEach((r) => {
    games.set(r.game_pk, [...(games.get(r.game_pk) ?? []), r]);
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Game predictions</h1>
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
      </div>
      {error && (
        <p className="text-sm text-zinc-500">No predictions for {date}.</p>
      )}
      {!rows && !error && <p className="text-sm text-zinc-500">Loading…</p>}
      {rows && (
        <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
              <tr>
                <th className="px-3 py-2">Matchup</th>
                <th className="px-3 py-2">Model</th>
                <th className="px-3 py-2 text-right">P(home)</th>
                <th className="px-3 py-2 text-right">Margin</th>
                <th className="px-3 py-2 text-right">Total</th>
                <th className="px-3 py-2 text-right">Result</th>
              </tr>
            </thead>
            <tbody>
              {[...games.values()].flat().map((r, i) => (
                <tr
                  key={`${r.game_pk}-${r.model_type}`}
                  className="border-t border-zinc-200 dark:border-zinc-800"
                >
                  <td className="px-3 py-2 font-medium">
                    {r.away} @ {r.home}
                  </td>
                  <td className="px-3 py-2 text-zinc-500">{r.model_type}</td>
                  <td className="px-3 py-2 text-right">{fmtPct(r.p_home)}</td>
                  <td className="px-3 py-2 text-right">
                    {r.pred_margin != null && r.pred_margin > 0 ? "+" : ""}
                    {fmtNum(r.pred_margin)}
                  </td>
                  <td className="px-3 py-2 text-right">{fmtNum(r.pred_total)}</td>
                  <td className="px-3 py-2 text-right text-zinc-500">
                    {r.is_final ? `${r.away_score}–${r.home_score}` : r.status ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
