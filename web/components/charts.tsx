"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { confusion, marginMissHistogram, ResultRow, roc, skillCurve } from "@/lib/perf";

const S1 = "var(--series-1)";
const S2 = "var(--series-2)";
const GRID = "var(--viz-grid)";
const TEXT = "var(--viz-text)";
const REF = "var(--viz-ref)";

const tooltipStyle = {
  backgroundColor: "var(--viz-panel)",
  border: `1px solid ${GRID}`,
  borderRadius: 6,
  fontSize: 12,
  color: "var(--foreground)",
};

function ChartPanel({
  title,
  sub,
  children,
}: {
  title: string;
  sub: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded border border-zinc-200 p-4 dark:border-zinc-800">
      <h3 className="font-semibold">{title}</h3>
      <p className="mb-3 text-xs text-zinc-500">{sub}</p>
      {children}
    </div>
  );
}

export function SkillCurveChart({ rows }: { rows: ResultRow[] }) {
  const data = skillCurve(rows);
  return (
    <ChartPanel
      title="Picking our spots"
      sub="When we only count games where the model is more confident, how often is it right — and how many games is that?"
    >
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 4, right: 12, left: -18, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="threshold"
            tick={{ fill: TEXT, fontSize: 11 }}
            tickFormatter={(v) => `${v}%+`}
            stroke={GRID}
          />
          <YAxis tick={{ fill: TEXT, fontSize: 11 }} unit="%" stroke={GRID} domain={[0, 100]} />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(v, name) => [
              `${Number(v).toFixed(1)}%`,
              String(name) === "accuracy" ? "Winners called" : "Share of games",
            ]}
            labelFormatter={(v) => `Confidence at least ${v}%`}
          />
          <Legend
            formatter={(v) => (v === "accuracy" ? "Winners called" : "Share of games kept")}
            wrapperStyle={{ fontSize: 12 }}
          />
          <ReferenceLine y={50} stroke={REF} strokeDasharray="4 4" strokeWidth={1} />
          <Line type="monotone" dataKey="accuracy" stroke={S1} strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="coverage" stroke={S2} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}

export function RocChart({ rows }: { rows: ResultRow[] }) {
  const { points, auc } = roc(rows);
  return (
    <ChartPanel
      title={`Telling winners from losers — score ${auc.toFixed(2)}`}
      sub="The curve should bow above the dashed line. 0.50 is guessing; 1.00 is perfect. (This is the ROC curve.)"
    >
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={points} margin={{ top: 4, right: 12, left: -18, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="fpr"
            type="number"
            domain={[0, 100]}
            tick={{ fill: TEXT, fontSize: 11 }}
            unit="%"
            stroke={GRID}
          />
          <YAxis domain={[0, 100]} tick={{ fill: TEXT, fontSize: 11 }} unit="%" stroke={GRID} />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(v) => [`${Number(v).toFixed(0)}%`]}
          />
          <ReferenceLine
            segment={[
              { x: 0, y: 0 },
              { x: 100, y: 100 },
            ]}
            stroke={REF}
            strokeDasharray="4 4"
            strokeWidth={1}
          />
          <Line type="monotone" dataKey="tpr" stroke={S1} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}

export function MarginMissChart({ rows }: { rows: ResultRow[] }) {
  const data = marginMissHistogram(rows);
  return (
    <ChartPanel
      title="How far the score calls miss"
      sub="Predicted margin minus the real margin, in runs. Centered on zero is honest; the spread is baseball."
    >
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} barCategoryGap={2} margin={{ top: 4, right: 12, left: -18, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="bin"
            tick={{ fill: TEXT, fontSize: 11 }}
            tickFormatter={(v) => (v > 0 ? `+${v}` : `${v}`)}
            stroke={GRID}
          />
          <YAxis tick={{ fill: TEXT, fontSize: 11 }} unit="%" stroke={GRID} />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(v) => [`${Number(v).toFixed(1)}% of games`]}
            labelFormatter={(v) => {
              const n = Number(v);
              return `missed by ${n > 0 ? `+${n}` : n} run${Math.abs(n) === 1 ? "" : "s"}`;
            }}
          />
          <ReferenceLine x={0} stroke={REF} strokeDasharray="4 4" strokeWidth={1} />
          <Bar dataKey="share" fill={S2} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}

export function ConfusionMatrix({ rows }: { rows: ResultRow[] }) {
  const c = confusion(rows);
  const total = rows.length;
  const cell = (n: number, good: boolean) => (
    <td
      className="px-4 py-3 text-center"
      style={{
        backgroundColor: good ? "var(--good-bg)" : "var(--bad-bg)",
        color: good ? "var(--good-text)" : "var(--bad-text)",
      }}
    >
      <div className="text-lg font-bold">{((100 * n) / total).toFixed(1)}%</div>
      <div className="text-xs opacity-80">{n.toLocaleString()} games</div>
    </td>
  );
  return (
    <ChartPanel
      title="Picks vs what happened"
      sub="Green cells are correct picks; red cells are misses. Rows are our pick, columns the real winner."
    >
      <table className="w-full border-separate border-spacing-0.5 text-sm">
        <thead>
          <tr className="text-xs text-zinc-500">
            <th></th>
            <th className="px-4 py-1">Home team won</th>
            <th className="px-4 py-1">Away team won</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th className="pr-2 text-right text-xs font-medium text-zinc-500">
              Picked home
            </th>
            {cell(c.homePickHomeWin, true)}
            {cell(c.homePickAwayWin, false)}
          </tr>
          <tr>
            <th className="pr-2 text-right text-xs font-medium text-zinc-500">
              Picked away
            </th>
            {cell(c.awayPickHomeWin, false)}
            {cell(c.awayPickAwayWin, true)}
          </tr>
        </tbody>
      </table>
    </ChartPanel>
  );
}

export function PlayerHitsChart({
  games,
}: {
  games: { game_date: string; h: number | null; exp_h: number | null }[];
}) {
  const data = [...games]
    .reverse()
    .filter((g) => g.h != null)
    .map((g) => ({ date: g.game_date.slice(5), actual: g.h, expected: g.exp_h }));
  if (data.length === 0) return null;
  return (
    <ChartPanel
      title="Hits: what we said vs what happened"
      sub="Bars are actual hits per game; the line is how many the model expected going in."
    >
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} barCategoryGap={2} margin={{ top: 4, right: 12, left: -24, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: TEXT, fontSize: 10 }} stroke={GRID} />
          <YAxis
            tick={{ fill: TEXT, fontSize: 11 }}
            stroke={GRID}
            allowDecimals={false}
          />
          <Tooltip contentStyle={tooltipStyle} />
          <Legend
            formatter={(v) => (v === "actual" ? "Actual hits" : "Expected hits")}
            wrapperStyle={{ fontSize: 12 }}
          />
          <Bar dataKey="actual" fill={S2} radius={[4, 4, 0, 0]} />
          <Line
            type="monotone"
            dataKey="expected"
            stroke={S1}
            strokeWidth={2}
            dot={{ r: 2 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartPanel>
  );
}
