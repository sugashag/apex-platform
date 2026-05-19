"use client";

import { useMemo, useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { apiFetch, ApiError } from "@/lib/api";
import type { Deal, PipelineStage, Paginated } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/error-state";
import { EmptyState } from "@/components/empty-state";
import { KanbanSquare } from "lucide-react";
import { Column } from "./_column";
import { DealCard } from "./_deal-card";

export default function PipelinePage() {
  const qc = useQueryClient();

  const stagesQ = useQuery<PipelineStage[]>({
    queryKey: ["pipeline-stages"],
    queryFn: () => apiFetch<PipelineStage[]>("/api/v1/pipeline-stages"),
  });
  const dealsQ = useQuery<Paginated<Deal>>({
    queryKey: ["deals", { include_inactive: false, page_size: 200 }],
    queryFn: () =>
      apiFetch<Paginated<Deal>>("/api/v1/deals", {
        query: { include_inactive: false, page_size: 200 },
      }),
  });

  const [activeId, setActiveId] = useState<string | null>(null);
  // Optimistic stage assignments keyed by deal id.
  const [overrides, setOverrides] = useState<Record<string, string>>({});

  useEffect(() => {
    setOverrides({});
  }, [dealsQ.dataUpdatedAt]);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));

  const dealsByStage = useMemo(() => {
    const map = new Map<string, Deal[]>();
    if (!stagesQ.data) return map;
    for (const s of stagesQ.data) map.set(s.id, []);
    const list = dealsQ.data?.items ?? [];
    for (const d of list) {
      if (!d.is_active) continue;
      const stageId = overrides[d.id] ?? d.pipeline_stage_id;
      if (!stageId || !map.has(stageId)) continue;
      map.get(stageId)!.push(d);
    }
    return map;
  }, [stagesQ.data, dealsQ.data, overrides]);

  const activeDeal = useMemo(
    () => dealsQ.data?.items.find((d) => d.id === activeId) ?? null,
    [dealsQ.data, activeId]
  );

  const moveDeal = useMutation({
    mutationFn: async ({ dealId, stageId }: { dealId: string; stageId: string }) => {
      return apiFetch<Deal>(`/api/v1/deals/${dealId}`, {
        method: "PATCH",
        body: { pipeline_stage_id: stageId },
      });
    },
    onError: (_err, vars) => {
      setOverrides((prev) => {
        const next = { ...prev };
        delete next[vars.dealId];
        return next;
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["deals"] });
    },
  });

  function onDragStart(e: DragStartEvent) {
    setActiveId(String(e.active.id));
  }

  function onDragEnd(e: DragEndEvent) {
    setActiveId(null);
    const dealId = String(e.active.id);
    const overId = e.over?.id ? String(e.over.id) : null;
    if (!overId) return;
    const stages = stagesQ.data ?? [];
    const targetStageId = stages.find((s) => s.id === overId) ? overId : null;
    if (!targetStageId) return;
    const current = dealsQ.data?.items.find((d) => d.id === dealId);
    if (!current) return;
    if (current.pipeline_stage_id === targetStageId) return;
    setOverrides((prev) => ({ ...prev, [dealId]: targetStageId }));
    moveDeal.mutate({ dealId, stageId: targetStageId });
  }

  const isLoading = stagesQ.isLoading || dealsQ.isLoading;
  const isError = stagesQ.isError || dealsQ.isError;
  const errorMsg =
    stagesQ.error instanceof ApiError
      ? stagesQ.error.message
      : dealsQ.error instanceof ApiError
        ? dealsQ.error.message
        : undefined;

  return (
    <div>
      <PageHeader title="Pipeline" description="Drag deals between stages." />
      <div className="p-4 md:p-6">
        {isLoading ? (
          <div className="flex gap-4 overflow-x-auto">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[60vh] w-72 shrink-0" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState
            title="Couldn't load pipeline"
            message={errorMsg}
            onRetry={() => {
              stagesQ.refetch();
              dealsQ.refetch();
            }}
          />
        ) : !stagesQ.data || stagesQ.data.length === 0 ? (
          <EmptyState
            icon={KanbanSquare}
            title="No pipeline stages yet"
            description="Create your first pipeline stage in Settings to start tracking deals."
          />
        ) : (
          <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd}>
            <div className="flex gap-4 overflow-x-auto pb-4">
              {stagesQ.data
                .slice()
                .sort((a, b) => a.position - b.position)
                .map((stage) => (
                  <Column key={stage.id} stage={stage} deals={dealsByStage.get(stage.id) ?? []} />
                ))}
            </div>
            <DragOverlay>{activeDeal ? <DealCard deal={activeDeal} dragging /> : null}</DragOverlay>
          </DndContext>
        )}
      </div>
    </div>
  );
}
