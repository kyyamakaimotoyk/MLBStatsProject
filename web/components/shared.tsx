"use client";

import { FeedGame } from "@/lib/public-api";
import { copy, finalScore, pctLabel, scoreCall } from "@/lib/copy";

export function ProofChip({
  metric,
  line1,
  line2,
}: {
  metric: string;
  line1: string;
  line2?: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="text-2xl font-bold text-orange-500">{metric}</div>
      <div className="text-xs text-zinc-500">{line1}</div>
      {line2 && <div className="text-xs text-zinc-500">{line2}</div>}
    </div>
  );
}

export function ResultMark({ correct }: { correct: boolean | null }) {
  if (correct == null) return <span className="text-zinc-400">—</span>;
  return correct ? (
    <span className="font-bold text-emerald-600 dark:text-emerald-400">✓</span>
  ) : (
    <span className="font-bold text-rose-600 dark:text-rose-400">✗</span>
  );
}

export function PicksTable({ games }: { games: FeedGame[] }) {
  return (
    <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-sm">
        <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
          <tr>
            <th className="px-3 py-2">{copy.table.matchup}</th>
            <th className="px-3 py-2">{copy.table.pick}</th>
            <th className="px-3 py-2 text-right">{copy.table.winChance}</th>
            <th className="px-3 py-2 text-right">{copy.table.scoreCall}</th>
            <th className="px-3 py-2 text-right">{copy.table.totalRuns}</th>
            <th className="px-3 py-2 text-right">{copy.table.final}</th>
            <th className="px-3 py-2 text-right">{copy.table.result}</th>
          </tr>
        </thead>
        <tbody>
          {games.map((g) => (
            <tr
              key={g.game_pk}
              className={`border-t border-zinc-200 dark:border-zinc-800 ${
                g.correct == null
                  ? ""
                  : g.correct
                    ? "bg-emerald-50 dark:bg-emerald-950/30"
                    : "bg-rose-50 dark:bg-rose-950/30"
              }`}
            >
              <td className="px-3 py-2 font-medium">
                {g.away} @ {g.home}
              </td>
              <td className="px-3 py-2">
                <span className="font-semibold text-orange-500">{g.pick}</span>
                {g.pick_chance <= 0.55 && (
                  <span className="ml-2 rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] uppercase text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    {copy.table.coinFlip}
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right">{pctLabel(g.pick_chance)}</td>
              <td className="px-3 py-2 text-right text-zinc-600 dark:text-zinc-300">
                {scoreCall(g.home, g.away, g.pred_home_runs, g.pred_away_runs)}
              </td>
              <td className="px-3 py-2 text-right">
                {g.pred_total != null ? g.pred_total.toFixed(1) : "—"}
              </td>
              <td className="px-3 py-2 text-right text-zinc-500">
                {g.is_final
                  ? finalScore(g.home, g.away, g.home_score, g.away_score)
                  : (g.status ?? "—")}
              </td>
              <td className="px-3 py-2 text-right">
                <ResultMark correct={g.correct} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PicksStrip({ games }: { games: FeedGame[] }) {
  const graded = games.filter((g) => g.correct != null);
  return (
    <div className="flex flex-wrap gap-1">
      {graded.map((g) => (
        <span
          key={g.game_pk}
          title={`${g.away} @ ${g.home}: picked ${g.pick} (${pctLabel(g.pick_chance)})`}
          className={`inline-flex h-6 w-6 items-center justify-center rounded text-xs font-bold text-white ${
            g.correct ? "bg-emerald-500" : "bg-rose-500"
          }`}
        >
          {g.correct ? "✓" : "✗"}
        </span>
      ))}
    </div>
  );
}
