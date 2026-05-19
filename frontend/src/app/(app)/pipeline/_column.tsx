"use client";

import { useDroppable } from "@dnd-kit/core";
import type { Deal, PipelineStage } from "@/lib/types";
import { cn, formatCurrency } from "@/lib/utils";
import { DealCard } from "./_deal-card";
import { EmptyState } from "@/components/empty-state";
import { LayoutGrid } from "lucide-react";

interface ColumnProps {
  stage: PipelineStage;
  deals: Deal[];
}

export function Column({ stage, deals }: ColumnProps) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });
  const total = deals.reduce((sum, d) => sum + (d.value_cents ?? 0), 0);

  const dotColor = stage.is_won
    ? "#16A34A"
    : stage.is_lost
      ? "#DC2626"
      : stage.color || "#2E75B6";

  return (
    <section
      ref={setNodeRef}
      aria-label={stage.name}
      className={cn(
        "flex w-72 shrink-0 flex-col rounded-lg border border-[#E2E8F0] bg-white",
        isOver && "ring-2 ring-accent"
      )}
    >
      <header className="flex items-center justify-between gap-2 border-b border-[#E2E8F0] px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: dotColor }} aria-hidden />
          <h2 className="truncate text-sm font-semibold text-slate-900">{stage.name}</h2>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
            {deals.length}
          </span>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">{formatCurrency(total)}</span>
      </header>
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {deals.length === 0 ? (
          <EmptyState
            icon={LayoutGrid}
            title="No deals"
            description="Drop a deal here."
            className="border-none bg-slate-50 py-8"
          />
        ) : (
          deals.map((deal) => <DealCard key={deal.id} deal={deal} />)
        )}
      </div>
    </section>
  );
}
