// Shared time-window options for the Tonight and Record pages.

export type WindowKey = "1m" | "2m" | "3m" | "season" | "2seasons" | "3seasons";

export const WINDOW_OPTIONS: { key: WindowKey; label: string }[] = [
  { key: "1m", label: "Last month" },
  { key: "2m", label: "Last two months" },
  { key: "3m", label: "Last three months" },
  { key: "season", label: "This season" },
  { key: "2seasons", label: "Last two seasons" },
  { key: "3seasons", label: "Last three seasons" },
];

// Seasons start late March; March 1 is a safe season boundary. Before March,
// "this season" means the previous year's season.
export function sinceDate(key: WindowKey): string {
  const now = new Date();
  const seasonYear = now.getMonth() >= 2 ? now.getFullYear() : now.getFullYear() - 1;
  const d = new Date(now);
  switch (key) {
    case "1m":
      d.setDate(d.getDate() - 30);
      break;
    case "2m":
      d.setDate(d.getDate() - 60);
      break;
    case "3m":
      d.setDate(d.getDate() - 90);
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
  const since = new Date(sinceDate(key));
  return Math.ceil((Date.now() - since.getTime()) / 86400000);
}
