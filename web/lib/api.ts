export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export function fmtPct(x: number | null | undefined): string {
  return x == null ? "—" : `${(x * 100).toFixed(1)}%`;
}

export function fmtNum(x: number | null | undefined, digits = 2): string {
  return x == null ? "—" : x.toFixed(digits);
}

// The whole site runs on one clock: US Eastern, MLB's schedule timezone.
// A viewer in Tokyo (or a UTC server) must agree with the slate on what
// "today" means. en-CA formats as YYYY-MM-DD.
export function today(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
  }).format(new Date());
}

export function fmtOdds(ml: number | null | undefined): string {
  if (ml == null) return "—";
  return ml > 0 ? `+${ml}` : `${ml}`;
}
