"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getTeams, TeamRow } from "@/lib/public-api";

export default function TeamsPage() {
  const [teams, setTeams] = useState<TeamRow[] | null>(null);

  useEffect(() => {
    getTeams().then(setTeams).catch(() => setTeams([]));
  }, []);

  const divisions = new Map<string, TeamRow[]>();
  (teams ?? []).forEach((t) => {
    const key = `${t.league} ${t.division}`;
    divisions.set(key, [...(divisions.get(key) ?? []), t]);
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Teams</h1>
      {!teams && <p className="text-sm text-zinc-500">Loading…</p>}
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {[...divisions.entries()].map(([division, rows]) => (
          <div key={division}>
            <h2 className="mb-2 text-sm font-semibold text-zinc-500">{division}</h2>
            <ul className="space-y-1">
              {rows.map((t) => (
                <li key={t.team_id}>
                  <Link
                    href={`/teams/${t.abbrev}`}
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
