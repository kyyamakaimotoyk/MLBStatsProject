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

const axisLabelStyle = { fill: TEXT, fontSize: 11 };

function xLabel(value: string) {
  return { value, position: "insideBottom" as const, offset: -2, style: axisLabelStyle };
}

function yLabel(value: string) {
  return {
    value,
    angle: -90,
    position: "insideLeft" as const,
    offset: 12,
    style: { ...axisLabelStyle, textAnchor: "middle" as const },
  };
}

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
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 4, right: 12, left: 4, bottom: 14 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="threshold"
            tick={{ fill: TEXT, fontSize: 11 }}
            tickFormatter={(v) => `${v}%+`}
            stroke={GRID}
            label={xLabel("Minimum win chance to count the pick")}
          />
          <YAxis
            tick={{ fill: TEXT, fontSize: 11 }}
            unit="%"
            stroke={GRID}
            domain={[0, 100]}
            label={yLabel("Percent of games")}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            formatter={(v, name) => [
              `${Number(v).toFixed(1)}%`,
              String(name) === "accuracy" ? "Winners called" : "Share of games",
            ]}
            labelFormatter={(v) => `Confidence at least ${v}%`}
          />
          <Legend
            verticalAlign="top"
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
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={points} margin={{ top: 4, right: 12, left: 4, bottom: 14 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="fpr"
            type="number"
            domain={[0, 100]}
            tick={{ fill: TEXT, fontSize: 11 }}
            unit="%"
            stroke={GRID}
            label={xLabel("False alarms — losses we called wins")}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: TEXT, fontSize: 11 }}
            unit="%"
            stroke={GRID}
            label={yLabel("Wins we caught")}
          />
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
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} barCategoryGap={2} margin={{ top: 4, right: 12, left: 4, bottom: 14 }}>
          <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
          <XAxis
            dataKey="bin"
            tick={{ fill: TEXT, fontSize: 11 }}
            tickFormatter={(v) => (v > 0 ? `+${v}` : `${v}`)}
            stroke={GRID}
            label={xLabel("Runs off — predicted margin minus actual")}
          />
          <YAxis
            tick={{ fill: TEXT, fontSize: 11 }}
            unit="%"
            stroke={GRID}
            label={yLabel("Share of games")}
          />
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

export type GamePoint = {
  date: string;
  home: string;
  away: string;
  home_score: number | null;
  away_score: number | null;
  actual: number | null;
  expected?: number | null;
};

function GameTooltip({ active, payload, statLabel }: {
  active?: boolean;
  payload?: { payload: GamePoint; dataKey: string; value: number }[];
  statLabel: string;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div style={tooltipStyle} className="px-3 py-2">
      <div className="font-medium">
        {d.date} · {d.away} @ {d.home}
      </div>
      {d.home_score != null && (
        <div style={{ color: "var(--viz-text)" }}>
          Final: {d.away} {d.away_score} – {d.home} {d.home_score}
        </div>
      )}
      <div className="mt-1">
        {statLabel}: <span className="font-semibold">{d.actual}</span>
        {d.expected != null && (
          <span style={{ color: "var(--viz-text)" }}>
            {" "}
            (we expected {d.expected.toFixed(1)})
          </span>
        )}
      </div>
    </div>
  );
}

