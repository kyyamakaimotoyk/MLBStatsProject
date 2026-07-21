"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { today } from "@/lib/api";
import { BattingGame, getPlayer, PitchingGame, PlayerDetail } from "@/lib/public-api";
import { pctLabel } from "@/lib/copy";
import { useLang } from "@/lib/i18n";
import { poissonTail } from "@/lib/perf";
import { ResultMark } from "@/components/shared";
import { ClearCurveChart, GamePoint, PlayerCountingChart } from "@/components/charts";

// Labels live in lib/translations.ts (t.playerDetail.batStats/pitStats/windows),
// keyed by these stat keys.
const BAT_STATS = [
  { key: "h", exp: "exp_h", max: 5 },
  { key: "tb", exp: "exp_tb", max: 8 },
  { key: "hr", exp: "exp_hr", max: 3 },
  { key: "bb", exp: "exp_bb", max: 4 },
  { key: "k", exp: "exp_k", max: 5 },
  { key: "rbi", exp: null, max: 6 },
  { key: "r", exp: null, max: 4 },
] as const;

const PIT_STATS = [
  { key: "k", max: 12 },
  { key: "er", max: 8 },
  { key: "innings", max: 9 },
] as const;

const WINDOWS = [
  { key: "2w", days: 14 },
  { key: "1m", days: 31 },
  { key: "season", days: 365 },
] as const;

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-zinc-200 px-3 py-2 dark:border-zinc-800">
      <div className="text-lg font-bold" style={{ color: "var(--accent-mark)" }}>
        {value}
      </div>
      <div className="text-xs text-zinc-500">{label}</div>
    </div>
  );
}

function windowGames<T extends { game_date: string; season: number }>(
  games: T[],
  win: (typeof WINDOWS)[number]["key"],
): T[] {
  if (win === "season") {
    const latest = Math.max(...games.map((g) => g.season));
    return games.filter((g) => g.season === latest);
  }
  const days = WINDOWS.find((w) => w.key === win)!.days;
  const since = new Date(new Date(`${today()}T00:00:00Z`).getTime() - days * 86400000)
    .toISOString()
    .slice(0, 10);
  return games.filter((g) => g.game_date >= since);
}

export default function PlayerPage() {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Loading…</p>}>
      <PlayerContent />
    </Suspense>
  );
}

