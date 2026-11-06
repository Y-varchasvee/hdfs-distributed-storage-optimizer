"use client";

import {
  Activity,
  ChartNoAxesCombined,
  CopyCheck,
  FlaskConical,
  FolderTree,
  Gauge,
  Layers3,
  Menu,
  Moon,
  Server,
  Settings2,
  Sparkles,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useState, useSyncExternalStore, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useClusterStatus } from "@/lib/queries";
import { cn } from "@/lib/utils";

const NAV: { group: string; items: { href: string; label: string; icon: LucideIcon }[] }[] = [
  {
    group: "Overview",
    items: [{ href: "/", label: "Dashboard", icon: Gauge }],
  },
  {
    group: "Data",
    items: [
      { href: "/files", label: "Files", icon: FolderTree },
      { href: "/duplicates", label: "Duplicates", icon: CopyCheck },
      { href: "/optimize", label: "Optimization", icon: Sparkles },
    ],
  },
  {
    group: "Cluster",
    items: [
      { href: "/replication", label: "Replication", icon: Layers3 },
      { href: "/cluster", label: "Monitoring", icon: Server },
    ],
  },
  {
    group: "Insight",
    items: [
      { href: "/analytics", label: "Analytics", icon: ChartNoAxesCombined },
      { href: "/activity", label: "Activity", icon: Activity },
      { href: "/lab", label: "Dataset lab", icon: FlaskConical },
    ],
  },
  {
    group: "System",
    items: [{ href: "/settings", label: "Settings", icon: Settings2 }],
  },
];

function BrandMark() {
  // Several logical files resolving to one stored copy.
  return (
    <svg viewBox="0 0 24 24" className="size-5" fill="none" aria-hidden>
      <path d="M3 5h6c3 0 3 7 6 7M3 12h12M3 19h6c3 0 3-7 6-7" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <rect x="15" y="9" width="6" height="6" rx="1.5" fill="var(--series-1)" />
    </svg>
  );
}

function ClusterIndicator() {
  const { data, isError } = useClusterStatus();
  let dot = "bg-muted-foreground";
  let text = "Checking cluster";
  if (isError) {
    dot = "bg-critical";
    text = "Backend unreachable";
  } else if (data && !data.reachable) {
    dot = "bg-critical";
    text = "NameNode unreachable";
  } else if (data?.reachable) {
    dot = data.health === "healthy" ? "bg-good" : data.health === "degraded" ? "bg-warning" : "bg-critical";
    text = `${data.health === "healthy" ? "Healthy" : data.health === "degraded" ? "Degraded" : "Critical"} · ${data.datanodes.live} DataNode${data.datanodes.live === 1 ? "" : "s"}`;
  }
  return (
    <Link href="/cluster" className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
      <span className={cn("size-2 shrink-0 rounded-full", dot)} aria-hidden />
      <span className="truncate">{text}</span>
    </Link>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // The theme is unknown during server rendering; true only in the browser.
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const dark = mounted && resolvedTheme === "dark";
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme(dark ? "light" : "dark")}
    >
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="space-y-4">
      {NAV.map((section) => (
        <div key={section.group}>
          <p className="mb-1 px-2 text-[11px] font-medium text-subtle">{section.group}</p>
          <ul className="space-y-px">
            {section.items.map(({ href, label, icon: Icon }) => {
              const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-[13px] transition-colors",
                      active ? "bg-accent font-medium text-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                    )}
                  >
                    <Icon className="size-4 shrink-0" aria-hidden />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[216px_minmax(0,1fr)]">
      <aside className="hidden border-r bg-card lg:block">
        <div className="sticky top-0 flex h-screen flex-col">
          <div className="flex h-14 items-center gap-2 px-4">
            <BrandMark />
            <span className="text-sm font-semibold tracking-tight">HDFS Optimizer</span>
          </div>
          <div className="flex-1 overflow-y-auto px-2 py-2">
            <Navigation />
          </div>
          <div className="flex items-center justify-between gap-1 border-t px-2 py-2">
            <ClusterIndicator />
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <div className="sticky top-0 z-30 flex h-12 items-center justify-between border-b bg-card px-3 lg:hidden">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon-sm" aria-label="Open navigation" onClick={() => setOpen(true)}>
              <Menu />
            </Button>
            <BrandMark />
            <span className="text-sm font-semibold tracking-tight">HDFS Optimizer</span>
          </div>
          <ThemeToggle />
        </div>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent side="left" className="w-64 p-3">
            <SheetTitle className="px-2 pt-1 pb-2 text-sm">HDFS Optimizer</SheetTitle>
            <Navigation onNavigate={() => setOpen(false)} />
            <div className="mt-4 border-t pt-2">
              <ClusterIndicator />
            </div>
          </SheetContent>
        </Sheet>

        <motion.main
          key={pathname}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
          className="mx-auto w-full max-w-[1320px] px-4 py-6 sm:px-6 lg:px-8"
        >
          {children}
        </motion.main>
      </div>
    </div>
  );
}
