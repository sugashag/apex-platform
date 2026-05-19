import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { BarChart3 } from "lucide-react";

export default function ReportsPage() {
  return (
    <div>
      <PageHeader title="Reports" description="Coming soon." />
      <div className="p-4 md:p-6">
        <EmptyState
          icon={BarChart3}
          title="Reports — coming soon"
          description="Pipeline, attribution, and rep performance reports land here next."
        />
      </div>
    </div>
  );
}
