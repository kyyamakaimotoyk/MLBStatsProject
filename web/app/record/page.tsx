"use client";

import { useEffect, useState } from "react";
import { Feed, getFeed, getSummary, Summary } from "@/lib/public-api";
import { getJSON } from "@/lib/api";
import { ResultRow } from "@/lib/perf";
import { pctLabel } from "@/lib/copy";
import { PicksStrip, ProofChip, WindowSelect } from "@/components/shared";
import { sinceDate, WindowKey } from "@/lib/windows";
import {
  ConfusionMatrix,
  MarginMissChart,
  RocChart,
  SkillCurveChart,
} from "@/components/charts";

export default function RecordPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [feed, setFeed] = useState<Feed | null>(null);
  const [rows, setRows] = useState<ResultRow[] | null>(null);
  const [win, setWin] = useState<WindowKey>("3m");

  useEffect(() => {
    getSummary().then(setSummary).catch(() => {});
    getFeed(21).then(setFeed).catch(() => {});
    getJSON<ResultRow[]>("/api/public/results").then(setRows).catch(() => {});
  }, []);

  const gradedGames = (feed?.days ?? [])
    .flatMap((d) => d.games)
    .filter((g) => g.correct != null)
    .reverse();

  const since = sinceDate(win);
  const view = (rows ?? []).filter((r) => r.game_date >= since);
  const correct = view.filter((r) => (r.p_home >= 0.5) === r.home_won).length;
  const marginMiss = view.length
    ? view.reduce((s, r) => s + Math.abs(r.pred_margin - r.margin), 0) / view.length
    : null;
  const totalMiss = view.filter((r) => r.pred_total != null && r.total != null);
  const totalMissAvg = totalMiss.length
    ? totalMiss.reduce((s, r) => s + Math.abs((r.pred_total ?? 0) - (r.total ?? 0)), 0) /
      totalMiss.length
    : null;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">The track record</h1>
          <p className="mt-1 text-zinc-600 dark:text-zinc-400">
            Every prediction gets graded against the final score — the good calls
            and the bad ones. Nothing is deleted, nothing is cherry-picked.
          </p>
        </div>
        <WindowSelect value={win} onChange={setWin} />
      </div>

      {view.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <ProofChip
            metric={pctLabel(correct / view.length)}
            line1="winners called"
            line2={`${correct.toLocaleString()}–${(view.length - correct).toLocaleString()} over this window`}
          />
          <ProofChip
            metric={view.length.toLocaleString()}
            line1="games graded"
            line2={`since ${since}`}
          />
          <ProofChip
            metric={marginMiss != null ? `±${marginMiss.toFixed(1)} runs` : "—"}
            line1="average score miss"
            line2={
              totalMissAvg != null ? `total-runs miss ±${totalMissAvg.toFixed(1)}` : undefined
            }
          />
          <ProofChip
            metric={pctLabel(summary?.batter_hit_call_pct)}
            line1="hitter calls right"
            line2={
              summary
                ? `"gets a hit tonight?" — ${summary.batter_calls_graded.toLocaleString()} graded, all time`
                : undefined
            }
          />
        </div>
      )}
      {rows && view.length === 0 && (
        <p className="text-sm text-zinc-500">No graded games in this window yet.</p>
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

      {view.length > 100 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Under the hood</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            <SkillCurveChart rows={view} />
            <RocChart rows={view} />
            <MarginMissChart rows={view} />
            <ConfusionMatrix rows={view} />
          </div>
        </section>
      )}
      {view.length > 0 && view.length <= 100 && (
        <p className="text-xs text-zinc-400">
          Charts appear once a window has more than 100 graded games.
        </p>
      )}

      <p className="text-xs text-zinc-400">
        The record includes the model's full backtest: for every past game the
        model was trained only on games before it, then its prediction was
        graded — the same rules it plays by every night now.
      </p>
    </div>
  );
}
