"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getTeams, getTeamTrends, TeamRow, TeamTrends } from "@/lib/public-api";
import { TeamTrendsChart } from "@/components/charts";

const TREND_STATS = [
  { key: "runs_scored", label: "Runs scored" },
  { key: "runs_allowed", label: "Runs allowed" },
  { key: "run_diff", label: "Run difference" },
  { key: "total_runs", label: "Total runs in their games" },
];

export default function TeamsPage() {
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
      cur.includes(ab) ? cur.filter((t) => t !== ab) : cur.length >= 6 ? cur : [...cur, ab],
    );

  const divisions = new Map<string, TeamRow[]>();
  (teams ?? []).forEach((t) => {
    const key = `${t.league} ${t.division}`;
    divisions.set(key, [...(divisions.get(key) ?? []), t]);
  });

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Teams</h1>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Stat trends</h2>
        <p className="text-sm text-zinc-500">
          Pick up to six teams and a stat — the lines are 10-game rolling
          averages across this season.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={stat}
            onChange={(e) => setStat(e.target.value)}
            className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          >
            {TREND_STATS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap gap-1">
          {(teams ?? []).map((t) => (
            <button
              key={t.abbrev}
              onClick={() => toggle(t.abbrev)}
              className={`rounded border px-2 py-0.5 text-xs font-mono ${
                selected.includes(t.abbrev)
                  ? "border-[var(--accent-mark)] font-semibold"
                  : "border-zinc-300 text-zinc-500 dark:border-zinc-700"
              }`}
              style={
                selected.includes(t.abbrev)
                  ? { color: "var(--accent-text)" }
                  : undefined
              }
            >
              {t.abbrev}
            </button>
          ))}
        </div>
        {trends && trends.series.length > 0 && (
          <TeamTrendsChart
            series={trends.series}
            statLabel={TREND_STATS.find((s) => s.key === stat)?.label ?? stat}
          />
        )}
        {selected.length === 0 && (
          <p className="text-sm text-zinc-500">Pick at least one team.</p>
        )}
      </section>

      <h2 className="text-lg font-semibold">Team pages</h2>
      {!teams && <p className="text-sm text-zinc-500">Loading…</p>}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {[...divisions.entries()].map(([division, rows]) => (
          <div key={division}>
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">{division}</h2>
            <ul className="space-y-1">
              {rows.map((t) => (
                <li key={t.team_id}>
                  <Link
                    href={`/teams/team?ab=${t.abbrev}`}
                    className="text-sm hover:text-[var(--accent-text)]"
                  >
                    <span className="font-mono text-zinc-400">{t.abbrev}</span>{" "}
                    {t.name}
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
