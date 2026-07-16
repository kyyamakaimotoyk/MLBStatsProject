"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getTeam, TeamDetail } from "@/lib/public-api";
import { pctLabel } from "@/lib/copy";
import { ResultMark } from "@/components/shared";

export default function TeamPage() {
  const params = useParams<{ abbrev: string }>();
  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (params.abbrev)
      getTeam(params.abbrev).then(setTeam).catch((e) => setError(String(e)));
  }, [params.abbrev]);

  if (error) return <p className="text-sm text-zinc-500">No recent games found.</p>;
  if (!team) return <p className="text-sm text-zinc-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{team.team}</h1>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">
          Last 10: <span className="font-semibold">{team.last10_wins}–{team.last10_losses}</span>
          {team.runs_per_game_l10 != null && (
            <> · scoring {team.runs_per_game_l10.toFixed(1)} runs a game</>
          )}
        </p>
      </div>
      <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
            <tr>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Game</th>
              <th className="px-3 py-2 text-right">Score</th>
              <th className="px-3 py-2 text-right">W/L</th>
              <th className="px-3 py-2 text-right">Our call</th>
              <th className="px-3 py-2 text-right">Right?</th>
            </tr>
          </thead>
          <tbody>
            {team.games.map((g) => {
              const isHome = g.home === team.team;
              const pickedUs =
                g.p_home != null ? (g.p_home >= 0.5) === isHome : null;
              const usWinChance =
                g.p_home == null ? null : isHome ? g.p_home : 1 - g.p_home;
              const correct =
                g.is_final && g.team_won != null && pickedUs != null
                  ? pickedUs === g.team_won
                  : null;
              return (
                <tr key={g.game_pk} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="px-3 py-2 text-zinc-500">{g.game_date}</td>
                  <td className="px-3 py-2 font-medium">
                    {g.away} @ {g.home}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {g.is_final ? `${g.away_score}–${g.home_score}` : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {g.team_won == null ? "—" : (
                      <span
                        className="font-semibold"
                        style={{ color: g.team_won ? "var(--good-text)" : "var(--bad-text)" }}
                      >
                        {g.team_won ? "W" : "L"}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-zinc-600 dark:text-zinc-300">
                    {usWinChance == null
                      ? "—"
                      : pickedUs
                        ? `${team.team} to win (${pctLabel(usWinChance)})`
                        : `opponent (${pctLabel(1 - usWinChance)})`}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <ResultMark correct={correct} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
