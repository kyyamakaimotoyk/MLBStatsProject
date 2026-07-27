// Formatting helpers shared across pages. All user-facing copy lives in
// lib/translations.ts (en/ja); only language-neutral formatters and the
// English-only SEO metadata belong here.

// Search engines and social cards read only the prerendered HTML, and the
// EN/JA toggle is client-side — one URL serves both languages. So the meta
// description carries both: engines surface whichever half matches the
// searcher's query language (and the JA half is the only Japanese text a
// crawler ever sees on the site).
export const siteMeta = {
  title: "MLB Model",
  description:
    "Nightly machine-learning predictions for every MLB game — winners, " +
    "scores, run totals, and hitter calls, all graded in public. " +
    "機械学習モデルがMLBの全試合を毎日予測。勝敗・スコア・合計得点・注目打者の予測を" +
    "試合前に公開し、実際の結果と照らし合わせて採点しています。",
};

export function pctLabel(p: number | null | undefined): string {
  return p == null ? "—" : `${Math.round(p * 100)}%`;
}

export function scoreCall(home: string, away: string, hr: number | null, ar: number | null) {
  if (hr == null || ar == null) return "—";
  return hr >= ar
    ? `${home} ${hr.toFixed(1)}–${ar.toFixed(1)}`
    : `${away} ${ar.toFixed(1)}–${hr.toFixed(1)}`;
}

export function finalScore(home: string, away: string, hs: number | null, as_: number | null) {
  if (hs == null || as_ == null) return "—";
  return hs > as_ ? `${home} ${hs}–${as_}` : `${away} ${as_}–${hs}`;
}

// The betting market's favorite with its no-vig win chance, e.g. "NYY 62%".
// evenLabel is the localized word for a pick'em line.
export function marketCall(
  home: string,
  away: string,
  pHome: number | null,
  evenLabel = "even",
) {
  if (pHome == null) return "—";
  if (pHome === 0.5) return evenLabel;
  const fav = pHome > 0.5 ? home : away;
  return `${fav} ${pctLabel(Math.max(pHome, 1 - pHome))}`;
}
