"use client";

import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { Venue } from "@/lib/types";

interface VenueCardProps {
  venue: Venue;
  selected: boolean;
  onSelect: () => void;
}

function formatScore(score: number): string {
  // Scores may arrive 0-1 or 0-100; normalise to a percent for display.
  const pct = score <= 1 ? score * 100 : score;
  return `${Math.round(pct)}% fit`;
}

function formatDeadline(deadline?: string | null): string | null {
  if (!deadline) return null;
  // A bare YYYY-MM-DD parses as UTC midnight and can display as the prior
  // local day; anchor it to local midnight like the CFP page does.
  const parsed = new Date(
    /^\d{4}-\d{2}-\d{2}$/.test(deadline) ? `${deadline}T00:00:00` : deadline,
  );
  if (Number.isNaN(parsed.getTime())) return deadline;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function VenueCard({ venue, selected, onSelect }: VenueCardProps) {
  const deadline = formatDeadline(venue.deadline);

  return (
    <Card
      interactive
      onClick={onSelect}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={[
        "cursor-pointer",
        selected
          ? "border-primary ring-2 ring-primary/40"
          : "hover:border-primary/30",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h4 className="font-display text-base font-semibold text-ink">
            {venue.name}
          </h4>
          {venue.type ? (
            <span className="text-xs uppercase tracking-wide text-muted">
              {venue.type}
            </span>
          ) : null}
        </div>
        <span title="How closely this venue matches your work, from 0 to 100 percent">
          <Badge tone={selected ? "primary" : "lime"}>
            {formatScore(venue.score)}
          </Badge>
        </span>
      </div>

      {venue.rationale ? (
        <p className="mt-3 text-sm leading-relaxed text-muted">
          {venue.rationale}
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {deadline ? (
          <span title="Last day to submit to this venue">
            <Badge tone="pink">Submit by {deadline}</Badge>
          </span>
        ) : null}
        {typeof venue.acceptance_rate === "number" ? (
          <span title="Share of submissions this venue accepts">
            <Badge tone="neutral">
              {Math.round(
                (venue.acceptance_rate <= 1
                  ? venue.acceptance_rate * 100
                  : venue.acceptance_rate) * 1,
              )}
              % accepted
            </Badge>
          </span>
        ) : null}
        {venue.url ? (
          <a
            href={venue.url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-xs font-medium text-primary underline-offset-2 hover:underline"
          >
            View venue
          </a>
        ) : null}
      </div>
    </Card>
  );
}
