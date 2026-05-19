import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { ListChecks } from "lucide-react";

export default function SequencesPage() {
  return (
    <div>
      <PageHeader title="Sequences" description="Coming soon." />
      <div className="p-4 md:p-6">
        <EmptyState
          icon={ListChecks}
          title="Sequences — coming soon"
          description="Multi-touch outreach cadences will be authored and tracked here."
        />
      </div>
    </div>
  );
}
