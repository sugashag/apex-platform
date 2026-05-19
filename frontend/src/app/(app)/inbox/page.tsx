"use client";

import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Paginated, Thread, ThreadStatus } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { AiBadge } from "@/components/ai-indicator";
import { cn } from "@/lib/utils";
import { Inbox as InboxIcon, Clock, AlertTriangle, CheckCircle2 } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

const STATUS_FILTERS: Array<{ value: ThreadStatus | "all"; label: string }> = [
  { value: "open", label: "Open" },
  { value: "snoozed", label: "Snoozed" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

export default function InboxPage() {
  const [status, setStatus] = useState<ThreadStatus | "all">("open");
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, refetch } = useQuery<Paginated<Thread>>({
    queryKey: ["threads", { status, page }],
    queryFn: () =>
      apiFetch<Paginated<Thread>>("/api/v1/inbox", {
        query: {
          status: status === "all" ? undefined : status,
          page,
          page_size: 25,
        },
      }),
    placeholderData: keepPreviousData,
  });

  return (
    <div>
      <PageHeader
        title="Inbox"
        description="Threads from email, chat, and SMS."
        actions={
          <div className="flex flex-wrap gap-1 rounded-md border border-[#E2E8F0] bg-white p-1">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => {
                  setStatus(f.value);
                  setPage(1);
                }}
                className={cn(
                  "rounded-sm px-3 py-1 text-xs font-medium",
                  status === f.value ? "bg-primary text-primary-foreground" : "text-slate-600 hover:bg-slate-100"
                )}
                aria-pressed={status === f.value}
              >
                {f.label}
              </button>
            ))}
          </div>
        }
      />
      <div className="space-y-4 p-4 md:p-6">
        {isLoading && !data ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState onRetry={() => refetch()} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            icon={InboxIcon}
            title="Inbox zero"
            description="When emails, chats, or SMS come in, threads will show up here."
          />
        ) : (
          <>
            <Card className="overflow-hidden">
              <ul>
                {data.items.map((t) => (
                  <ThreadRow key={t.id} thread={t} />
                ))}
              </ul>
            </Card>
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                Page {data.page} of {Math.max(1, data.total_pages)} · {data.total} total
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={data.page <= 1}
                  onClick={() => setPage(data.page - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={data.page >= data.total_pages}
                  onClick={() => setPage(data.page + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ThreadRow({ thread }: { thread: Thread }) {
  const now = Date.now();
  const slaDue = thread.sla_first_response_due_at
    ? new Date(thread.sla_first_response_due_at).getTime()
    : null;
  const slaBreached = slaDue != null && slaDue < now && !thread.first_responded_at;
  const slaSoon =
    !slaBreached && slaDue != null && slaDue - now < 1000 * 60 * 60 && !thread.first_responded_at;

  return (
    <li className="border-b border-[#E2E8F0] last:border-b-0">
      <div className="flex items-start gap-3 px-4 py-3 hover:bg-slate-50">
        <StatusPill status={thread.status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-semibold text-slate-900">
              {thread.contact_name ?? "Unknown contact"}
            </span>
            {thread.has_ai_draft ? <AiBadge label="AI draft" /> : null}
            {slaBreached ? (
              <Badge variant="danger" className="inline-flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" aria-hidden /> SLA breached
              </Badge>
            ) : slaSoon ? (
              <Badge variant="warning" className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" aria-hidden /> SLA soon
              </Badge>
            ) : null}
          </div>
          <div className="mt-0.5 truncate text-sm text-slate-700">{thread.subject ?? "(no subject)"}</div>
          <div className="mt-1 text-xs text-slate-400">
            {thread.assignee_name ? `Assigned to ${thread.assignee_name} · ` : null}
            {thread.message_count} message{thread.message_count === 1 ? "" : "s"}
            {thread.last_message_at
              ? ` · ${formatDistanceToNow(new Date(thread.last_message_at), { addSuffix: true })}`
              : null}
          </div>
        </div>
      </div>
    </li>
  );
}

function StatusPill({ status }: { status: ThreadStatus }) {
  if (status === "open")
    return (
      <Badge variant="primary" className="mt-0.5 shrink-0">
        open
      </Badge>
    );
  if (status === "snoozed")
    return (
      <Badge variant="warning" className="mt-0.5 inline-flex shrink-0 items-center gap-1">
        <Clock className="h-3 w-3" aria-hidden />
        snoozed
      </Badge>
    );
  return (
    <Badge variant="success" className="mt-0.5 inline-flex shrink-0 items-center gap-1">
      <CheckCircle2 className="h-3 w-3" aria-hidden />
      resolved
    </Badge>
  );
}
