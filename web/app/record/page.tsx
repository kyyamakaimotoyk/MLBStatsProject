"use client";

import { useEffect, useState } from "react";
import { Feed, getFeed, getSummary, Summary } from "@/lib/public-api";
import { getJSON } from "@/lib/api";
import { BatterDay, marketComparison, ResultRow } from "@/lib/perf";
import { pctLabel } from "@/lib/copy";
import { useLang } from "@/lib/i18n";
import { PicksStrip, ProofChip, WindowSelect } from "@/components/shared";
import { sinceDate, WindowKey } from "@/lib/windows";
import {
  BatterSkillCurveChart,
  HrWatchCurveChart,
  ConfidenceCurveChart,
  ConfusionMatrix,
  MarginMissChart,
  RocChart,
  SkillCurveChart,
  TotalSkillCurveChart,
} from "@/components/charts";

export default function RecordPage() {
  const { t } = useLang();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [feed, setFeed] = useState<Feed | null>(null);
  const [rows, setRows] = useState<ResultRow[] | null>(null);
  const [batterDays, setBatterDays] = useState<BatterDay[] | null>(null);
  const [win, setWin] = useState<WindowKey>("3m");

  useEffect(() => {
    getSummary().then(setSummary).catch(() => {});
    getFeed(21).then(setFeed).catch(() => {});
    getJSON<ResultRow[]>("/api/public/results").then(setRows).catch(() => {});
    getJSON<BatterDay[]>("/api/public/batter-results").then(setBatterDays).catch(() => {});
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
  const market = marketComparison(view);
  const batterView = (batterDays ?? []).filter((d) => d.game_date >= since);
  const batterCalls = batterView.reduce((s, d) => s + d.n, 0);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t.record.title}</h1>
          <p className="mt-1 text-zinc-600 dark:text-zinc-400">{t.record.subtitle}</p>
        </div>
        <WindowSelect value={win} onChange={setWin} />
      </div>

      {view.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <ProofChip
            metric={pctLabel(correct / view.length)}
            line1={t.record.winnersCalled}
            line2={t.record.wlOver(
              t.common.wl(correct.toLocaleString(), (view.length - correct).toLocaleString()),
            )}
          />
          <ProofChip
            metric={view.length.toLocaleString()}
            line1={t.record.gamesGraded}
            line2={t.record.since(since)}
          />
          <ProofChip
            metric={
              marginMiss != null ? t.common.plusMinusRuns(marginMiss.toFixed(1)) : "—"
            }
            line1={t.record.avgScoreMiss}
            line2={
              totalMissAvg != null ? t.record.totalRunsMiss(totalMissAvg.toFixed(1)) : undefined
            }
          />
          <ProofChip
            metric={pctLabel(summary?.batter_hit_call_pct)}
            line1={t.record.hitterCallsRight}
            line2={
              summary
                ? t.record.hitterCallsSub(summary.batter_calls_graded.toLocaleString())
                : undefined
            }
          />
        </div>
      )}
      {rows && view.length === 0 && (
        <p className="text-sm text-zinc-500">{t.record.noGraded}</p>
      )}

      {rows && view.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t.record.marketTitle}</h2>
          <p className="text-sm text-zinc-500">{t.record.marketSub}</p>
          {market && market.n >= 30 ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <ProofChip
                  metric={`${pctLabel(market.modelAcc)} vs ${pctLabel(market.marketAcc)}`}
                  line1={t.record.usVsMarket}
                  line2={t.record.sameGames(market.n.toLocaleString())}
                />
                <ProofChip
                  metric={
                    market.modelTotalMiss != null && market.marketTotalMiss != null
                      ? `±${market.modelTotalMiss.toFixed(1)} vs ±${market.marketTotalMiss.toFixed(1)}`
                      : "—"
                  }
                  line1={t.record.totalsVsMarket}
                  line2={
                    market.totalsN
                      ? t.record.totalsGames(market.totalsN.toLocaleString())
                      : undefined
                  }
                />
                <ProofChip
                  metric={t.common.wl(
                    market.disagreeWins.toLocaleString(),
                    (market.disagreeN - market.disagreeWins).toLocaleString(),
                  )}
                  line1={t.record.upsetPicks}
                  line2={t.record.upsetSub(market.disagreeN.toLocaleString())}
                />
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <SkillCurveChart rows={view} />
                <TotalSkillCurveChart rows={view} />
              </div>
              <p className="text-xs text-zinc-400">
                {t.record.linesCover(
                  market.n.toLocaleString(),
                  view.length.toLocaleString(),
                )}
              </p>
            </>
          ) : (
            <p className="text-sm text-zinc-500">{t.record.fewLines(market?.n ?? 0)}</p>
          )}
        </section>
      )}

      {batterView.length > 15 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t.record.hittersTitle}</h2>
          <p className="text-sm text-zinc-500">
            {t.record.hittersBody(batterCalls.toLocaleString())}
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <HrWatchCurveChart days={batterView} />
            <BatterSkillCurveChart days={batterView} />
          </div>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t.record.threeWeeksTitle}</h2>
        <p className="text-sm text-zinc-500">{t.record.threeWeeksSub}</p>
        {feed ? <PicksStrip games={gradedGames} /> : <p className="text-sm text-zinc-500">{t.common.loading}</p>}
        {gradedGames.length > 0 && (
          <p className="text-sm text-zinc-500">
            {t.record.stretch(
              t.common.wl(
                gradedGames.filter((g) => g.correct).length.toLocaleString(),
                gradedGames.filter((g) => !g.correct).length.toLocaleString(),
              ),
            )}
          </p>
        )}
      </section>

      {view.length > 100 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t.record.underHoodTitle}</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            <ConfidenceCurveChart rows={view} />
            <RocChart rows={view} />
            <MarginMissChart rows={view} />
            <ConfusionMatrix rows={view} />
          </div>
        </section>
      )}
      {view.length > 0 && view.length <= 100 && (
        <p className="text-xs text-zinc-400">{t.record.chartsAppear}</p>
      )}

      <p className="text-xs text-zinc-400">{t.record.backtestNote}</p>
    </div>
  );
}
