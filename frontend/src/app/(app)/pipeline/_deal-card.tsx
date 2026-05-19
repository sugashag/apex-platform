"use client";

import { useDraggable } from "@dnd-kit/core";
import type { Deal } from "@/lib/types";
import { cn, daysBetween, formatCurrency } from "@/lib/utils";
import { LeadScoreBadge } from "@/components/lead-score-badge";
import { Building2 } from "lucide-react";

interface DealCardProps {
  deal: Deal;
  dragging?: boolean;
}

export function DealCard({ deal, dragging }: DealCardProps) {
  const { attributes, listeners, setNodeRef, isDragging, transform } = useDraggable({ id: deal.id });
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` }
    : undefined;

  const daysInStage = daysBetween(deal.stage_entered_at ?? deal.updated_at);

  return (
    <article
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={cn(
        "cursor-grab rounded-md border border-[#E2E8F0] bg-white p-3 shadow-sm transition-shadow hover:shadow",
        (isDragging || dragging) && "opacity-90 shadow-md ring-2 ring-accent"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="line-clamp-2 text-sm font-semibold text-slate-900">{deal.name}</h3>
        {typeof deal.lead_score === "number" ? <LeadScoreBadge score={deal.lead_score} /> : null}
      </div>
      {deal.contact_name || deal.company_name ? (
        <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
          {deal.company_name ? (
            <span className="inline-flex items-center gap-1">
              <Building2 className="h-3 w-3" aria-hidden />
              {deal.company_name}
            </span>
          ) : null}
          {deal.contact_name && deal.company_name ? <span aria-hidden>·</span> : null}
          {deal.contact_name ? <span>{deal.contact_name}</span> : null}
        </div>
      ) : null}
      <div className="mt-3 flex items-center justify-between text-xs">
        <span className="font-medium text-slate-900">{formatCurrency(deal.value_cents, deal.currency)}</span>
        <span className="text-muted-foreground">{daysInStage}d in stage</span>
      </div>
    </article>
  );
}
