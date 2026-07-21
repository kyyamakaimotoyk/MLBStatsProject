"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Feed, getFeed, getSummary, Summary } from "@/lib/public-api";
import { getJSON, today } from "@/lib/api";
import { ResultRow } from "@/lib/perf";
import { pctLabel } from "@/lib/copy";
import { useLang } from "@/lib/i18n";
import { PicksTable, ProofChip, WindowSelect } from "@/components/shared";
import { daysBack, sinceDate, WindowKey } from "@/lib/windows";

export default function HomePage() {
  const { t } = useLang();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [rows, setRows] = useState<ResultRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDays, setShowDays] = useState(4);
  const [win, setWin] = useState<WindowKey>("1m");

  useEffect(() => {
    getSummary().then(setSummary).catch(() => {});
    getJSON<ResultRow[]>("/api/public/results").then(setRows).catch(() => {});
  }, []);

  useEffect(() => {
    setFeed(null);
    getFeed(Math.min(daysBack(win), 90))
      .then(setFeed)
      .catch((e) => setError(String(e)));
  }, [win]);

  const todayStr = today(); // site clock: US Eastern, not the viewer's timezone
  const tonight = feed?.days.find((d) => d.date === todayStr);
  const past = (feed?.days ?? []).filter((d) => d.date !== todayStr);

  return (
    <div className="space-y-10">
      <section className="space-y-4 pt-4 text-center">
        <h1 className="text-3xl font-bold">{t.site.tagline}</h1>
        <p className="mx-auto max-w-2xl text-zinc-600 dark:text-zinc-400">
          {t.site.subtitle}
        </p>
        <div className="flex justify-center gap-3">
          <a
            href="#tonight"
            className="rounded px-4 py-2 text-sm font-semibold hover:opacity-90"
            style={{ backgroundColor: "var(--btn-bg)", color: "var(--btn-text)" }}
          >
            {t.site.ctaTonight}
          </a>
          <Link
            href="/record"
            className="rounded border border-zinc-300 px-4 py-2 text-sm font-semibold hover:border-[var(--accent-mark)] dark:border-zinc-700"
          >
            {t.site.ctaRecord}
          </Link>
        </div>
        {summary && (
          <div className="mx-auto flex max-w-2xl flex-wrap justify-center gap-3 pt-2">
            <ProofChip
              metric={pctLabel(
                summary.last30_wins / Math.max(summary.last30_wins + summary.last30_losses, 1),
              )}
              line1={t.proof.winners(t.proof.last30)}
              line2={t.common.wl(
                summary.last30_wins.toLocaleString(),
                summary.last30_losses.toLocaleString(),
              )}
            />
            <ProofChip
              metric={t.common.plusMinusRuns(summary.avg_score_error.toFixed(1))}
              line1={t.proof.scoreMiss(t.proof.sinceYear(summary.since.slice(0, 4)))}
            />
            <ProofChip
              metric={summary.games_graded.toLocaleString()}
              line1={t.proof.logged}
              line2={t.proof.loggedSub}
            />
          </div>
        )}
      </section>

      <section id="tonight" className="space-y-3">
        <h2 className="text-lg font-semibold">
          {tonight ? t.home.predictionsFor(tonight.date) : t.site.noTonight}
        </h2>
        {feed && !tonight && (
          <p className="text-sm text-zinc-500">{t.site.noTonightSub}</p>
        )}
        {error && <p className="text-sm text-zinc-500">{t.home.errLate}</p>}
        {!feed && !error && <p className="text-sm text-zinc-500">{t.home.loadingTonight}</p>}
        {tonight && <PicksTable games={tonight.games} />}
        {tonight && tonight.games.some((g) => g.watch.length > 0) && (
          <div className="rounded border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <div className="mb-1 font-semibold text-zinc-600 dark:text-zinc-400">
              {t.home.hittersToWatch}
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
                    {t.home.toHomer(pctLabel(w.p_hr))}
                  </span>
                ))}
            </div>
          </div>
        )}
      </section>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{t.home.recentResults}</h2>
          <WindowSelect value={win} onChange={setWin} />
        </div>
        {rows && (
          <WindowRecordLine rows={rows} winKey={win} />
        )}
        {past.slice(0, showDays).map((d) => (
          <div key={d.date} className="space-y-2">
            <h3 className="text-sm font-semibold text-zinc-500">{d.date}</h3>
            <PicksTable games={d.games} />
          </div>
        ))}
        {past.length > showDays && (
          <button
            onClick={() => setShowDays((n) => n + 4)}
            className="rounded border border-zinc-300 px-3 py-1.5 text-sm hover:border-[var(--accent-mark)] dark:border-zinc-700"
          >
            {t.home.showMoreDays}
          </button>
        )}
        {daysBack(win) > 90 && (
          <p className="text-xs text-zinc-400">
            {t.home.dayTablesNote}
            <a href="/record" className="underline">
              {t.home.dayTablesLink}
            </a>
            {t.home.dayTablesNoteEnd}
          </p>
        )}
      </section>

      <section className="grid gap-4 border-t border-zinc-200 pt-8 sm:grid-cols-4 dark:border-zinc-800">
        {t.steps.map((s, i) => (
          <div key={s.title} className="space-y-1">
            <div className="text-xs font-bold" style={{ color: "var(--accent-text)" }}>
              {t.home.stepLabel(i + 1)}
            </div>
            <div className="font-semibold">{s.title}</div>
            <p className="text-sm text-zinc-500">{s.body}</p>
          </div>
        ))}
      </section>

      <p className="pb-4 text-center text-xs text-zinc-400">
        {t.site.clockNote} {t.site.disclaimer}
      </p>
    </div>
  );
}

function WindowRecordLine({ rows, winKey }: { rows: ResultRow[]; winKey: WindowKey }) {
  const { t } = useLang();
  const since = sinceDate(winKey);
  const view = rows.filter((r) => r.game_date >= since);
  if (view.length === 0) return null;
  const correct = view.filter((r) => (r.p_home >= 0.5) === r.home_won).length;
  return (
    <p className="text-sm text-zinc-600 dark:text-zinc-400">
      {t.home.windowRecordBefore}
      <span className="font-semibold">
        {t.common.wl(correct.toLocaleString(), (view.length - correct).toLocaleString())}
      </span>
      {t.home.windowRecordAfter(pctLabel(correct / view.length), view.length.toLocaleString())}
    </p>
  );
}
