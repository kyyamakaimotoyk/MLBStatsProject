// Client-side metric derivation from flat graded rows (the hoopmodel
// lib/perf.ts pattern): the API ships raw rows, the browser computes charts.

export type ResultRow = {
  game_date: string;
  p_home: number;
  pred_margin: number;
  pred_total: number | null;
  margin: number;
  total: number | null;
  home_won: boolean;
  // Strong/Lean pick tier, resolved by the pipeline (core/tiers.py rule:
  // calibrated win chance of the pick >= 58%). Optional so charts degrade
  // if the API hasn't been redeployed with it yet.
  tier?: "strong" | "lean";
  // The betting market's pregame view, when a line was captured: no-vig
  // closing win probability and the closing total line (benchmarks only,
  // never model inputs).
  market_p_home: number | null;
  market_total: number | null;
};

export function confidenceCurve(rows: ResultRow[]) {
  // accuracy + share of games kept, when only counting picks at or above a
  // minimum win chance
  const out: { threshold: number; accuracy: number; coverage: number }[] = [];
  for (let t = 50; t <= 72; t += 1) {
    const kept = rows.filter((r) => Math.max(r.p_home, 1 - r.p_home) * 100 >= t);
    if (kept.length < 30) break;
    const correct = kept.filter((r) => (r.p_home >= 0.5) === r.home_won).length;
    out.push({
      threshold: t,
      accuracy: (100 * correct) / kept.length,
      coverage: (100 * kept.length) / rows.length,
    });
  }
  return out;
}

// Thin a date series for rendering (markers need breathing room), always
// keeping the last point so the curve ends where the record does.
function thinSeries<T>(points: T[], max = 120): T[] {
  const step = Math.max(1, Math.ceil(points.length / max));
  return points.filter((_, i) => i % step === 0 || i === points.length - 1);
}

// Skill curve (the hoopmodel chart): running total of correct picks minus
// half the games played, per day. A coin-flipper drifts along zero; skill
// climbs. Both series count only games with a market line — and skip games
// the market prices dead even (no favorite) — so the market-favorite
// benchmark is on the same footing.
export function skillCurve(rows: ResultRow[]) {
  const lined = rows.filter((r) => r.market_p_home != null && r.market_p_home !== 0.5);
  const byDate = new Map<string, { model: number; market: number; n: number }>();
  for (const r of lined) {
    const d = byDate.get(r.game_date) ?? { model: 0, market: 0, n: 0 };
    d.n += 1;
    if ((r.p_home >= 0.5) === r.home_won) d.model += 1;
    if ((r.market_p_home! > 0.5) === r.home_won) d.market += 1;
    byDate.set(r.game_date, d);
  }
  let model = 0;
  let market = 0;
  const out = [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, d]) => {
      model += d.model - d.n / 2;
      market += d.market - d.n / 2;
      return {
        date,
        model: Math.round(model * 10) / 10,
        market: Math.round(market * 10) / 10,
      };
    });
  return thinSeries(out);
}

// The same running total for the "gets a hit tonight?" calls. Coin-flip is
// the wrong opponent here (most starters get a hit most nights), so the
// same-footing benchmark is the lazy rule that says yes for everyone.
export type BatterDay = {
  game_date: string;
  n: number;
  model_correct: number;
  always_yes_correct: number;
  hr_base_hits: number;
  hr_watch_n: number;
  hr_watch_hits: number;
};

export function batterSkillCurve(days: BatterDay[]) {
  // Plotted as the margin over the lazy rule (it IS the zero line): both
  // series beat coin-flip by thousands of calls, so drawing them raw hides
  // the only gap that means anything.
  let edge = 0;
  const out = [...days]
    .sort((a, b) => a.game_date.localeCompare(b.game_date))
    .map((d) => {
      edge += d.model_correct - d.always_yes_correct;
      return { date: d.game_date, edge };
    });
  return thinSeries(out);
}

// HR watch: each day the model names its five likeliest home-run hitters.
// The fair benchmark is chance — five random starters homer at that day's
// base rate — so the curve accumulates homers by our five above that pace.
export function hrWatchCurve(days: BatterDay[]) {
  let edge = 0;
  const out = [...days]
    .filter((d) => d.hr_watch_n > 0 && d.n > 0)
    .sort((a, b) => a.game_date.localeCompare(b.game_date))
    .map((d) => {
      edge += d.hr_watch_hits - (d.hr_watch_n * d.hr_base_hits) / d.n;
      return { date: d.game_date, edge: Math.round(edge * 10) / 10 };
    });
  return thinSeries(out);
}

