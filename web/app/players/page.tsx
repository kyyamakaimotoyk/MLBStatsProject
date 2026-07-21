"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getJSON, today } from "@/lib/api";
import { getPitcherBoard, PitcherBoardRow, searchPlayers } from "@/lib/public-api";
import { pctLabel } from "@/lib/copy";
import { useLang } from "@/lib/i18n";

type BatterRow = {
  game_pk: number;
  home: string;
  away: string;
  player_id: number;
  batter: string;
  probable_pitcher_id?: number | null;
  probable_pitcher: string | null;
  p_hit: number | null;
  p_hr: number | null;
  p_tb2: number | null;
  exp_h: number | null;
  exp_tb: number | null;
};

export default function PlayersPage() {
  const { t } = useLang();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ player_id: number; full_name: string }[]>([]);
  const [board, setBoard] = useState<BatterRow[] | null>(null);
  const [pitchers, setPitchers] = useState<PitcherBoardRow[] | null>(null);

  useEffect(() => {
    getJSON<BatterRow[]>(`/api/batters?date=${today()}`)
      .then(setBoard)
      .catch(() => setBoard([]));
    getPitcherBoard()
      .then((rows) =>
        setPitchers(
          [...rows].sort(
            (a, b) =>
              (b.sp_exp_k ?? b.opp_exp_k ?? -1) - (a.sp_exp_k ?? a.opp_exp_k ?? -1),
          ),
        ),
      )
      .catch(() => setPitchers([]));
  }, []);

  useEffect(() => {
    if (q.length < 2) {
      setResults([]);
      return;
    }
    const timer = setTimeout(() => searchPlayers(q).then(setResults).catch(() => {}), 250);
    return () => clearTimeout(timer);
  }, [q]);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">{t.players.title}</h1>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">{t.players.subtitle}</p>
      </div>

      <div className="relative max-w-md">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t.players.searchPlaceholder}
          className="w-full rounded border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        {results.length > 0 && (
          <ul className="absolute z-10 mt-1 w-full rounded border border-zinc-200 bg-white shadow dark:border-zinc-700 dark:bg-zinc-900">
            {results.map((r) => (
              <li key={r.player_id}>
                <Link
                  href={`/players/detail?id=${r.player_id}`}
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
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">{t.players.hitterBoardTitle}</h2>
          <Link href="/batters" className="text-sm text-[var(--accent-text)] hover:underline">
            {t.players.fullBoardLink}
          </Link>
        </div>
        <p className="text-sm text-zinc-500">{t.players.hitterBoardSub}</p>
        {!board && <p className="text-sm text-zinc-500">{t.common.loading}</p>}
        {board && board.length === 0 && (
          <p className="text-sm text-zinc-500">{t.players.noHitters}</p>
        )}
        {board && board.length > 0 && (
          <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
                <tr>
                  <th className="px-3 py-2">{t.players.colHitter}</th>
                  <th className="px-3 py-2">{t.players.colGame}</th>
                  <th className="px-3 py-2">{t.players.colFacing}</th>
                  <th className="px-3 py-2 text-right">{t.players.colHomers}</th>
                  <th className="px-3 py-2 text-right">{t.players.colTb2}</th>
                  <th className="px-3 py-2 text-right">{t.players.colHit}</th>
                </tr>
              </thead>
              <tbody>
                {board.slice(0, 40).map((r, i) => (
                  <tr key={`${r.game_pk}-${i}`} className="border-t border-zinc-200 dark:border-zinc-800">
                    <td className="px-3 py-2 font-medium">
                      <Link
                        href={`/players/detail?id=${r.player_id}`}
                        className="text-[var(--accent-text)] hover:underline"
                      >
                        {r.batter}
                      </Link>
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
                    <td className="px-3 py-2 text-right font-medium">{pctLabel(r.p_hr)}</td>
                    <td className="px-3 py-2 text-right">{pctLabel(r.p_tb2)}</td>
                    <td className="px-3 py-2 text-right text-zinc-500">{pctLabel(r.p_hit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-zinc-400">{t.players.hitterFoot}</p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t.players.pitchingTitle}</h2>
        <p className="text-sm text-zinc-500">{t.players.pitchingSub}</p>
        {!pitchers && <p className="text-sm text-zinc-500">{t.common.loading}</p>}
        {pitchers && pitchers.length === 0 && (
          <p className="text-sm text-zinc-500">{t.players.noPitchers}</p>
        )}
        {pitchers && pitchers.length > 0 && (
          <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
                <tr>
                  <th className="px-3 py-2">{t.players.colPitcher}</th>
                  <th className="px-3 py-2">{t.players.colGame}</th>
                  <th className="px-3 py-2 text-right">{t.players.colEra}</th>
                  <th className="px-3 py-2 text-right">{t.players.colWhip}</th>
                  <th className="px-3 py-2 text-right">{t.players.colK9}</th>
                  <th className="px-3 py-2 text-right">{t.players.colExpK}</th>
                  <th className="px-3 py-2 text-right">{t.players.colExpBb}</th>
                  <th className="px-3 py-2 text-right">{t.players.colExpH}</th>
                </tr>
              </thead>
              <tbody>
                {pitchers.map((r) => (
                  <tr
                    key={`${r.game_pk}-${r.pitcher_id}`}
                    className="border-t border-zinc-200 dark:border-zinc-800"
                  >
                    <td className="px-3 py-2 font-medium">
                      <Link
                        href={`/players/detail?id=${r.pitcher_id}`}
                        className="text-[var(--accent-text)] hover:underline"
                      >
                        {r.pitcher}
                      </Link>
                      <span className="ml-2 text-xs text-zinc-500">
                        {r.team}
                        {r.throws ? ` · ${t.players.throws(r.throws)}` : ""}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-zinc-500">
                      {r.away} @ {r.home}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.era != null ? r.era.toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.whip != null ? r.whip.toFixed(2) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.k9 != null ? r.k9.toFixed(1) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-medium">
                      {r.sp_exp_k != null ? r.sp_exp_k.toFixed(1) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.sp_exp_bb != null ? r.sp_exp_bb.toFixed(1) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {r.sp_exp_h != null ? r.sp_exp_h.toFixed(1) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-zinc-400">{t.players.pitchingFoot}</p>
      </section>
    </div>
  );
}
