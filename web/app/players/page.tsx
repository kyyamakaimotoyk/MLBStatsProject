"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getJSON, today } from "@/lib/api";
import { searchPlayers } from "@/lib/public-api";
import { pctLabel } from "@/lib/copy";

type BatterRow = {
  game_pk: number;
  home: string;
  away: string;
  player_id: number;
  batter: string;
  probable_pitcher: string | null;
  p_hit: number | null;
  p_hr: number | null;
  exp_h: number | null;
  exp_tb: number | null;
};

export default function PlayersPage() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ player_id: number; full_name: string }[]>([]);
  const [board, setBoard] = useState<BatterRow[] | null>(null);

  useEffect(() => {
    getJSON<BatterRow[]>(`/api/batters?date=${today()}`)
      .then(setBoard)
      .catch(() => setBoard([]));
  }, []);

  useEffect(() => {
    if (q.length < 2) {
      setResults([]);
      return;
    }
    const t = setTimeout(() => searchPlayers(q).then(setResults).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Players</h1>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">
          Look up any hitter's recent games and how our calls on them have done.
        </p>
      </div>

      <div className="relative max-w-md">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search a player, e.g. Juan Soto"
          className="w-full rounded border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        {results.length > 0 && (
          <ul className="absolute z-10 mt-1 w-full rounded border border-zinc-200 bg-white shadow dark:border-zinc-700 dark:bg-zinc-900">
            {results.map((r) => (
              <li key={r.player_id}>
                <Link
                  href={`/players/${r.player_id}`}
                  className="block px-3 py-2 text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  onClick={() => setQ("")}
                >
                  {r.full_name}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Tonight's hitter board</h2>
        {!board && <p className="text-sm text-zinc-500">Loading…</p>}
        {board && board.length === 0 && (
          <p className="text-sm text-zinc-500">No hitter predictions posted yet today.</p>
        )}
        {board && board.length > 0 && (
          <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
                <tr>
                  <th className="px-3 py-2">Hitter</th>
                  <th className="px-3 py-2">Game</th>
                  <th className="px-3 py-2">Facing</th>
                  <th className="px-3 py-2 text-right">Gets a hit</th>
                  <th className="px-3 py-2 text-right">Homers</th>
                  <th className="px-3 py-2 text-right">Hits expected</th>
                </tr>
              </thead>
              <tbody>
                {board.slice(0, 40).map((r, i) => (
                  <tr key={`${r.game_pk}-${i}`} className="border-t border-zinc-200 dark:border-zinc-800">
                    <td className="px-3 py-2 font-medium">
                      <Link
                        href={`/players/${r.player_id}`}
                        className="hover:text-[var(--accent-text)] hover:underline"
                      >
                        {r.batter}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-zinc-500">
                      {r.away} @ {r.home}
                    </td>
                    <td className="px-3 py-2 text-zinc-500">{r.probable_pitcher ?? "TBD"}</td>
                    <td className="px-3 py-2 text-right">{pctLabel(r.p_hit)}</td>
                    <td className="px-3 py-2 text-right">{pctLabel(r.p_hr)}</td>
                    <td className="px-3 py-2 text-right">
                      {r.exp_h != null ? r.exp_h.toFixed(1) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
