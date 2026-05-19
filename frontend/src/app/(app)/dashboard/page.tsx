"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { DashboardData, ActivityItem } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/error-state";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { AiBadge } from "@/components/ai-indicator";
import { formatCurrency } from "@/lib/utils";
import { Activity, BadgeCheck, DollarSign, Inbox, Phone, AlertCircle } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

function pickNumber(d: DashboardData, keys: string[]): number {
  for (const k of keys) {
    const v = d[k];
    if (typeof v === "number") return v;
  }
  return 0;
}

function pickActivities(d: DashboardData): ActivityItem[] {
  for (const k of ["activity_feed", "recent_activities", "activities"]) {
    const v = d[k];
    if (Array.isArray(v)) return v as ActivityItem[];
  }
  return [];
}

export default function DashboardPage() {
  const { data, isLoading, isError, refetch } = useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: () => apiFetch<DashboardData>("/api/v1/reports/dashboard"),
  });

  return (
    <div>
      <PageHeader title="Dashboard" description="Your day at a glance." />
      <div className="space-y-6 p-4 md:p-6">
        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-28 w-full" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState
            title="Couldn't load dashboard"
            message="We couldn't reach the API. Check your connection and try again."
            onRetry={() => refetch()}
          />
        ) : (
          <>
            <StatGrid data={data!} />
            <ActivityFeed items={pickActivities(data!)} />
          </>
        )}
      </div>
    </div>
  );
}

function StatGrid({ data }: { data: DashboardData }) {
  const openDealsCount = pickNumber(data, ["open_deals_count", "my_open_deals_count", "open_deals"]);
  const openDealsValue = pickNumber(data, [
    "open_deals_value_cents",
    "my_open_deals_value_cents",
    "open_deals_value",
  ]);
  const callsToday = pickNumber(data, ["calls_today", "calls_today_count"]);
  const emailsUnread = pickNumber(data, ["emails_unread", "inbox_unread", "unread_emails"]);
  const leadAlerts = pickNumber(data, ["lead_score_alerts", "lead_alerts", "hot_leads"]);

  const stats = [
    {
      label: "My Open Deals",
      value: openDealsCount.toLocaleString(),
      sub: formatCurrency(openDealsValue),
      icon: BadgeCheck,
    },
    { label: "Calls Today", value: callsToday.toLocaleString(), icon: Phone },
    { label: "Emails in Inbox", value: emailsUnread.toLocaleString(), icon: Inbox },
    { label: "Lead Score Alerts", value: leadAlerts.toLocaleString(), icon: AlertCircle },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {stats.map((stat) => {
        const Icon = stat.icon;
        return (
          <Card key={stat.label}>
            <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-slate-600">{stat.label}</CardTitle>
              <Icon className="h-4 w-4 text-slate-400" aria-hidden />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold text-slate-900">{stat.value}</div>
              {stat.sub ? <div className="mt-1 text-xs text-muted-foreground">{stat.sub}</div> : null}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function ActivityFeed({ items }: { items: ActivityItem[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Activity className="h-4 w-4 text-slate-500" aria-hidden />
          Activity
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No recent activity"
            description="Activity from calls, emails, and deals will appear here once your team gets going."
          />
        ) : (
          <ul className="divide-y divide-[#E2E8F0]">
            {items.slice(0, 20).map((item, idx) => (
              <li key={item.id ?? idx} className="flex items-start gap-3 py-3">
                <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-accent" aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-900">
                      {item.subject ?? item.type ?? "Activity"}
                    </span>
                    {item.is_ai_generated ? <AiBadge /> : null}
                  </div>
                  {item.description ? (
                    <p className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">{item.description}</p>
                  ) : null}
                  <div className="mt-1 text-xs text-slate-400">
                    {item.user_name ? `${item.user_name} · ` : null}
                    {item.occurred_at
                      ? formatDistanceToNow(new Date(item.occurred_at), { addSuffix: true })
                      : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
