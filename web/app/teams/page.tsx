"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getTeams, getTeamTrends, TeamRow, TeamTrends } from "@/lib/public-api";
import { TeamTrendsChart } from "@/components/charts";
import { useLang } from "@/lib/i18n";

// Labels live in lib/translations.ts (t.teams.trendStats), keyed by these values.
const TREND_STAT_KEYS = ["runs_scored", "runs_allowed", "run_diff", "total_runs"];

export default function TeamsPage() {
  const { t } = useLang();
  const [teams, setTeams] = useState<TeamRow[] | null>(null);
  const [selected, setSelected] = useState<string[]>(["PHI", "NYM"]);
  const [stat, setStat] = useState("runs_scored");
  const [trends, setTrends] = useState<TeamTrends | null>(null);

  useEffect(() => {
    getTeams().then(setTeams).catch(() => setTeams([]));
  }, []);

  useEffect(() => {
    if (selected.length === 0) {
      setTrends(null);
      return;
    }
    getTeamTrends(stat, selected).then(setTrends).catch(() => setTrends(null));
  }, [stat, selected]);

  const toggle = (ab: string) =>
    setSelected((cur) =>
      cur.includes(ab) ? cur.filter((x) => x !== ab) : cur.length >= 6 ? cur : [...cur, ab],
    );

  const divisions = new Map<string, TeamRow[]>();
  (teams ?? []).forEach((row) => {
    const key = `${row.league} ${row.division}`;
    divisions.set(key, [...(divisions.get(key) ?? []), row]);
  });

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">{t.teams.title}</h1>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t.teams.trendsTitle}</h2>
        <p className="text-sm text-zinc-500">{t.teams.trendsSub}</p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={stat}
            onChange={(e) => setStat(e.target.value)}
            className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          >
            {TREND_STAT_KEYS.map((key) => (
              <option key={key} value={key}>
                {t.teams.trendStats[key]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap gap-1">
          {(teams ?? []).map((row) => (
            <button
              key={row.abbrev}
              onClick={() => toggle(row.abbrev)}
              className={`rounded border px-2 py-0.5 text-xs font-mono ${
                selected.includes(row.abbrev)
                  ? "border-[var(--accent-mark)] font-semibold"
                  : "border-zinc-300 text-zinc-500 dark:border-zinc-700"
              }`}
              style={
                selected.includes(row.abbrev)
                  ? { color: "var(--accent-text)" }
                  : undefined
              }
            >
              {row.abbrev}
            </button>
          ))}
        </div>
        {trends && trends.series.length > 0 && (
          <TeamTrendsChart
            series={trends.series}
            statLabel={t.teams.trendStats[stat] ?? stat}
          />
        )}
        {selected.length === 0 && (
          <p className="text-sm text-zinc-500">{t.teams.pickOne}</p>
        )}
      </section>

      <h2 className="text-lg font-semibold">{t.teams.teamPages}</h2>
      {!teams && <p className="text-sm text-zinc-500">{t.common.loading}</p>}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {[...divisions.entries()].map(([division, rows]) => (
          <div key={division}>
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">{division}</h2>
            <ul className="space-y-1">
              {rows.map((row) => (
                <li key={row.team_id}>
                  <Link
                    href={`/teams/team?ab=${row.abbrev}`}
                    className="text-sm hover:text-[var(--accent-text)]"
                  >
                    <span className="font-mono text-zinc-400">{row.abbrev}</span>{" "}
                    {row.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
