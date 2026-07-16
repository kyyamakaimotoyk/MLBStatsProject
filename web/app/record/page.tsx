"use client";

import { useEffect, useState } from "react";
import { Feed, getFeed, getSummary, Summary } from "@/lib/public-api";
import { pctLabel } from "@/lib/copy";
import { PicksStrip, ProofChip } from "@/components/shared";

export default function RecordPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [feed, setFeed] = useState<Feed | null>(null);

  useEffect(() => {
    getSummary().then(setSummary).catch(() => {});
    getFeed(21).then(setFeed).catch(() => {});
  }, []);

  const gradedGames = (feed?.days ?? [])
    .flatMap((d) => d.games)
    .filter((g) => g.correct != null)
    .reverse();

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">The track record</h1>
        <p className="mt-1 text-zinc-600 dark:text-zinc-400">
          Every prediction gets graded against the final score — the good calls
          and the bad ones. Nothing is deleted, nothing is cherry-picked.
        </p>
      </div>

      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <ProofChip
            metric={pctLabel(summary.winners_pct)}
            line1="winners called"
            line2={`across ${summary.games_graded.toLocaleString()} games since ${summary.since}`}
          />
          <ProofChip
            metric={`${summary.last30_wins}–${summary.last30_losses}`}
            line1="last 30 days"
            line2="picking the winner"
          />
          <ProofChip
            metric={`±${summary.avg_score_error.toFixed(1)} runs`}
            line1="average score miss"
            line2={`total-runs miss ±${summary.avg_total_error.toFixed(1)}`}
          />
          <ProofChip
            metric={pctLabel(summary.batter_hit_call_pct)}
            line1="hitter calls right"
            line2={`"gets a hit tonight?" — ${summary.batter_calls_graded.toLocaleString()} graded`}
          />
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">The last three weeks, pick by pick</h2>
        <p className="text-sm text-zinc-500">
          One square per game, oldest to newest. Hover for the pick.
        </p>
        {feed ? <PicksStrip games={gradedGames} /> : <p className="text-sm text-zinc-500">Loading…</p>}
        {gradedGames.length > 0 && (
          <p className="text-sm text-zinc-500">
            {gradedGames.filter((g) => g.correct).length}–
            {gradedGames.filter((g) => !g.correct).length} over this stretch
          </p>
        )}
      </section>

      <p className="text-xs text-zinc-400">
        The record includes the model's full backtest: for every past game the
        model was trained only on games before it, then its prediction was
        graded — the same rules it plays by every night now.
      </p>
    </div>
  );
}
