"use client";

import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuthStore } from "@/stores/auth-store";
import { Badge } from "@/components/ui/badge";

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  return (
    <div>
      <PageHeader title="Settings" description="Your profile and workspace." />
      <div className="grid grid-cols-1 gap-4 p-4 md:p-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Profile</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="Name" value={[user?.first_name, user?.last_name].filter(Boolean).join(" ") || "—"} />
            <Row label="Email" value={user?.email ?? "—"} />
            <Row
              label="Role"
              value={user?.role ? <Badge variant="primary">{user.role}</Badge> : "—"}
            />
            <Row label="Workspace ID" value={user?.workspace_id ?? "—"} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">API</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Backend: <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{process.env.NEXT_PUBLIC_API_URL}</code>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[#E2E8F0] py-2 last:border-b-0">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="truncate text-sm text-slate-900">{value}</div>
    </div>
  );
}
