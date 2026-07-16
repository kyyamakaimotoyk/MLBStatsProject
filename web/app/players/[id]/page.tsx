"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getPlayer, PlayerDetail } from "@/lib/public-api";
import { pctLabel } from "@/lib/copy";
import { ResultMark } from "@/components/shared";
import { PlayerHitsChart } from "@/components/charts";

export default function PlayerPage() {
  const params = useParams<{ id: string }>();
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (params.id)
      getPlayer(Number(params.id)).then(setPlayer).catch((e) => setError(String(e)));
  }, [params.id]);

  if (error) return <p className="text-sm text-zinc-500">Player not found.</p>;
  if (!player) return <p className="text-sm text-zinc-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{player.name}</h1>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">
          Last 15 games:{" "}
          {player.l15_hits_per_game != null && (
            <>
              <span className="font-semibold">{player.l15_hits_per_game.toFixed(1)}</span>{" "}
              hits a game
            </>
          )}
          {" · "}
          <span className="font-semibold">{player.l15_hr}</span> home runs
        </p>
      </div>

      <PlayerHitsChart games={player.games} />

      <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
            <tr>
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Game</th>
              <th className="px-3 py-2 text-right">H</th>
              <th className="px-3 py-2 text-right">HR</th>
              <th className="px-3 py-2 text-right">TB</th>
              <th className="px-3 py-2 text-right">BB</th>
              <th className="px-3 py-2 text-right">K</th>
              <th className="px-3 py-2 text-right">We said (a hit)</th>
              <th className="px-3 py-2 text-right">Right?</th>
            </tr>
          </thead>
          <tbody>
            {player.games.map((g, i) => {
              const gotHit = g.h != null ? g.h >= 1 : null;
              const calledHit = g.p_hit != null ? g.p_hit >= 0.5 : null;
              const correct =
                gotHit != null && calledHit != null ? calledHit === gotHit : null;
              return (
                <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="px-3 py-2 text-zinc-500">{g.game_date}</td>
                  <td className="px-3 py-2">
                    {g.away} @ {g.home}
                  </td>
                  <td className="px-3 py-2 text-right font-medium">{g.h ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{g.hr ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{g.tb ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{g.bb ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{g.k ?? "—"}</td>
                  <td className="px-3 py-2 text-right text-zinc-600 dark:text-zinc-300">
                    {g.p_hit != null ? pctLabel(g.p_hit) : "—"}
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
      <p className="text-xs text-zinc-400">
        "We said" is the model's pregame chance this player gets at least one
        hit; it's graded against what actually happened.
      </p>
    </div>
  );
}
