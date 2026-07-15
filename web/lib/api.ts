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

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}
