"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getJSON, fmtNum, fmtPct, today } from "@/lib/api";
import { useLang } from "@/lib/i18n";

type BatterPrediction = {
  game_pk: number;
  home: string;
  away: string;
  player_id: number;
  batter: string;
  probable_pitcher_id?: number | null;
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
  const { t } = useLang();
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
        <h1 className="text-lg font-semibold">{t.batters.title}</h1>
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
            <option value="all">{t.batters.allGames}</option>
            {matchups.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        )}
      </div>
      {error && (
        <p className="text-sm text-zinc-500">{t.batters.noneFor(date)}</p>
      )}
      {!rows && !error && <p className="text-sm text-zinc-500">{t.common.loading}</p>}
      {rows && (
        <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
              <tr>
                <th className="px-3 py-2">{t.batters.colBatter}</th>
                <th className="px-3 py-2 text-right">{t.batters.colSlot}</th>
                <th className="px-3 py-2">{t.batters.colGame}</th>
                <th className="px-3 py-2">{t.batters.colVsSp}</th>
                <th className="px-3 py-2 text-right">{t.batters.colPHit}</th>
                <th className="px-3 py-2 text-right">{t.batters.colPHr}</th>
                <th className="px-3 py-2 text-right">{t.batters.colPTb2}</th>
                <th className="px-3 py-2 text-right">{t.batters.colEH}</th>
                <th className="px-3 py-2 text-right">{t.batters.colETb}</th>
                <th className="px-3 py-2 text-right">{t.batters.colEK}</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r, i) => (
                <tr
                  key={`${r.game_pk}-${r.batter}-${i}`}
                  className="border-t border-zinc-200 dark:border-zinc-800"
                >
                  <td className="px-3 py-2 font-medium">
                    <Link
                      href={`/players/detail?id=${r.player_id}`}
                      className="text-[var(--accent-text)] hover:underline"
                    >
                      {r.batter}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-right text-zinc-500">
                    {r.lineup_slot ?? "—"}
                  </td>
                  <td className="px-3 py-2 text-zinc-500">
                    {r.away} @ {r.home}
                  </td>
                  <td className="px-3 py-2 text-zinc-500">
                    {r.probable_pitcher_id && r.probable_pitcher ? (
                      <Link
                        href={`/players/detail?id=${r.probable_pitcher_id}`}
                        className="text-[var(--accent-text)] hover:underline"
                      >
                        {r.probable_pitcher}
                      </Link>
                    ) : (
                      r.probable_pitcher ?? t.common.tbd
                    )}
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
