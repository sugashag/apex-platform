"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { Contact, Paginated } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LeadScoreBadge } from "@/components/lead-score-badge";
import { Search, Users } from "lucide-react";

export default function ContactsPage() {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [page, setPage] = useState(1);

  // Tiny debounce without an extra dep.
  useDebounced(search, 250, (v) => {
    setDebounced(v);
    setPage(1);
  });

  const { data, isLoading, isError, refetch } = useQuery<Paginated<Contact>>({
    queryKey: ["contacts", { search: debounced, page }],
    queryFn: () =>
      apiFetch<Paginated<Contact>>("/api/v1/contacts", {
        query: { search: debounced || undefined, page, page_size: 25 },
      }),
    placeholderData: keepPreviousData,
  });

  return (
    <div>
      <PageHeader
        title="Contacts"
        description="People in your CRM."
        actions={
          <div className="relative w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" aria-hidden />
            <Input
              type="search"
              placeholder="Search by name, email, company…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        }
      />
      <div className="space-y-4 p-4 md:p-6">
        {isLoading && !data ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : isError ? (
          <ErrorState onRetry={() => refetch()} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            icon={Users}
            title={debounced ? "No matching contacts" : "No contacts yet"}
            description={
              debounced
                ? "Try a different search."
                : "Contacts will appear here as your team adds them or as leads come in."
            }
          />
        ) : (
          <>
            <Card className="overflow-hidden">
              <div className="hidden grid-cols-12 border-b border-[#E2E8F0] bg-slate-50 px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-500 md:grid">
                <div className="col-span-4">Name</div>
                <div className="col-span-3">Email</div>
                <div className="col-span-2">Source</div>
                <div className="col-span-2">Title</div>
                <div className="col-span-1 text-right">Score</div>
              </div>
              <ul>
                {data.items.map((c) => (
                  <li key={c.id} className="border-b border-[#E2E8F0] last:border-b-0">
                    <Link
                      href={`/contacts/${c.id}`}
                      className="grid grid-cols-1 gap-1 px-4 py-3 hover:bg-slate-50 md:grid-cols-12 md:items-center md:gap-2"
                    >
                      <div className="col-span-4 truncate text-sm font-medium text-slate-900">
                        {[c.first_name, c.last_name].filter(Boolean).join(" ") || c.email}
                      </div>
                      <div className="col-span-3 truncate text-sm text-slate-600">{c.email}</div>
                      <div className="col-span-2 truncate text-sm text-slate-600">{c.source ?? "—"}</div>
                      <div className="col-span-2 truncate text-sm text-slate-600">{c.title ?? "—"}</div>
                      <div className="col-span-1 flex md:justify-end">
                        <LeadScoreBadge score={c.lead_score} />
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
            <Pager
              page={data.page}
              totalPages={data.total_pages}
              total={data.total}
              onChange={setPage}
            />
          </>
        )}
      </div>
    </div>
  );
}

function Pager({
  page,
  totalPages,
  total,
  onChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  onChange: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-between text-sm text-muted-foreground">
      <span>
        Page {page} of {Math.max(1, totalPages)} · {total} total
      </span>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onChange(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

function useDebounced<T>(value: T, delayMs: number, cb: (v: T) => void) {
  useEffect(() => {
    const t = setTimeout(() => cb(value), delayMs);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, delayMs]);
}