function PlayerContent() {
  const { t } = useLang();
  const id = useSearchParams().get("id");
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [batStat, setBatStat] = useState<(typeof BAT_STATS)[number]["key"]>("h");
  const [batWin, setBatWin] = useState<(typeof WINDOWS)[number]["key"]>("1m");
  const [pitStat, setPitStat] = useState<(typeof PIT_STATS)[number]["key"]>("k");
  const [pitWin, setPitWin] = useState<(typeof WINDOWS)[number]["key"]>("season");
  const [lineStat, setLineStat] = useState<(typeof BAT_STATS)[number]["key"]>("h");
  const [line, setLine] = useState(2);

  useEffect(() => {
    if (id) getPlayer(Number(id)).then(setPlayer).catch((e) => setError(String(e)));
  }, [id]);

  const batDef = BAT_STATS.find((s) => s.key === batStat)!;
  const lineDef = BAT_STATS.find((s) => s.key === lineStat)!;

  const batPoints: GamePoint[] = useMemo(() => {
    const games = windowGames(player?.batting?.games ?? [], batWin);
    return [...games].reverse().map((g) => ({
      date: g.game_date,
      home: g.home,
      away: g.away,
      home_score: g.home_score,
      away_score: g.away_score,
      actual: g[batDef.key] as number | null,
      expected: batDef.exp ? (g[batDef.exp as keyof BattingGame] as number | null) : null,
    }));
  }, [player, batWin, batDef]);

  const pitPoints: GamePoint[] = useMemo(() => {
    const games = windowGames(player?.pitching?.games ?? [], pitWin);
    return [...games].reverse().map((g) => ({
      date: g.game_date,
      home: g.home,
      away: g.away,
      home_score: g.home_score,
      away_score: g.away_score,
      actual:
        pitStat === "innings"
          ? g.outs != null
            ? Math.round((g.outs / 3) * 10) / 10
            : null
          : (g[pitStat as keyof PitchingGame] as number | null),
    }));
  }, [player, pitWin, pitStat]);

  const clearData = useMemo(() => {
    const games = windowGames(player?.batting?.games ?? [], "season").filter(
      (g) => g[lineDef.key] != null,
    );
    const values = games.map((g) => g[lineDef.key] as number);
    const empirical = [];
    for (let k = 0; k <= lineDef.max; k += 1) {
      empirical.push({ k, share: values.length ? values.filter((v) => v >= k).length / values.length : 0 });
    }
    let model = null;
    const lp = player?.latest_pred;
    const expKey = lineDef.exp as keyof NonNullable<PlayerDetail["latest_pred"]> | null;
    if (lp && expKey && lp[expKey] != null) {
      const lambda = Number(lp[expKey]);
      model = empirical.map(({ k }) => ({ k, share: poissonTail(lambda, k) }));
    }
    return { empirical, model, values };
  }, [player, lineDef]);

  if (error) return <p className="text-sm text-zinc-500">{t.playerDetail.notFound}</p>;
  if (!player) return <p className="text-sm text-zinc-500">{t.common.loading}</p>;

  const bs = player.batting?.season;
  const ps = player.pitching?.season;
  const avg3 = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(3).replace(/^0/, ""));
  const overShare = clearData.empirical.find((e) => e.k === line)?.share ?? null;
  const modelShare = clearData.model?.find((e) => e.k === line)?.share ?? null;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">{player.name}</h1>
        <p className="mt-1 text-sm text-zinc-500">{player.position}</p>
      </div>

      {bs && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t.playerDetail.hitting(bs.season)}</h2>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-8">
            <Tile label={t.playerDetail.tiles.avg} value={avg3(bs.avg)} />
            <Tile label={t.playerDetail.tiles.obp} value={avg3(bs.obp)} />
            <Tile label={t.playerDetail.tiles.slg} value={avg3(bs.slg)} />
            <Tile label={t.playerDetail.tiles.ops} value={avg3(bs.ops)} />
            <Tile label={t.playerDetail.tiles.hr} value={`${bs.hr}`} />
            <Tile label={t.playerDetail.tiles.rbi} value={`${bs.rbi}`} />
            <Tile label={t.playerDetail.tiles.sb} value={`${bs.sb}`} />
            <Tile label={t.playerDetail.tiles.games} value={`${bs.games}`} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={batStat}
              onChange={(e) => setBatStat(e.target.value as typeof batStat)}
              className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              {BAT_STATS.map((s) => (
                <option key={s.key} value={s.key}>
                  {t.playerDetail.batStats[s.key]}
                </option>
              ))}
            </select>
            <select
              value={batWin}
              onChange={(e) => setBatWin(e.target.value as typeof batWin)}
              className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              {WINDOWS.map((w) => (
                <option key={w.key} value={w.key}>
                  {t.playerDetail.windows[w.key]}
                </option>
              ))}
            </select>
          </div>
          <PlayerCountingChart points={batPoints} statLabel={t.playerDetail.batStats[batDef.key]} />
        </section>
      )}

      {bs && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t.playerDetail.clearTitle}</h2>
          <p className="text-sm text-zinc-500">{t.playerDetail.clearSub(player.name)}</p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={lineStat}
              onChange={(e) => {
                setLineStat(e.target.value as typeof lineStat);
                setLine(1);
              }}
              className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              {BAT_STATS.filter((s) => s.exp).map((s) => (
                <option key={s.key} value={s.key}>
                  {t.playerDetail.batStats[s.key]}
                </option>
              ))}
            </select>
            <label className="text-sm text-zinc-500">{t.playerDetail.atLeast}</label>
            <input
              type="number"
              min={0}
              max={lineDef.max}
              value={line}
              onChange={(e) => setLine(Math.max(0, Math.min(lineDef.max, Number(e.target.value))))}
              className="w-16 rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Tile label={t.playerDetail.gamesThisSeason} value={`${clearData.values.length}`} />
            <Tile
              label={t.playerDetail.avgPerGame}
              value={
                clearData.values.length
                  ? (clearData.values.reduce((a, b) => a + b, 0) / clearData.values.length).toFixed(2)
                  : "—"
              }
            />
            <Tile label={t.playerDetail.clearedTile(line)} value={pctLabel(overShare)} />
            <Tile
              label={t.playerDetail.modelNextGame}
              value={modelShare != null ? pctLabel(modelShare) : "—"}
            />
          </div>
          <ClearCurveChart
            empirical={clearData.empirical}
            model={clearData.model}
            line={line}
            statLabel={t.playerDetail.batStats[lineDef.key]}
          />
        </section>
      )}

      {ps && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t.playerDetail.pitching(ps.season)}</h2>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-7">
            <Tile label={t.playerDetail.tiles.era} value={ps.era != null ? ps.era.toFixed(2) : "—"} />
            <Tile label={t.playerDetail.tiles.whip} value={ps.whip != null ? ps.whip.toFixed(2) : "—"} />
            <Tile label={t.playerDetail.tiles.k9} value={ps.k9 != null ? ps.k9.toFixed(1) : "—"} />
            <Tile label={t.playerDetail.tiles.so} value={`${ps.so}`} />
            <Tile label={t.playerDetail.tiles.ip} value={ps.ip.toFixed(1)} />
            <Tile label={t.playerDetail.tiles.starts} value={`${ps.starts}`} />
            <Tile label={t.playerDetail.tiles.games} value={`${ps.games}`} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={pitStat}
              onChange={(e) => setPitStat(e.target.value as typeof pitStat)}
              className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              {PIT_STATS.map((s) => (
                <option key={s.key} value={s.key}>
                  {t.playerDetail.pitStats[s.key]}
                </option>
              ))}
            </select>
            <select
              value={pitWin}
              onChange={(e) => setPitWin(e.target.value as typeof pitWin)}
              className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              {WINDOWS.map((w) => (
                <option key={w.key} value={w.key}>
                  {t.playerDetail.windows[w.key]}
                </option>
              ))}
            </select>
          </div>
          <PlayerCountingChart
            points={pitPoints}
            statLabel={t.playerDetail.pitStats[pitStat]}
          />
        </section>
      )}

      {player.batting && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">{t.playerDetail.recentTitle}</h2>
          <div className="overflow-x-auto rounded border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-sm">
              <thead className="bg-zinc-100 text-left dark:bg-zinc-900">
                <tr>
                  <th className="px-3 py-2">{t.playerDetail.colDate}</th>
                  <th className="px-3 py-2">{t.playerDetail.colGame}</th>
                  <th className="px-3 py-2 text-right">H</th>
                  <th className="px-3 py-2 text-right">HR</th>
                  <th className="px-3 py-2 text-right">TB</th>
                  <th className="px-3 py-2 text-right">BB</th>
                  <th className="px-3 py-2 text-right">K</th>
                  <th className="px-3 py-2 text-right">{t.playerDetail.colSaidHit}</th>
                  <th className="px-3 py-2 text-right">{t.playerDetail.colRight}</th>
                </tr>
              </thead>
              <tbody>
                {player.batting.games.slice(0, 20).map((g, i) => {
                  const gotHit = g.h != null ? g.h >= 1 : null;
                  const calledHit = g.p_hit != null ? g.p_hit >= 0.5 : null;
                  const correct =
                    gotHit != null && calledHit != null ? calledHit === gotHit : null;
                  return (
                    <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                      <td className="px-3 py-2 text-zinc-500">{g.game_date}</td>
                      <td className="px-3 py-2">
                        {g.away} @ {g.home}
                      </td>
                      <td className="px-3 py-2 text-right font-medium">{g.h ?? "—"}</td>
                      <td className="px-3 py-2 text-right">{g.hr ?? "—"}</td>
                      <td className="px-3 py-2 text-right">{g.tb ?? "—"}</td>
                      <td className="px-3 py-2 text-right">{g.bb ?? "—"}</td>
                      <td className="px-3 py-2 text-right">{g.k ?? "—"}</td>
                      <td className="px-3 py-2 text-right text-zinc-600 dark:text-zinc-300">
                        {g.p_hit != null ? pctLabel(g.p_hit) : "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <ResultMark correct={correct} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
