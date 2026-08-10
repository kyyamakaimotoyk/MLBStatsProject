"use client";

import { useState } from "react";
import { FeedGame } from "@/lib/public-api";
import { finalScore, marketCall, pctLabel, scoreCall } from "@/lib/copy";
import { useLang } from "@/lib/i18n";
import { WINDOW_KEYS, WindowKey } from "@/lib/windows";

export function WindowSelect({
  value,
  onChange,
}: {
  value: WindowKey;
  onChange: (k: WindowKey) => void;
}) {
  const { t } = useLang();
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as WindowKey)}
      className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
    >
      {WINDOW_KEYS.map((key) => (
        <option key={key} value={key}>
          {t.windows[key]}
        </option>
      ))}
    </select>
  );
}

export type TierKey = "all" | "strong" | "lean";

const TIER_KEYS: TierKey[] = ["all", "strong", "lean"];

export function TierSelect({
  value,
  onChange,
}: {
  value: TierKey;
  onChange: (k: TierKey) => void;
}) {
  const { t } = useLang();
  return (
    <div className="flex items-center gap-1 text-xs" role="group">
      {TIER_KEYS.map((k) => (
        <button
          key={k}
          type="button"
          aria-pressed={value === k}
          onClick={() => onChange(k)}
          className={
            value === k
              ? "rounded border border-[var(--accent-mark)] px-1.5 py-0.5 font-semibold"
              : "rounded border border-transparent px-1.5 py-0.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
          }
          style={value === k ? { color: "var(--accent-text)" } : undefined}
        >
          {t.record.tiers[k]}
        </button>
      ))}
    </div>
  );
}

export function StrongBadge() {
  const { t } = useLang();
  return (
    <span
      className="ml-2 rounded border border-[var(--accent-mark)] px-1.5 py-0.5 text-[10px] font-semibold uppercase"
      style={{ color: "var(--accent-text)" }}
    >
      {t.table.strong}
    </span>
  );
}

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
      <div className="text-2xl font-bold" style={{ color: "var(--accent-mark)" }}>
        {metric}
      </div>
      <div className="text-xs text-zinc-500">{line1}</div>
      {line2 && <div className="text-xs text-zinc-500">{line2}</div>}
    </div>
  );
}

export function ResultMark({ correct }: { correct: boolean | null }) {
  if (correct == null) return <span className="text-zinc-400">—</span>;
  return (
    <span
      className="font-bold"
      style={{ color: correct ? "var(--good-text)" : "var(--bad-text)" }}
    >
      {correct ? "✓" : "✗"}
    </span>
  );
}

export function PicksTable({ games }: { games: FeedGame[] }) {
  const { t } = useLang();
  return (
    <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-sm">
        <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
          <tr>
            <th className="px-3 py-2">{t.table.matchup}</th>
            <th className="px-3 py-2">{t.table.pick}</th>
            <th className="px-3 py-2 text-right">{t.table.winChance}</th>
            <th className="px-3 py-2 text-right">{t.table.scoreCall}</th>
            <th className="px-3 py-2 text-right">{t.table.totalRuns}</th>
            <th className="px-3 py-2 text-right">{t.table.marketFavorite}</th>
            <th className="px-3 py-2 text-right">{t.table.marketTotal}</th>
            <th className="px-3 py-2 text-right">{t.table.final}</th>
            <th className="px-3 py-2 text-right">{t.table.result}</th>
          </tr>
        </thead>
        <tbody>
          {games.map((g) => (
            <tr
              key={g.game_pk}
              className="border-t border-zinc-200 dark:border-zinc-800"
              style={
                g.correct == null
                  ? undefined
                  : {
                      backgroundColor: `color-mix(in oklab, ${
                        g.correct ? "var(--good-bg)" : "var(--bad-bg)"
                      } 70%, transparent)`,
                    }
              }
            >
              <td className="px-3 py-2 font-medium">
                {g.away} @ {g.home}
              </td>
              <td className="px-3 py-2">
                <span className="font-semibold" style={{ color: "var(--accent-text)" }}>
                  {g.pick}
                </span>
                {g.tier === "strong" && <StrongBadge />}
                {g.pick_chance <= 0.55 && (
                  <span className="ml-2 rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] uppercase text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                    {t.table.coinFlip}
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
                {marketCall(g.home, g.away, g.market_p_home, t.table.even)}
              </td>
              <td className="px-3 py-2 text-right text-zinc-500">
                {g.market_total != null ? g.market_total.toFixed(1) : "—"}
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
  const { t } = useLang();
  const graded = games.filter((g) => g.correct != null);
  const [selected, setSelected] = useState<FeedGame | null>(null);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {graded.map((g) => (
          <button
            key={g.game_pk}
            type="button"
            onClick={() => setSelected(selected?.game_pk === g.game_pk ? null : g)}
            title={t.strip.chipTitle(g.away, g.home, g.pick, pctLabel(g.pick_chance))}
            aria-label={t.strip.chipAria(g.game_date, g.away, g.home, Boolean(g.correct))}
            className="inline-flex h-6 w-6 items-center justify-center rounded text-xs font-bold"
            style={{
              backgroundColor: g.correct ? "var(--good-bg)" : "var(--bad-bg)",
              color: g.correct ? "var(--good-text)" : "var(--bad-text)",
              outline:
                selected?.game_pk === g.game_pk
                  ? "2px solid var(--accent-mark)"
                  : undefined,
              outlineOffset: 1,
            }}
          >
            {g.correct ? "✓" : "✗"}
          </button>
        ))}
      </div>
      {selected && (
        <div className="rounded border border-zinc-200 bg-white px-4 py-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center justify-between gap-3">
            <span className="font-semibold">
              {selected.away} @ {selected.home}
              <span className="ml-2 font-normal text-zinc-500">{selected.game_date}</span>
            </span>
            <span
              className="font-bold"
              style={{
                color: selected.correct ? "var(--good-text)" : "var(--bad-text)",
              }}
            >
              {selected.correct ? t.strip.gotIt : t.strip.missed}
            </span>
          </div>
          <div className="mt-1 text-zinc-600 dark:text-zinc-300">
            {t.strip.pickedBefore}
            <span className="font-semibold" style={{ color: "var(--accent-text)" }}>
              {selected.pick}
            </span>
            {t.strip.pickedAfter(pctLabel(selected.pick_chance))}
          </div>
          <div className="text-zinc-600 dark:text-zinc-300">
            {t.strip.scoreCallLabel}{" "}
            <span className="font-semibold">
              {scoreCall(
                selected.home,
                selected.away,
                selected.pred_home_runs,
                selected.pred_away_runs,
              )}
            </span>
            {" · "}
            {t.strip.finalLabel}{" "}
            <span className="font-semibold">
              {finalScore(selected.home, selected.away, selected.home_score, selected.away_score)}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
