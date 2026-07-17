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
  // The betting market's pregame view, when a line was captured: no-vig
  // closing win probability and the closing total line (benchmarks only,
  // never model inputs).
  market_p_home: number | null;
  market_total: number | null;
};

export function skillCurve(rows: ResultRow[]) {
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

// Over/under skill curve: grade the model's side of the market's total line,
// counting only games where the model's total is at least `edge` runs off the
// line. Pushes (final total exactly on the line) grade nobody and are dropped.
export function totalSkillCurve(rows: ResultRow[]) {
  const graded = rows.filter(
    (r) =>
      r.pred_total != null &&
      r.total != null &&
      r.market_total != null &&
      r.total !== r.market_total &&
      r.pred_total !== r.market_total,
  );
  const out: { edge: number; accuracy: number; coverage: number }[] = [];
  for (let e = 0; e <= 3; e += 0.25) {
    const kept = graded.filter((r) => Math.abs(r.pred_total! - r.market_total!) >= e);
    if (kept.length < 30) break;
    const correct = kept.filter(
      (r) => (r.pred_total! > r.market_total!) === (r.total! > r.market_total!),
    ).length;
    out.push({
      edge: e,
      accuracy: (100 * correct) / kept.length,
      coverage: (100 * kept.length) / graded.length,
    });
  }
  return out;
}

// Head-to-head vs the market on the games where we have a pregame line:
// winner accuracy for both, total-runs miss for both, and the record when
// the model and the market favorite disagree.
export function marketComparison(rows: ResultRow[]) {
  const lined = rows.filter((r) => r.market_p_home != null);
  if (lined.length === 0) return null;
  const modelRight = (r: ResultRow) => (r.p_home >= 0.5) === r.home_won;
  const marketRight = (r: ResultRow) => (r.market_p_home! >= 0.5) === r.home_won;
  const disagree = lined.filter((r) => (r.p_home >= 0.5) !== (r.market_p_home! >= 0.5));
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

// Month-by-month winners-called rate, model vs the market favorite, on the
// same games. Months with too few lined games are dropped (noise).
export function monthlyVsMarket(rows: ResultRow[]) {
  const byMonth = new Map<string, ResultRow[]>();
  for (const r of rows) {
    if (r.market_p_home == null) continue;
    const m = r.game_date.slice(0, 7);
    byMonth.set(m, [...(byMonth.get(m) ?? []), r]);
  }
  return [...byMonth.entries()]
    .filter(([, v]) => v.length >= 15)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, v]) => ({
      month,
      n: v.length,
      model: (100 * v.filter((r) => (r.p_home >= 0.5) === r.home_won).length) / v.length,
      market:
        (100 * v.filter((r) => (r.market_p_home! >= 0.5) === r.home_won).length) / v.length,
    }));
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
