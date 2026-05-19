"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch, ApiError } from "@/lib/api";
import type { Contact, ActivityItem } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/error-state";
import { EmptyState } from "@/components/empty-state";
import { LeadScoreBadge } from "@/components/lead-score-badge";
import { Badge } from "@/components/ui/badge";
import { AiBadge } from "@/components/ai-indicator";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { initials } from "@/lib/utils";
import { Mail, Phone, Briefcase, Globe, Activity, type LucideIcon } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

interface TimelineResponse {
  items?: ActivityItem[];
}

export default function ContactDetailPage({ params }: { params: { id: string } }) {
  const contactQ = useQuery<Contact>({
    queryKey: ["contact", params.id],
    queryFn: () => apiFetch<Contact>(`/api/v1/contacts/${params.id}`),
  });
  const timelineQ = useQuery<TimelineResponse | ActivityItem[]>({
    queryKey: ["contact-timeline", params.id],
    queryFn: () => apiFetch<TimelineResponse | ActivityItem[]>(`/api/v1/contacts/${params.id}/timeline`),
    enabled: !!contactQ.data,
  });

  if (contactQ.isLoading) {
    return (
      <div>
        <PageHeader title="Contact" />
        <div className="space-y-4 p-4 md:p-6">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }
  if (contactQ.isError || !contactQ.data) {
    const err = contactQ.error;
    const msg = err instanceof ApiError ? err.message : undefined;
    return (
      <div>
        <PageHeader title="Contact" />
        <div className="p-4 md:p-6">
          <ErrorState title="Couldn't load contact" message={msg} onRetry={() => contactQ.refetch()} />
        </div>
      </div>
    );
  }

  const c = contactQ.data;
  const fullName = [c.first_name, c.last_name].filter(Boolean).join(" ") || c.email;
  const timelineItems: ActivityItem[] = Array.isArray(timelineQ.data)
    ? timelineQ.data
    : (timelineQ.data?.items ?? []);

  return (
    <div>
      <PageHeader title={fullName} description={c.title ?? "Contact"} />
      <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader className="flex flex-row items-center gap-3">
            <Avatar className="h-12 w-12">
              <AvatarFallback>{initials(c.first_name, c.last_name, c.email)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <CardTitle className="truncate text-base">{fullName}</CardTitle>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <LeadScoreBadge score={c.lead_score} />
                {c.source ? (
                  <Badge variant="primary" aria-label={`Attribution source ${c.source}`}>
                    <Globe className="mr-1 h-3 w-3" aria-hidden />
                    {c.source}
                  </Badge>
                ) : null}
                {c.email_status === "bounced" ? <Badge variant="danger">bounced</Badge> : null}
                {c.email_status === "unsubscribed" ? <Badge variant="warning">unsubscribed</Badge> : null}
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <DetailRow icon={Mail} label="Email" value={c.email} />
            {c.phone ? <DetailRow icon={Phone} label="Phone" value={c.phone} /> : null}
            {c.title ? <DetailRow icon={Briefcase} label="Title" value={c.title} /> : null}
            {c.source_campaign ? <DetailRow label="Campaign" value={c.source_campaign} /> : null}
            {c.source_medium ? <DetailRow label="Medium" value={c.source_medium} /> : null}
            {c.first_seen_at ? (
              <DetailRow
                label="First seen"
                value={formatDistanceToNow(new Date(c.first_seen_at), { addSuffix: true })}
              />
            ) : null}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-slate-500" aria-hidden />
              Activity timeline
            </CardTitle>
          </CardHeader>
          <CardContent>
            {timelineQ.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : timelineQ.isError ? (
              <ErrorState onRetry={() => timelineQ.refetch()} />
            ) : timelineItems.length === 0 ? (
              <EmptyState
                icon={Activity}
                title="No activity yet"
                description="Emails, calls, and notes will appear here."
              />
            ) : (
              <ol className="relative space-y-4 border-l border-[#E2E8F0] pl-5">
                {timelineItems.map((item, idx) => (
                  <li key={item.id ?? idx} className="relative">
                    <span className="absolute -left-[26px] top-1 h-2.5 w-2.5 rounded-full bg-accent" aria-hidden />
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-900">
                        {item.subject ?? item.type ?? "Activity"}
                      </span>
                      {item.is_ai_generated ? <AiBadge /> : null}
                    </div>
                    {item.description ? (
                      <p className="mt-0.5 text-sm text-muted-foreground">{item.description}</p>
                    ) : null}
                    <div className="mt-1 text-xs text-slate-400">
                      {item.user_name ? `${item.user_name} · ` : null}
                      {item.occurred_at
                        ? formatDistanceToNow(new Date(item.occurred_at), { addSuffix: true })
                        : null}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function DetailRow({
  icon: Icon,
  label,
  value,
}: {
  icon?: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-2">
      {Icon ? <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden /> : null}
      <div className="min-w-0">
        <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
        <div className="truncate text-sm text-slate-900">{value}</div>
      </div>
    </div>
  );
}
