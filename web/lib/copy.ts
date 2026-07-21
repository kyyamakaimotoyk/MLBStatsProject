// Formatting helpers shared across pages. All user-facing copy lives in
// lib/translations.ts (en/ja); only language-neutral formatters and the
// English-only SEO metadata belong here.

// Static export prerenders in English, so search/OG metadata stays English.
export const siteMeta = {
  title: "MLB Model",
  subtitle:
    "A machine-learning model picks every MLB game — the winner, the score, " +
    "and the hitters to watch. Every prediction is logged, graded against the " +
    "real result, and published. Hits and misses alike.",
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