export function PlayerCountingChart({
  points,
  statLabel,
}: {
  points: GamePoint[];
  statLabel: string;
}) {
  const data = points.map((p) => ({ ...p, date: p.date.slice(5) }));
  if (data.length === 0) return null;
  const hasExpected = data.some((d) => d.expected != null);
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} barCategoryGap={2} margin={{ top: 4, right: 12, left: 4, bottom: 14 }}>
        <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: TEXT, fontSize: 10 }}
          stroke={GRID}
          label={xLabel("Game date")}
        />
        <YAxis
          tick={{ fill: TEXT, fontSize: 11 }}
          stroke={GRID}
          allowDecimals={false}
          label={yLabel(statLabel)}
        />
        <Tooltip content={<GameTooltip statLabel={statLabel} />} />
        {hasExpected && (
          <Legend
            verticalAlign="top"
            formatter={(v) => (v === "actual" ? `Actual ${statLabel.toLowerCase()}` : "We expected")}
            wrapperStyle={{ fontSize: 12 }}
          />
        )}
        <Bar dataKey="actual" fill={S2} radius={[4, 4, 0, 0]} />
        {hasExpected && (
          <Line type="monotone" dataKey="expected" stroke={S1} strokeWidth={2} dot={{ r: 2 }} />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function ClearCurveChart({
  empirical,
  model,
  line,
  statLabel,
}: {
  empirical: { k: number; share: number }[];
  model: { k: number; share: number }[] | null;
  line: number;
  statLabel: string;
}) {
  const data = empirical.map((e) => ({
    k: e.k,
    window: e.share * 100,
    tonight: model?.find((m) => m.k === e.k) ? model.find((m) => m.k === e.k)!.share * 100 : null,
  }));
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 4, right: 12, left: 4, bottom: 14 }}>
        <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
        <XAxis
          dataKey="k"
          tick={{ fill: TEXT, fontSize: 11 }}
          stroke={GRID}
          label={xLabel(`${statLabel} — at least this many`)}
        />
        <YAxis
          domain={[0, 100]}
          unit="%"
          tick={{ fill: TEXT, fontSize: 11 }}
          stroke={GRID}
          label={yLabel("Chance of clearing it")}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(v, name) => [
            `${Number(v).toFixed(0)}%`,
            String(name) === "window" ? "Recent games" : "Model, next game",
          ]}
          labelFormatter={(v) => `${statLabel} ≥ ${v}`}
        />
        <Legend
          verticalAlign="top"
          formatter={(v) => (v === "window" ? "Recent games" : "Model, next game")}
          wrapperStyle={{ fontSize: 12 }}
        />
        <ReferenceLine x={line} stroke={REF} strokeDasharray="4 4" strokeWidth={1} />
        <Line type="monotone" dataKey="window" stroke={S2} strokeWidth={2} dot={{ r: 3 }} />
        {model && (
          <Line type="monotone" dataKey="tonight" stroke={S1} strokeWidth={2} dot={{ r: 3 }} />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}

const TEAM_SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)",
                     "var(--series-4)", "var(--series-5)", "var(--series-6)"];

export function TeamTrendsChart({
  series,
  statLabel,
}: {
  series: { team: string; points: { date: string; rolling: number | null }[] }[];
  statLabel: string;
}) {
  const dates = [...new Set(series.flatMap((s) => s.points.map((p) => p.date)))].sort();
  const rows = dates.map((date) => {
    const row: Record<string, string | number | null> = { date: date.slice(5) };
    for (const s of series) {
      const p = s.points.find((x) => x.date === date);
      row[s.team] = p?.rolling ?? null;
    }
    return row;
  });
  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={rows} margin={{ top: 4, right: 12, left: 4, bottom: 14 }}>
        <CartesianGrid stroke={GRID} strokeWidth={1} vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: TEXT, fontSize: 10 }}
          stroke={GRID}
          minTickGap={24}
          label={xLabel("Date")}
        />
        <YAxis
          tick={{ fill: TEXT, fontSize: 11 }}
          stroke={GRID}
          label={yLabel(`${statLabel} (10-game average)`)}
        />
        <Tooltip
          contentStyle={tooltipStyle}
          formatter={(v) => [Number(v).toFixed(2)]}
        />
        <Legend verticalAlign="top" wrapperStyle={{ fontSize: 12 }} />
        {series.map((s, i) => (
          <Line
            key={s.team}
            type="monotone"
            dataKey={s.team}
            stroke={TEAM_SERIES[i % TEAM_SERIES.length]}
            strokeWidth={2}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
