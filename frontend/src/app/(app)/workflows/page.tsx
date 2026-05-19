import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { Workflow } from "lucide-react";

export default function WorkflowsPage() {
  return (
    <div>
      <PageHeader title="Workflows" description="Coming soon." />
      <div className="p-4 md:p-6">
        <EmptyState
          icon={Workflow}
          title="Workflows — coming soon"
          description="Build durable, multi-step automations across your CRM and NetSuite."
        />
      </div>
    </div>
  );
}
