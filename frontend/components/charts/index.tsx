"use client";

import { Table2, ChartColumn } from "lucide-react";
import { useState, type ReactNode } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Panel } from "@/components/common";
import { Button } from "@/components/ui/button";
import { formatBytes, formatCount, parseTime } from "@/lib/format";

const axisTick = { fill: "var(--chart-label)", fontSize: 11 };
const GRID = "var(--chart-grid)";
const AXIS = "var(--chart-axis)";

export interface TableColumn {
  key: string;
  label: string;
  align?: "right";
  format?: (value: never) => string;
}

/** Every chart has a table twin, so no value depends on hovering or on color. */
export function ChartPanel({
  title,
  subtitle,
  legend,
  columns,
  rows,
  children,
  empty,
}: {
  title: string;
  subtitle?: ReactNode;
  legend?: { label: string; color: string }[];
  columns: TableColumn[];
  rows: Record<string, unknown>[];
  children: ReactNode;
  empty?: ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <Panel
      title={title}
      subtitle={subtitle}
      actions={
        rows.length > 0 && (
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={showTable ? "Show chart" : "Show table"}
            title={showTable ? "Show chart" : "Show table"}
            onClick={() => setShowTable((v) => !v)}
          >
            {showTable ? <ChartColumn /> : <Table2 />}
          </Button>
        )
      }
    >
      {rows.length === 0 ? (
        empty
      ) : showTable ? (
        <div className="max-h-56 overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                {columns.map((c) => (
                  <th key={c.key} className={`py-1.5 pr-3 font-medium ${c.align === "right" ? "text-right" : "text-left"}`}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular">
              {rows.map((row, i) => (
                <tr key={i} className="border-b last:border-0">
                  {columns.map((c) => (
                    <td key={c.key} className={`py-1 pr-3 ${c.align === "right" ? "text-right" : ""}`}>
                      {c.format ? c.format(row[c.key] as never) : String(row[c.key] ?? "N/A")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          {legend && (
            <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              {legend.map((item) => (
                <li key={item.label} className="flex items-center gap-1.5">
                  <span className="inline-block h-0.5 w-3 rounded-full" style={{ background: item.color }} aria-hidden />
                  {item.label}
                </li>
              ))}
            </ul>
          )}
          {children}
        </>
      )}
    </Panel>
  );
}

function TooltipBox({ title, rows }: { title: string; rows: { label: string; value: string; color?: string }[] }) {
  return (
    <div className="rounded-md border bg-popover px-2.5 py-2 text-xs shadow-sm">
      <p className="mb-1 font-medium">{title}</p>
      {rows.map((row) => (
        <p key={row.label} className="tabular flex items-center justify-between gap-4 text-muted-foreground">
          <span className="flex items-center gap-1.5">
            {row.color && <span className="inline-block size-2 rounded-full" style={{ background: row.color }} aria-hidden />}
            {row.label}
          </span>
          <span className="text-foreground">{row.value}</span>
        </p>
      ))}
    </div>
  );
}

/** Logical and stored bytes over time, on one axis. The gap between the lines is the saving. */
export function StorageOverTimeChart({ data, height = 220 }: { data: { taken_at: string; logical_bytes: number; stored_bytes: number }[]; height?: number }) {
  const series = data.map((d, index) => ({ ...d, index, label: parseTime(d.taken_at).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="index" tick={false} axisLine={{ stroke: AXIS }} tickLine={false} height={8} />
        <YAxis tick={axisTick} tickFormatter={(v) => formatBytes(v, 0)} axisLine={false} tickLine={false} width={62} />
        <Tooltip
          cursor={{ stroke: AXIS }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as (typeof series)[number];
            return (
              <TooltipBox
                title={point.label}
                rows={[
                  { label: "Logical", value: formatBytes(point.logical_bytes), color: "var(--chart-label)" },
                  { label: "Stored", value: formatBytes(point.stored_bytes), color: "var(--series-1)" },
                ]}
              />
            );
          }}
        />
        <Area type="stepAfter" dataKey="logical_bytes" stroke="var(--chart-label)" strokeWidth={2} fill="none" isAnimationActive={false} />
        <Area type="stepAfter" dataKey="stored_bytes" stroke="var(--series-1)" strokeWidth={2} fill="var(--series-1)" fillOpacity={0.1} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

type Row = Record<string, unknown>;

export function ColumnChart({
  data,
  x,
  y,
  xFormat,
  yFormat = formatCount,
  seriesLabel,
}: {
  data: Row[];
  x: string;
  y: string;
  xFormat?: (value: never) => string;
  yFormat?: (value: number) => string;
  seriesLabel: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={x} tick={axisTick} tickFormatter={xFormat as never} axisLine={{ stroke: AXIS }} tickLine={false} interval={0} height={24} />
        <YAxis tick={axisTick} tickFormatter={(v) => yFormat(v)} axisLine={false} tickLine={false} width={56} allowDecimals={false} />
        <Tooltip
          cursor={{ fill: "var(--muted)", opacity: 0.6 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as Row;
            const heading = xFormat ? xFormat(point[x] as never) : String(point[x]);
            return <TooltipBox title={heading} rows={[{ label: seriesLabel, value: yFormat(point[y] as number), color: "var(--series-1)" }]} />;
          }}
        />
        <Bar dataKey={y} fill="var(--series-1)" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function HorizontalBars({
  data,
  category,
  value,
  format,
  seriesLabel,
}: {
  data: Row[];
  category: string;
  value: string;
  format: (value: number) => string;
  seriesLabel: string;
}) {
  const height = Math.max(120, data.length * 34 + 10);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart layout="vertical" data={data} margin={{ top: 0, right: 70, bottom: 0, left: 0 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey={category} tick={axisTick} axisLine={{ stroke: AXIS }} tickLine={false} width={70} />
        <Tooltip
          cursor={{ fill: "var(--muted)", opacity: 0.6 }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const point = payload[0].payload as Row;
            return <TooltipBox title={String(point[category])} rows={[{ label: seriesLabel, value: format(point[value] as number), color: "var(--series-1)" }]} />;
          }}
        />
        <Bar
          dataKey={value}
          fill="var(--series-1)"
          maxBarSize={18}
          radius={[0, 4, 4, 0]}
          isAnimationActive={false}
          label={{ position: "right", fill: "var(--chart-label)", fontSize: 11, formatter: (v: unknown) => format(v as number) }}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** One whole split into parts: what is kept and what deduplication avoided. */
export function ReductionBar({ logical, stored }: { logical: number; stored: number }) {
  if (logical <= 0) return null;
  const kept = Math.min(stored, logical);
  const avoided = Math.max(logical - stored, 0);
  const keptShare = (kept / logical) * 100;
  const avoidedShare = (avoided / logical) * 100;
  return (
    <div>
      <div
        className="flex h-7 w-full gap-0.5"
        role="img"
        aria-label={`${formatBytes(kept)} stored, ${keptShare.toFixed(1)} percent. ${formatBytes(avoided)} avoided, ${avoidedShare.toFixed(1)} percent.`}
      >
        {kept > 0 && (
          <div className="flex items-center overflow-hidden rounded bg-series-1 px-2 text-xs font-medium text-white" style={{ width: `${keptShare}%` }} title={`Stored: ${formatBytes(kept)}`}>
            {keptShare >= 12 && <span>{formatBytes(kept)}</span>}
          </div>
        )}
        {avoided > 0 && (
          <div className="flex items-center overflow-hidden rounded bg-avoided px-2 text-xs font-medium text-avoided-ink" style={{ width: `${avoidedShare}%` }} title={`Avoided: ${formatBytes(avoided)}`}>
            {avoidedShare >= 12 && <span>{formatBytes(avoided)}</span>}
          </div>
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <li className="flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-sm bg-series-1" aria-hidden />
          Stored content
        </li>
        <li className="flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-sm bg-avoided" aria-hidden />
          Avoided by deduplication
        </li>
      </ul>
    </div>
  );
}

/** Two comparable values as thin bars on one shared scale. */
export function BeforeAfter({
  rows,
  format = formatBytes,
}: {
  rows: { label: string; before: number; after: number }[];
  format?: (value: number) => string;
}) {
  return (
    <div className="space-y-4">
      {rows.map((row) => {
        const max = Math.max(row.before, row.after, 1);
        return (
          <div key={row.label}>
            <p className="mb-1.5 text-xs text-muted-foreground">{row.label}</p>
            <div className="space-y-1">
              {[
                { name: "Before", value: row.before, className: "bg-[var(--chart-label)]" },
                { name: "After", value: row.after, className: "bg-series-1" },
              ].map((part) => (
                <div key={part.name} className="flex items-center gap-2">
                  <span className="w-10 shrink-0 text-[11px] text-muted-foreground">{part.name}</span>
                  <div className="h-3 min-w-0 flex-1">
                    <div className={`h-full rounded-r ${part.className}`} style={{ width: `${(part.value / max) * 100}%`, minWidth: part.value > 0 ? 2 : 0 }} />
                  </div>
                  <span className="tabular w-20 shrink-0 text-right text-xs">{format(part.value)}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
