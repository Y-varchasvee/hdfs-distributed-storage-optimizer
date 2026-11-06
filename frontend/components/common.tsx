"use client";

import { motion } from "motion/react";
import { AlertTriangle, Check, CheckCircle2, Circle, Copy, Info, Loader2, OctagonAlert, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api";
import { shortHash } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  flush,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
}) {
  return (
    <section className={cn("min-w-0 rounded-lg border bg-card", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3.5 pb-1">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={flush ? "" : "p-4"}>{children}</div>
    </section>
  );
}

export type Provenance = "measured" | "derived" | "estimated";

const PROVENANCE: Record<Provenance, { label: string; help: string; dot: string }> = {
  measured: {
    label: "Measured",
    help: "Reported directly by HDFS at the time shown.",
    dot: "bg-foreground",
  },
  derived: {
    label: "Derived",
    help: "Computed exactly from the metadata database, which records what the application stored. Excludes replication.",
    dot: "border-[1.5px] border-foreground",
  },
  estimated: {
    label: "Estimated",
    help: "A prediction or calculation, not an observation. Treat as approximate until verified.",
    dot: "border-[1.5px] border-dashed border-muted-foreground",
  },
};

/** Every headline number states how it is known. */
export function ProvenanceTag({ kind }: { kind: Provenance }) {
  const info = PROVENANCE[kind];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span className="inline-flex cursor-help items-center gap-1 text-[11px] text-muted-foreground">
            <span className={cn("inline-block size-2 rounded-full", info.dot)} aria-hidden />
            {info.label}
          </span>
        }
      />
      <TooltipContent className="max-w-64">{info.help}</TooltipContent>
    </Tooltip>
  );
}

export function Stat({
  label,
  value,
  note,
  provenance,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  provenance?: Provenance;
}) {
  return (
    <div className="min-w-0">
      <div className="text-xs leading-tight text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-xl font-semibold tracking-tight" title={typeof value === "string" ? value : undefined}>
        {value}
      </div>
      <div className="mt-1 flex min-h-4 flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
        {provenance && <ProvenanceTag kind={provenance} />}
        {note && <span>{note}</span>}
      </div>
    </div>
  );
}

const TONES: Record<string, { icon: LucideIcon; className: string }> = {
  good: { icon: CheckCircle2, className: "text-good" },
  warning: { icon: AlertTriangle, className: "text-warning" },
  critical: { icon: OctagonAlert, className: "text-critical" },
  neutral: { icon: Circle, className: "text-muted-foreground" },
  info: { icon: Info, className: "text-muted-foreground" },
  busy: { icon: Loader2, className: "text-primary" },
};

/** Status always pairs an icon and a label with its color. */
export function Status({ tone, children, className }: { tone: keyof typeof TONES; children: ReactNode; className?: string }) {
  const { icon: Icon, className: toneClass } = TONES[tone];
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[13px]", className)}>
      <Icon className={cn("size-3.5 shrink-0", toneClass, tone === "busy" && "animate-spin")} aria-hidden />
      <span>{children}</span>
    </span>
  );
}

export function EmptyState({ icon: Icon, title, children, action }: { icon?: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
      {Icon && <Icon className="mb-3 size-5 text-muted-foreground" aria-hidden />}
      <p className="text-[13px] font-medium">{title}</p>
      {children && <p className="mt-1 max-w-md text-xs text-muted-foreground">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong.";
  const hdfsDown = error instanceof ApiError && error.code === "hdfs_unavailable";
  return (
    <div role="alert" className="flex items-start gap-2.5 rounded-md border border-critical/30 bg-critical/5 px-3 py-2.5 text-[13px]">
      <OctagonAlert className="mt-0.5 size-4 shrink-0 text-critical" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{hdfsDown ? "HDFS is unavailable" : "This could not be completed"}</p>
        <p className="mt-0.5 break-words text-muted-foreground">{message}</p>
      </div>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warning"; children: ReactNode }) {
  const Icon = tone === "warning" ? AlertTriangle : Info;
  return (
    <div className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-xs text-muted-foreground", tone === "warning" && "border-warning/40 bg-warning/5")}>
      <Icon className={cn("mt-px size-3.5 shrink-0", tone === "warning" && "text-warning")} aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function RowsSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  );
}

export function HashText({ hash, length = 12 }: { hash: string; length?: number }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="group inline-flex items-center gap-1 rounded font-mono text-xs text-muted-foreground hover:text-foreground"
      title={hash}
      aria-label={`Copy SHA-256 ${hash}`}
      onClick={(event) => {
        event.stopPropagation();
        navigator.clipboard?.writeText(hash);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
    >
      {shortHash(hash, length)}
      {copied ? <Check className="size-3" aria-hidden /> : <Copy className="size-3 opacity-0 group-hover:opacity-100" aria-hidden />}
    </button>
  );
}

/** A determinate bar that shows real job progress. */
export function ProgressBar({ value, className, label }: { value: number; className?: string; label?: string }) {
  const percent = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      role="progressbar"
      aria-valuenow={Math.round(percent)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <motion.div className="h-full rounded-full bg-series-1" animate={{ width: `${percent}%` }} transition={{ duration: 0.25, ease: "easeOut" }} />
    </div>
  );
}

/** A compact select. Options carry labels so the trigger always shows the human-readable choice. */
export function Choice<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  ariaLabel: string;
  className?: string;
}) {
  return (
    <Select items={options} value={value} onValueChange={(next) => next !== null && onChange(next as T)}>
      <SelectTrigger aria-label={ariaLabel} className={cn("h-8 text-[13px]", className)}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function KeyValue({ rows }: { rows: { label: string; value: ReactNode; hint?: ReactNode }[] }) {
  return (
    <dl className="divide-y text-[13px]">
      {rows.map((row) => (
        <div key={row.label} className="flex items-baseline justify-between gap-4 py-1.5 first:pt-0 last:pb-0">
          <dt className="shrink-0 text-muted-foreground">{row.label}</dt>
          <dd className="min-w-0 text-right break-words">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
