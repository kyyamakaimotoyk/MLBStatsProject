// Shared time-window options for the Tonight and Record pages.

import { today } from "@/lib/api";

export type WindowKey = "1m" | "2m" | "3m" | "season" | "2seasons" | "3seasons";

// Labels live in lib/translations.ts (t.windows), keyed by these values.
export const WINDOW_KEYS: WindowKey[] = ["1m", "2m", "3m", "season", "2seasons", "3seasons"];

// Seasons start late March; March 1 is a safe season boundary. Before March,
// "this season" means the previous year's season. Anchored to the site
// clock (US Eastern via today()), not the viewer's timezone.
export function sinceDate(key: WindowKey): string {
  const t = today();
  const year = Number(t.slice(0, 4));
  const seasonYear = Number(t.slice(5, 7)) >= 3 ? year : year - 1;
  const d = new Date(`${t}T00:00:00Z`);
  switch (key) {
    case "1m":
      d.setUTCDate(d.getUTCDate() - 30);
      break;
    case "2m":
      d.setUTCDate(d.getUTCDate() - 60);
      break;
    case "3m":
      d.setUTCDate(d.getUTCDate() - 90);
      break;
    case "season":
      return `${seasonYear}-03-01`;
    case "2seasons":
      return `${seasonYear - 1}-03-01`;
    case "3seasons":
      return `${seasonYear - 2}-03-01`;
  }
  return d.toISOString().slice(0, 10);
}

export function daysBack(key: WindowKey): number {
  const since = new Date(`${sinceDate(key)}T00:00:00Z`);
  const now = new Date(`${today()}T00:00:00Z`);
  return Math.ceil((now.getTime() - since.getTime()) / 86400000);
}
