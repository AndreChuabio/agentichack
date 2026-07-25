"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Cfp } from "@/lib/types";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import { CfpRow } from "./CfpRow";

type DeadlineFilter = "all" | "upcoming" | "past";

export default function CfpPage() {
  const [cfps, setCfps] = useState<Cfp[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [format, setFormat] = useState("all");
  const [deadlineFilter, setDeadlineFilter] = useState<DeadlineFilter>("upcoming");

  useEffect(() => {
    let cancelled = false;
    api
      .listCfps()
      .then((rows) => {
        if (!cancelled) setCfps(rows);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load CFPs");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const formats = useMemo(() => {
    if (!cfps) return [];
    return Array.from(new Set(cfps.map((c) => c.format).filter(Boolean))).sort();
  }, [cfps]);

  const today = useMemo(() => new Date(new Date().toDateString()), []);

  const filtered = useMemo(() => {
    if (!cfps) return [];
    const query = search.trim().toLowerCase();
    return cfps.filter((c) => {
      if (query) {
        const haystack = `${c.name} ${c.scope}`.toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      if (format !== "all" && c.format !== format) return false;
      if (deadlineFilter !== "all") {
        if (!c.deadline) return false;
        const deadline = new Date(`${c.deadline}T00:00:00`);
        const upcoming = deadline >= today;
        if (deadlineFilter === "upcoming" && !upcoming) return false;
        if (deadlineFilter === "past" && upcoming) return false;
      }
      return true;
    });
  }, [cfps, search, format, deadlineFilter, today]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-display text-2xl font-bold text-ink">
          Call for Papers
        </h1>
        <p className="mt-1 text-sm text-muted">
          Every venue in the shared CFP corpus, in chronological order.
        </p>
      </div>

      <Card className="flex flex-col gap-4 sm:flex-row sm:items-end sm:flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <Input
            label="Search"
            placeholder="Search by name or scope..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="font-display text-sm font-medium text-ink">
            Format
          </label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            className="rounded-2xl border border-black/10 bg-surface px-4 py-2.5 text-sm text-ink shadow-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
          >
            <option value="all">All formats</option>
            {formats.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="font-display text-sm font-medium text-ink">
            Deadline
          </label>
          <select
            value={deadlineFilter}
            onChange={(e) => setDeadlineFilter(e.target.value as DeadlineFilter)}
            className="rounded-2xl border border-black/10 bg-surface px-4 py-2.5 text-sm text-ink shadow-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/30"
          >
            <option value="all">All</option>
            <option value="upcoming">Upcoming</option>
            <option value="past">Past</option>
          </select>
        </div>
      </Card>

      <Card>
        {error ? (
          <p className="text-sm text-danger">{error}</p>
        ) : !cfps ? (
          <div className="flex items-center justify-center py-10">
            <Spinner size={24} />
          </div>
        ) : filtered.length === 0 ? (
          <div>
            <CardTitle>No CFPs match your filters</CardTitle>
            <CardDescription>Try clearing the search or filters above.</CardDescription>
          </div>
        ) : (
          <div className="flex flex-col">
            {filtered.map((cfp) => (
              <CfpRow key={cfp.id} cfp={cfp} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
