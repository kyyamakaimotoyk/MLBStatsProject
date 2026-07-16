"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Feed, getFeed, getSummary, Summary } from "@/lib/public-api";
import { copy, pctLabel } from "@/lib/copy";
import { PicksTable, ProofChip } from "@/components/shared";

export default function HomePage() {
  const [feed, setFeed] = useState<Feed | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDays, setShowDays] = useState(4);

  useEffect(() => {
    getFeed(10).then(setFeed).catch((e) => setError(String(e)));
    getSummary().then(setSummary).catch(() => {});
  }, []);

  const todayStr = new Date().toISOString().slice(0, 10);
  const tonight = feed?.days.find((d) => d.date === todayStr);
  const past = (feed?.days ?? []).filter((d) => d.date !== todayStr);

  return (
    <div className="space-y-10">
      <section className="space-y-4 pt-4 text-center">
        <h1 className="text-3xl font-bold">{copy.site.tagline}</h1>
        <p className="mx-auto max-w-2xl text-zinc-600 dark:text-zinc-400">
          {copy.site.subtitle}
        </p>
        <div className="flex justify-center gap-3">
          <a
            href="#tonight"
            className="rounded bg-orange-500 px-4 py-2 text-sm font-semibold text-white hover:bg-orange-600"
          >
            {copy.site.ctaTonight}
          </a>
          <Link
            href="/record"
            className="rounded border border-zinc-300 px-4 py-2 text-sm font-semibold hover:border-orange-500 dark:border-zinc-700"
          >
            {copy.site.ctaRecord}
          </Link>
        </div>
        {summary && (
          <div className="mx-auto flex max-w-2xl flex-wrap justify-center gap-3 pt-2">
            <ProofChip
              metric={pctLabel(
                summary.last30_wins / Math.max(summary.last30_wins + summary.last30_losses, 1),
              )}
              line1={copy.proof.winners("last 30 days")}
              line2={`${summary.last30_wins}–${summary.last30_losses}`}
            />
            <ProofChip
              metric={`±${summary.avg_score_error.toFixed(1)} runs`}
              line1={copy.proof.scoreMiss(`since ${summary.since.slice(0, 4)}`)}
            />
            <ProofChip
              metric={summary.games_graded.toLocaleString()}
              line1={copy.proof.logged}
              line2={copy.proof.loggedSub}
            />
          </div>
        )}
      </section>

      <section id="tonight" className="space-y-3">
        <h2 className="text-lg font-semibold">
          {tonight ? `Predictions for ${tonight.date}` : "No games tonight"}
        </h2>
        {error && <p className="text-sm text-zinc-500">Predictions are loading late — check back shortly.</p>}
        {!feed && !error && <p className="text-sm text-zinc-500">Loading tonight's picks…</p>}
        {tonight && <PicksTable games={tonight.games} />}
        {tonight && tonight.games.some((g) => g.watch.length > 0) && (
          <div className="rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <div className="mb-1 font-semibold text-zinc-600 dark:text-zinc-400">
              Hitters to watch tonight
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              {tonight.games
                .flatMap((g) => g.watch.map((w) => ({ ...w, game: `${g.away}@${g.home}` })))
                .sort((a, b) => b.p_hr - a.p_hr)
                .slice(0, 6)
                .map((w) => (
                  <span key={`${w.game}-${w.name}`} className="text-zinc-600 dark:text-zinc-300">
                    <span className="font-medium">{w.name}</span>{" "}
                    <span className="text-zinc-400">({w.game})</span> ·{" "}
                    {pctLabel(w.p_hr)} to homer
                  </span>
                ))}
            </div>
          </div>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Recent results</h2>
        {past.slice(0, showDays).map((d) => (
          <div key={d.date} className="space-y-2">
            <h3 className="text-sm font-semibold text-zinc-500">{d.date}</h3>
            <PicksTable games={d.games} />
          </div>
        ))}
        {past.length > showDays && (
          <button
            onClick={() => setShowDays((n) => n + 4)}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:border-orange-500 dark:border-zinc-700"
          >
            Show more days
          </button>
        )}
      </section>

      <section className="grid gap-4 border-t border-zinc-200 pt-8 sm:grid-cols-4 dark:border-zinc-800">
        {copy.steps.map((s, i) => (
          <div key={s.title} className="space-y-1">
            <div className="text-xs font-bold text-orange-500">STEP {i + 1}</div>
            <div className="font-semibold">{s.title}</div>
            <p className="text-sm text-zinc-500">{s.body}</p>
          </div>
        ))}
      </section>

      <p className="pb-4 text-center text-xs text-zinc-400">{copy.site.disclaimer}</p>
    </div>
  );
}
