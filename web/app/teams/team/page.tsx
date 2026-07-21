"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { getTeam, TeamDetail } from "@/lib/public-api";
import { pctLabel } from "@/lib/copy";
import { useLang } from "@/lib/i18n";
import { ResultMark } from "@/components/shared";

export default function TeamPage() {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
      <TeamContent />
    </Suspense>
  );
}

function TeamContent() {
  const { t } = useLang();
  const abbrev = useSearchParams().get("ab");
  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (abbrev) getTeam(abbrev).then(setTeam).catch((e) => setError(String(e)));
  }, [abbrev]);

  if (error) return <p className="text-sm text-zinc-500">{t.teamPage.notFound}</p>;
  if (!team) return <p className="text-sm text-zinc-500">{t.common.loading}</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{team.team}</h1>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">
          {t.teamPage.last10}{" "}
          <span className="font-semibold">
            {t.common.wl(`${team.last10_wins}`, `${team.last10_losses}`)}
          </span>
          {team.runs_per_game_l10 != null && (
            <> · {t.teamPage.scoring(team.runs_per_game_l10.toFixed(1))}</>
          )}
        </p>
      </div>
      <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-sm">
          <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
            <tr>
              <th className="px-3 py-2">{t.teamPage.colDate}</th>
              <th className="px-3 py-2">{t.teamPage.colGame}</th>
              <th className="px-3 py-2 text-right">{t.teamPage.colScore}</th>
              <th className="px-3 py-2 text-right">{t.teamPage.colWl}</th>
              <th className="px-3 py-2 text-right">{t.teamPage.colOurCall}</th>
              <th className="px-3 py-2 text-right">{t.teamPage.colRight}</th>
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
                        {g.team_won ? t.teamPage.win : t.teamPage.loss}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-zinc-600 dark:text-zinc-300">
                    {usWinChance == null
                      ? "—"
                      : pickedUs
                        ? t.teamPage.teamToWin(team.team, pctLabel(usWinChance))
                        : t.teamPage.opponent(pctLabel(1 - usWinChance))}
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