// The same running total for the over/under: our side of the market's total
// line, right calls minus half the games. Pushes (final total exactly on the
// line) grade nobody, and a predicted total exactly on the line is no call.
export function totalSkillCurve(rows: ResultRow[]) {
  const graded = rows.filter(
    (r) =>
      r.pred_total != null &&
      r.total != null &&
      r.market_total != null &&
      r.total !== r.market_total &&
      r.pred_total !== r.market_total,
  );
  const byDate = new Map<string, { c: number; n: number }>();
  for (const r of graded) {
    const d = byDate.get(r.game_date) ?? { c: 0, n: 0 };
    d.n += 1;
    if ((r.pred_total! > r.market_total!) === (r.total! > r.market_total!)) d.c += 1;
    byDate.set(r.game_date, d);
  }
  let cum = 0;
  const out = [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([date, d]) => {
      cum += d.c - d.n / 2;
      return { date, model: Math.round(cum * 10) / 10 };
    });
  return thinSeries(out);
}

// Head-to-head vs the market on the games where we have a pregame line:
// winner accuracy for both, total-runs miss for both, and the record when
// the model and the market favorite disagree.
export function marketComparison(rows: ResultRow[]) {
  const lined = rows.filter((r) => r.market_p_home != null);
  if (lined.length === 0) return null;
  const modelRight = (r: ResultRow) => (r.p_home >= 0.5) === r.home_won;
  const marketRight = (r: ResultRow) => (r.market_p_home! >= 0.5) === r.home_won;
  // A dead-even line has no favorite to disagree with (skillCurve skips
  // those games for the same reason).
  const disagree = lined.filter(
    (r) => r.market_p_home !== 0.5 && (r.p_home >= 0.5) !== (r.market_p_home! >= 0.5),
  );
  const totals = lined.filter(
    (r) => r.pred_total != null && r.total != null && r.market_total != null,
  );
  const miss = (f: (r: ResultRow) => number) =>
    totals.length ? totals.reduce((s, r) => s + f(r), 0) / totals.length : null;
  return {
    n: lined.length,
    modelAcc: lined.filter(modelRight).length / lined.length,
    marketAcc: lined.filter(marketRight).length / lined.length,
    disagreeN: disagree.length,
    disagreeWins: disagree.filter(modelRight).length,
    modelTotalMiss: miss((r) => Math.abs(r.pred_total! - r.total!)),
    marketTotalMiss: miss((r) => Math.abs(r.market_total! - r.total!)),
    totalsN: totals.length,
  };
}

export function roc(rows: ResultRow[]) {
  const sorted = [...rows].sort((a, b) => b.p_home - a.p_home);
  const pos = sorted.filter((r) => r.home_won).length;
  const neg = sorted.length - pos;
  let tp = 0;
  let fp = 0;
  const points: { fpr: number; tpr: number }[] = [{ fpr: 0, tpr: 0 }];
  let auc = 0;
  let prevFpr = 0;
  let prevTpr = 0;
  for (const r of sorted) {
    if (r.home_won) tp += 1;
    else fp += 1;
    const fpr = (100 * fp) / neg;
    const tpr = (100 * tp) / pos;
    auc += ((fpr - prevFpr) / 100) * ((tpr + prevTpr) / 200);
    points.push({ fpr, tpr });
    prevFpr = fpr;
    prevTpr = tpr;
  }
  // thin the curve for rendering (markers need breathing room)
  const step = Math.max(1, Math.floor(points.length / 60));
  return { points: points.filter((_, i) => i % step === 0 || i === points.length - 1), auc };
}

export function confusion(rows: ResultRow[]) {
  let homePickHomeWin = 0;
  let homePickAwayWin = 0;
  let awayPickHomeWin = 0;
  let awayPickAwayWin = 0;
  for (const r of rows) {
    const pickedHome = r.p_home >= 0.5;
    if (pickedHome && r.home_won) homePickHomeWin += 1;
    else if (pickedHome && !r.home_won) homePickAwayWin += 1;
    else if (!pickedHome && r.home_won) awayPickHomeWin += 1;
    else awayPickAwayWin += 1;
  }
  return { homePickHomeWin, homePickAwayWin, awayPickHomeWin, awayPickAwayWin };
}

// P(X >= k) for X ~ Poisson(lambda): the model-implied chance of clearing a
// counting-stat line, given the player model's expected value for tonight.
export function poissonTail(lambda: number, k: number): number {
  if (k <= 0) return 1;
  let term = Math.exp(-lambda);
  let cdf = term;
  for (let i = 1; i < k; i += 1) {
    term *= lambda / i;
    cdf += term;
  }
  return Math.max(0, 1 - cdf);
}

export function marginMissHistogram(rows: ResultRow[]) {
  // signed miss: predicted margin minus actual margin, 1-run bins, clamped
  const bins = new Map<number, number>();
  for (let b = -8; b <= 8; b += 1) bins.set(b, 0);
  for (const r of rows) {
    const miss = Math.max(-8, Math.min(8, Math.round(r.pred_margin - r.margin)));
    bins.set(miss, (bins.get(miss) ?? 0) + 1);
  }
  return [...bins.entries()].map(([bin, count]) => ({
    bin,
    share: (100 * count) / rows.length,
  }));
}
