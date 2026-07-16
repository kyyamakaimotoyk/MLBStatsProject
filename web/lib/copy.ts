// Centralized user-facing copy (the hoopmodel.com pattern). Plain language
// only: no odds, no statistical jargon, no gambling terms.
export const copy = {
  site: {
    title: "MLB Model",
    tagline: "Nightly MLB predictions — with receipts.",
    subtitle:
      "A machine-learning model picks every MLB game — the winner, the score, " +
      "and the hitters to watch. Every prediction is logged, graded against the " +
      "real result, and published. Hits and misses alike.",
    disclaimer: "Predictions are machine-learning model output, not betting advice.",
    ctaTonight: "Tonight's picks",
    ctaRecord: "See the track record",
  },
  nav: [
    { href: "/", label: "Tonight" },
    { href: "/record", label: "Record" },
    { href: "/teams", label: "Teams" },
    { href: "/players", label: "Players" },
    { href: "/performance", label: "Model lab" },
  ],
  proof: {
    winners: (window: string) => `winners called, ${window}`,
    scoreMiss: (window: string) => `average score miss, ${window}`,
    logged: "predictions logged",
    loggedSub: "and publicly scored",
  },
  table: {
    matchup: "Matchup",
    pick: "Pick",
    winChance: "Win chance",
    scoreCall: "Score call",
    totalRuns: "Total runs",
    final: "Final",
    result: "Result",
    coinFlip: "coin flip",
  },
  steps: [
    {
      title: "Every pitch, in",
      body: "Play-by-play and pitch-level data from every MLB game, updated each morning.",
    },
    {
      title: "Rolling form",
      body: "Each team's recent play — and tonight's actual lineup — distilled into features.",
    },
    {
      title: "One model, three calls",
      body: "A gradient-boosted model predicts each team's runs: that's the winner, the score, and the game total.",
    },
    {
      title: "Scored in public",
      body: "Picks post every morning, then get graded against the final score.",
    },
  ],
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
